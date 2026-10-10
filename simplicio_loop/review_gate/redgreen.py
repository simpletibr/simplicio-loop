"""Red-to-green: every new behavior test fails on main without the change and passes with it.

Runs only the new or changed test functions on `head_root` (all must pass), and the test files that hold them on
`base_root` (production of main) with the head's test files copied over it. A new test that passes on main proves
nothing about the change and is rejected with its id. A test whose name or docstring says `characterization` is
declared as already true on main: it is exempt, and still listed in `measured["exempt"]`.
`base_root` and `head_root` are disposable trees the caller created; this module writes only test files into `base_root`.

The pytest that judges the PR is main's: a `conftest.py` (any depth), pytest configuration or plugin module the PR adds or
changes (`diffs.is_pytest_infra`) can force any outcome, so it is never copied into `base_root` and is replaced by main's
version (or removed) in `head_root` before anything runs (`neutralize_pytest_infra`). A new test that needs the PR's own
conftest therefore fails honestly, and the message says so.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection, Mapping, Sequence

from . import isolation, pytest_cmd
from .diffs import PYTEST_CONFIG_NAMES, FileChange, is_pytest_infra
from .model import ERROR, FAIL, PASS, SKIPPED, CheckResult

NAME = "redgreen"
EXEMPT_WORD = "characterization"
_OUTCOME = re.compile(r"^(PASSED|FAILED|ERROR) (\S+?)(?:\[.*?\])?(?: - .*)?$")


@dataclass(frozen=True)
class TestRef:
    __test__ = False  # not a pytest class
    path: str
    name: str
    classname: str | None
    exempt: bool

    @property
    def node_id(self) -> str:
        return "::".join(filter(None, (self.path, self.classname, self.name)))


def _is_test_func(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")


def _span(node: ast.AST) -> range:
    first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
    return range(first, node.end_lineno + 1)


def new_tests(path: str, source: str, added: Collection[int]) -> list[TestRef]:
    """The test functions of `source` that overlap the added lines (module level and `Test*` classes)."""
    tree = ast.parse(source, filename=path)
    lines = set(added)
    found: list[TestRef] = []

    def visit(body: Sequence[ast.stmt], classname: str | None) -> None:
        for node in body:
            if _is_test_func(node) and lines.intersection(_span(node)):
                doc = ast.get_docstring(node) or ""
                found.append(TestRef(path, node.name, classname, EXEMPT_WORD in (node.name + " " + doc).lower()))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                visit(node.body, node.name if classname is None else f"{classname}::{node.name}")

    visit(tree.body, None)
    return found


def parse_outcomes(output: str) -> dict[str, str]:
    """`pytest -rA` short summary -> {id without params: passed|failed|error}; a file error is keyed by the file."""
    result: dict[str, str] = {}
    for line in output.splitlines():
        found = _OUTCOME.match(line.strip())
        if not found:
            continue
        verdict, key = found.group(1).lower(), found.group(2)
        if verdict == "passed" and result.get(key) in ("failed", "error"):
            continue
        result[key] = verdict
    return result


_CONFIG_SECTION = {"pyproject.toml": "[tool.pytest", "tox.ini": "[pytest]", "setup.cfg": "[tool:pytest]"}


def _pytest_config(root: Path) -> list[str]:
    """`-c <file>` when the tree has pytest configuration (the file pytest itself would pick), else `-c /dev/null`: a pytest.ini
    above the tree is never searched. The file is relative to the tree, which is the cwd of the run; the rootdir is the tree."""
    for name in PYTEST_CONFIG_NAMES:
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if name not in _CONFIG_SECTION or _CONFIG_SECTION[name] in text:
            return ["-c", name, "--rootdir", "."]
    return ["-c", os.devnull, "--rootdir", "."]


def neutralize_pytest_infra(base_root: Path, head_root: Path, changes: Sequence[FileChange]) -> list[str]:
    """Make `head_root` run under the pytest infrastructure of main: each conftest/config/plugin file the PR touches is replaced
    by the one in `base_root`, or removed when main has none. Returns the paths the PR touched (empty: nothing to say)."""
    touched = sorted({c.path for c in changes if is_pytest_infra(c.path)})
    for path in touched:
        target, original = head_root / path, base_root / path
        if target.is_symlink() or target.is_file():
            target.unlink()
        if original.is_file() and not original.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    return touched


def _pytest(root: Path, ids: Sequence[str], python: str, timeout: float, wrap: Callable, env: Mapping[str, str] | None,
            where: str, home: Path | None = None) -> dict[str, str]:
    argv = wrap(pytest_cmd.command(python, "-q", "--tb=no", "-rA", "-p", "no:cacheprovider", "-o", "addopts=",
                                    "--confcutdir", ".", *_pytest_config(root), "--continue-on-collection-errors", *ids))
    full_env = isolation.child_env(env, home)  # the PR's code never gets the watcher's environment
    if env and "PYTHONPATH" in env:
        full_env["PYTHONPATH"] = os.pathsep.join(str(root / p) if not os.path.isabs(p) else p
                                                 for p in env["PYTHONPATH"].split(os.pathsep))
    try:
        done = subprocess.run(argv, cwd=root, env=full_env, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"cannot run tests on {where}: interpreter or command not found: {argv[0]} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"timeout of {timeout:g}s running the new tests on {where}") from exc
    outcomes = parse_outcomes(done.stdout)
    if done.returncode != 0 and not outcomes and "No such file" in done.stderr + done.stdout:  # bwrap exits 1 when execvp fails
        raise RuntimeError(f"the interpreter {python} is not visible inside the sandbox on {where}: the sandbox binds / read-only and hides "
                           f"what the clone cannot reach; use an interpreter under /usr or /opt, or the venv of the clone "
                           f"({(done.stderr or done.stdout)[-200:].strip()})")
    if done.returncode not in (0, 1, 2) or (done.returncode == 2 and "ERROR" not in done.stdout):
        raise RuntimeError(f"pytest on {where} exited {done.returncode}: {(done.stderr or done.stdout)[-300:].strip()}")
    return outcomes


def _verdict(outcomes: Mapping[str, str], ref: TestRef) -> str:
    own = outcomes.get(ref.node_id)
    if own is not None:
        return own
    return outcomes.get(ref.path, "missing")  # a collection error took the whole file down


def check_redgreen(base_root: Path, head_root: Path, changes: Sequence[FileChange], *, python: str = sys.executable,
                   timeout: float = 300.0, wrap: Callable = lambda argv: argv,
                   env: Mapping[str, str] | None = None, wrap_for: Callable[[Path], Callable] | None = None,
                   home: Path | None = None) -> CheckResult:
    """`wrap_for(root)` builds the wrapper of the run in `root` (the sandbox does `--chdir <root>`, so one wrapper cannot serve
    both trees); without it `wrap` is used for both. `home` is the HOME of the child (default: an empty, missing directory)."""
    wrap_in = wrap_for or (lambda root: wrap)
    code = [c for c in changes if c.kind == "code" and c.status in ("A", "M")]
    tests = [c for c in changes if c.kind == "test" and c.status in ("A", "M")]
    if not code and not tests:
        return CheckResult(NAME, SKIPPED, ("sem codigo de producao nem teste alterado",))
    if not code:
        return CheckResult(NAME, SKIPPED, ("PR so de testes: nao ha mudanca de producao que deixe um teste vermelho em main",))
    refs: list[TestRef] = []
    for change in tests:
        if is_pytest_infra(change.path):
            continue
        try:
            refs += new_tests(change.path, (head_root / change.path).read_text(encoding="utf-8"), change.added)
        except (OSError, SyntaxError) as exc:
            return CheckResult(NAME, ERROR, (f"cannot read the tests of {change.path}: {exc}",))
    if not refs:
        return CheckResult(NAME, FAIL, ("mudanca de producao sem teste novo ou alterado: " +
                                        ", ".join(c.path for c in code[:5]),))
    ids = sorted({r.node_id for r in refs})
    try:
        infra = neutralize_pytest_infra(base_root, head_root, changes)  # first: the head run is judged by main's pytest too
        head = _pytest(head_root, ids, python, timeout, wrap_in(head_root), env, "head", home)
        for change in tests:  # the head's tests over the production of main
            if is_pytest_infra(change.path):  # base keeps main's conftest, pytest configuration and plugins
                continue
            target = base_root / change.path
            if target.is_symlink():  # never write through a link of main's tree
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(head_root / change.path, target)
        # By file, not by node id: a file that cannot be imported on main (it imports a module only the change adds) has no
        # collectors, and pytest exits 4 on its node ids instead of reporting `ERROR <file>`, which is the red we want.
        base = _pytest(base_root, sorted({r.path for r in refs}), python, timeout, wrap_in(base_root), env, "main", home)
    except RuntimeError as exc:
        return CheckResult(NAME, ERROR, (str(exc),))
    head_failed = [r.node_id for r in refs if _verdict(head, r) != "passed"]
    red = [r.node_id for r in refs if _verdict(base, r) != "passed" and not r.exempt]
    exempt = [r.node_id for r in refs if r.exempt]
    vacuous = [r.node_id for r in refs if _verdict(base, r) == "passed" and not r.exempt]
    measured: dict = {"tests": len(ids), "red": red, "vacuous": vacuous, "exempt": exempt, "head_failed": head_failed}
    reasons: list[str] = []
    note = ""
    if infra:
        note = (" (o PR altera conftest/configuracao/plugin do pytest: " + ", ".join(infra[:5]) + "; o portao roda os testes novos "
                "com os de main, entao um teste que depende deles falha de verdade; mova o que o teste precisa para o proprio "
                "arquivo de teste. Nivel T2)")
        measured.update(pytest_infra_ignored=infra, note=note.strip(" ()"))
    if head_failed:
        reasons.append("testes novos que falham com a mudanca: " + ", ".join(head_failed[:8]) + note)
    if vacuous:
        reasons.append(f"{len(vacuous)} teste(s) novo(s) passam em main sem a mudanca (nao provam nada): " +
                       ", ".join(vacuous[:8]))
    if not red and not vacuous and not head_failed:
        reasons.append("nenhum teste novo falha em main: todos sao isentos (characterization)")
    return CheckResult(NAME, FAIL if reasons else PASS, tuple(reasons), measured)
