"""Line execution: the new tests of a PR must EXECUTE the changed lines of its production code (Parte de #1649, m3).

A test that only reads the source text (`assert "return a - b" in src`) or pins a file's sha256 runs and passes without
calling the code it names. Red/green and mutation do not see that, and `usage` only catches part of it. This check runs
the PR's new tests under `coverage` (inside the same wrapper as the other checks) and asks, per changed production file,
whether at least `MIN_EXECUTED` of its changed statements ran.

- A changed statement is an added line that `coverage` counts as a statement and that is not a `def`/`class` header:
  blank lines, comments, docstrings and `else:`/`try:` do not count. A file with no such line is not judged.
- The threshold is `MIN_EXECUTED = 1` executed changed statement per changed production file: a start, not a proof of
  full coverage. Raising it changes the rule for every PR.
- `coverage` is not a runtime dependency. When the run's interpreter cannot import it, the check is SKIPPED with the
  reason; it never passes silently.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import diffs, identity, isolation, redgreen
from .diffs import FileChange
from .model import ERROR, FAIL, PASS, SKIPPED, CheckResult

NAME = "line_coverage"
MIN_EXECUTED = 1
REPORT_NAME = ".review_gate_lines.json"  # written inside the head tree (the jail's only writable place), read and removed

_TRIVIAL = re.compile(r"^\s*(?:#|pass\s*$|import\s|from\s+\S+\s+import\b|(?:async\s+)?def\s|class\s|@|else:|try:|finally:|[)\]}],?\s*$)")

# The interpreter runs coverage around pytest, in memory (`data_file=None`) and measuring the head tree (cwd). The editable
# finder removal is the one of `pytest_cmd`: no module the tree lacks is served from another checkout.
_BOOT = (
    "import sys\n"
    "import coverage\n"
    "cov = coverage.Coverage(data_file=None, source=['.'])\n"
    "cov.start()\n"
    "sys.meta_path[:] = [f for f in sys.meta_path if 'editable' not in (getattr(f, '__module__', '') + getattr(f, '__name__', '')).lower()]\n"
    "import pytest\n"
    "code = pytest.main(sys.argv[2:])\n"
    "cov.stop()\n"
    "cov.json_report(outfile=sys.argv[1])\n"
    "sys.exit(code)\n"
)


def is_trivial(line: str) -> bool:
    """A changed line that is not a statement of behavior: blank, comment, pass, import, a header or a block keyword."""
    return not line.strip() or bool(_TRIVIAL.match(line))


def _env(head_root: Path, env: Mapping[str, str] | None, home: Path | None) -> dict[str, str]:
    full_env = isolation.child_env(env, home)  # the PR's code never gets the watcher's environment
    if env and "PYTHONPATH" in env:
        full_env["PYTHONPATH"] = os.pathsep.join(str(head_root / p) if not os.path.isabs(p) else p for p in env["PYTHONPATH"].split(os.pathsep))
    return full_env


def _run(argv: list[str], head_root: Path, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=head_root, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"cannot run coverage: interpreter or command not found: {argv[0]} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"timeout of {timeout:g}s running the new tests under coverage on head") from exc


def _new_test_ids(head_root: Path, changes: Sequence[FileChange]) -> list[str]:
    ids: list[str] = []
    for change in changes:
        if change.kind != "test" or change.status not in ("A", "M") or diffs.is_pytest_infra(change.path):
            continue
        text = (head_root / change.path).read_text(encoding="utf-8")
        ids += [ref.node_id for ref in redgreen.new_tests(change.path, text, change.added)]
    return sorted(set(ids))


def check_line_coverage(head_root: Path, changes: Sequence[FileChange], *, python: str = sys.executable, timeout: float = 300.0,
                        wrap: Callable[[list[str]], list[str]] = lambda argv: argv, env: Mapping[str, str] | None = None,
                        home: Path | None = None) -> CheckResult:
    """Run the new tests of the head tree under coverage and judge each changed production file by its executed statements."""
    code = [c for c in changes if c.kind == "code" and c.status in ("A", "M")]
    if not code:
        return CheckResult(NAME, SKIPPED, (identity.non_python_skip_reason(changes) or "sem codigo de producao Python alterado",))
    try:
        ids = _new_test_ids(head_root, changes)
        run_env = _env(head_root, env, home)
        probe = _run(wrap([python, "-c", "import coverage"]), head_root, run_env, 60)
        if probe.returncode != 0:  # honest skip: the gate cannot measure lines without coverage in its interpreter
            why = (probe.stderr or probe.stdout).strip()[-200:] or f"exit {probe.returncode}"
            return CheckResult(NAME, SKIPPED, (f"coverage nao importavel no python do portao ({python}): {why}; "
                                               "sem ele a execucao das linhas alteradas nao e medida",))
        if not ids:
            return CheckResult(NAME, FAIL, ("lines_not_executed: nenhum teste novo executa a producao alterada: "
                                            + ", ".join(c.path for c in code[:5]),))
        report = head_root / REPORT_NAME
        argv = [python, "-c", _BOOT, str(report), "-q", "--tb=no", "-p", "no:cacheprovider", "-o", "addopts=", "--confcutdir", ".",
                *redgreen.pytest_config(head_root), "--continue-on-collection-errors", *ids]
        done = _run(wrap(argv), head_root, run_env, timeout)
        if not report.is_file():
            raise RuntimeError(f"coverage wrote no report (exit {done.returncode}): {(done.stderr or done.stdout)[-300:].strip()}")
        files = json.loads(report.read_text(encoding="utf-8")).get("files", {})
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
        return CheckResult(NAME, ERROR, (f"line coverage could not run: {exc}",))
    finally:
        (head_root / REPORT_NAME).unlink(missing_ok=True)
    return _judge(head_root, code, files, ids)


def _judge(head_root: Path, code: Sequence[FileChange], files: Mapping[str, dict], ids: Sequence[str]) -> CheckResult:
    by_path = {Path(os.path.relpath(head_root / key, head_root)).as_posix(): entry for key, entry in files.items()}
    measured: dict = {"tests": len(ids), "files": {}}
    reasons: list[str] = []
    for change in code:
        lines = (head_root / change.path).read_text(encoding="utf-8").splitlines()
        entry = by_path.get(change.path, {})
        executed = set(entry.get("executed_lines", []))
        statements = executed | set(entry.get("missing_lines", []))
        changed = [n for n in change.added if n in statements and 0 < n <= len(lines) and not is_trivial(lines[n - 1])]
        if not changed:
            continue  # the file changed no statement of behavior: nothing to judge
        hits = [n for n in changed if n in executed]
        not_run = [n for n in changed if n not in executed]
        measured["files"][change.path] = {"changed": len(changed), "executed": len(hits), "first_not_executed": not_run[:5]}
        if len(hits) < MIN_EXECUTED:
            reasons.append(f"lines_not_executed: {change.path} ({len(hits)} de {len(changed)} linha(s) alterada(s) executada(s) pelos "
                           f"testes novos; primeiras nao executadas: {', '.join(str(n) for n in not_run[:5])})")
    return CheckResult(NAME, FAIL if reasons else PASS, tuple(reasons), measured)
