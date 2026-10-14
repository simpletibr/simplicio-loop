"""The automatic review gate of one PR: runs every check on disposable trees and returns the GateReport.

Everything the gate creates lives under `<repo>/.simplicio-loop/review-gate/` and is removed by exact path
(`git worktree remove` of the two trees it added; the report JSON stays). A check that raises is an `error` with
its cause, never a silent pass. See `comment.py` for the text posted on the PR.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping

from ..watcher247 import sandbox
from . import coverage, diffs, docs, identity, isolation, line_coverage, mutation, pytest_cmd, redgreen, usage
from .diffs import FileChange
from .identity import Agent
from .model import ERROR, FAIL, CheckResult, GateReport

REPORT_DIR = Path(".simplicio-loop") / "review-gate"
DEFAULT_MUTANTS = 12
DEFAULT_MIN_KILL = 0.6
NEIGHBOR_CAP = 8


@dataclass(frozen=True)
class GateInput:
    repo: Path  # a clone that has the objects of `base` and `head`
    pr: int
    issue: int | None
    issue_body: str
    pr_body: str
    base: str
    head: str
    author: Agent
    reviewer: Agent = identity.AUTO_REVIEWER
    independent: Agent | None = None
    n_mutants: int = DEFAULT_MUTANTS
    min_kill: float = DEFAULT_MIN_KILL
    test_timeout_s: float = 300.0
    mutant_timeout_s: float = 120.0
    python: str = sys.executable
    # None (the only value production uses): the gate's own bwrap jail from `isolation.make_jail`, or a rejection with
    # `sandbox_unavailable` when there is none. A callable is a seam for tests that exercise the checks, not the jail.
    wrap_for: Callable[[Path], Callable[[list], list]] | None = None
    state_dir: Path | None = None  # read-only inside the jail; default `<repo>/.simplicio-loop/review-gate` (the watcher passes its state dir)
    extra: tuple[CheckResult, ...] = field(default=())  # checks run elsewhere (endpoint_compare ...) with their cause


class _Refused(Exception):
    """The gate will not run the PR's code; `check` says why and is the whole report."""

    def __init__(self, check: CheckResult) -> None:
        super().__init__(check.name)
        self.check = check


def _git(repo: Path, *args: str, timeout: float = 120) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {done.stderr.strip()[-200:]}")
    return done.stdout


def default_env(root: Path) -> dict[str, str]:
    paths = [p for p in (".", "packages/dev-cli", "packages/mapper") if p == "." or (root / p).is_dir()]
    return {"PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}


def neighbors(root: Path, changes: list[FileChange]) -> list[str]:
    """Tests (outside the changed ones) that import a changed production module or test helper, so a mutant is also tried against them."""
    changed_tests = {c.path for c in changes if c.kind == "test"}
    stems = {Path(c.path).stem for c in changes if c.status in ("A", "M") and (c.kind == "code" or diffs.is_test_helper(c.path))}
    found: list[str] = []
    patterns = [re.compile(rf"(?:from|import)\s+[\w.]*\b{re.escape(s)}\b") for s in sorted(stems)]
    for test in sorted((root / "tests").rglob("test_*.py")) if (root / "tests").is_dir() else []:
        rel = test.relative_to(root).as_posix()
        if rel in changed_tests:
            continue
        try:
            text = test.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(p.search(text) for p in patterns):
            found.append(rel)
        if len(found) >= NEIGHBOR_CAP:
            break
    return found


def head_reader(repo: Path, head: str) -> Callable[[str], str | None]:
    """`read(path)`: the text of `path` at `head` (what the level looks for in a test module), None when git has no such text."""
    def read(path: str) -> str | None:
        try:
            return _git(repo, "show", f"{head}:{path}")
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            return None
    return read


def mutation_argv(python: str, root: Path, tests: list[str]) -> list[str]:
    """The pytest command of the mutation run: pinned to the configuration of the tree like the red/green run (empty: no tests)."""
    if not tests:
        return []
    return pytest_cmd.command(python, "-q", "--tb=no", "-p", "no:cacheprovider", "-o", "addopts=", "--confcutdir", ".",
                              *redgreen.pytest_config(root), *tests)


def _timed(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    start = time.monotonic()
    try:
        result = fn()
    except Exception as exc:  # a check that crashed is a visible error, not a pass  # noqa: BLE001
        result = CheckResult(name, ERROR, (f"{name} could not run: {type(exc).__name__}: {exc}",))
    return replace(result, measured={**result.measured, "elapsed_s": round(time.monotonic() - start, 3)})


def _added_text(root: Path, changes: list[FileChange]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in changes:
        if c.status == "D":
            continue
        try:
            lines = (root / c.path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        out[c.path] = "\n".join(lines[n - 1] for n in c.added if 0 < n <= len(lines))
    return out


def _sources(root: Path, changes: list[FileChange]) -> dict[str, str]:
    """The whole text of each test file the PR adds or changes, so coverage judges a test by its own function."""
    out: dict[str, str] = {}
    for c in changes:
        if c.kind == "test" and c.status != "D":
            try:
                out[c.path] = (root / c.path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return out


def _base_public(base_root: Path, changes: list[FileChange]) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    for c in changes:
        if c.kind == "code" and c.status == "M" and (base_root / c.path).is_file():
            out[c.path] = frozenset(usage.public_names((base_root / c.path).read_text(encoding="utf-8")))
    return out


def run_gate(inp: GateInput) -> GateReport:
    start = time.monotonic()
    changes = diffs.changed_files(inp.repo, inp.base, inp.head)
    level = identity.classify_level(changes, read=head_reader(inp.repo, inp.head))
    work = inp.repo / REPORT_DIR / f"pr-{inp.pr}-{inp.head[:7]}"
    base_root, head_root = work / "base", work / "head"
    created: list[Path] = []
    wrap_for, home, refusal = inp.wrap_for, None, None
    if not changes:  # nothing to review: never approved, whatever the issue says, and nothing to run
        refusal = CheckResult("diff", FAIL, ("empty_diff: o PR nao altera nenhum arquivo; um PR vazio nunca e aprovado",),
                              {"reason_code": "empty_diff"})
    elif symlinks := [c.path for c in changes if c.symlink]:  # a link's target is read on the host by nothing: refused, never followed
        refusal = CheckResult("diff", FAIL, (f"symlink_refused: o PR altera link simbolico, que o gate nao segue: {', '.join(symlinks)}",),
                              {"reason_code": "symlink_refused", "paths": symlinks})
    elif wrap_for is None:  # the PR's code runs in the gate's own jail, or it does not run
        state = inp.state_dir or inp.repo / REPORT_DIR
        try:
            state.mkdir(parents=True, exist_ok=True)
            jail = isolation.make_jail(state, inp.python)
            wrap_for, home = jail.wrap_for, jail.home
        except sandbox.SandboxUnavailable as exc:
            refusal = CheckResult("sandbox", ERROR, (f"{exc.reason_code}: {exc}",), {"reason_code": exc.reason_code})
    try:
        if refusal is not None:
            raise _Refused(refusal)
        work.mkdir(parents=True, exist_ok=False)
        for root, rev in ((base_root, inp.base), (head_root, inp.head)):
            _git(inp.repo, "worktree", "add", "--detach", "--quiet", str(root), rev)
            created.append(root)
        redgreen.neutralize_pytest_infra(base_root, head_root, changes)  # no check runs under a conftest/config/plugin the PR wrote
        env = default_env(head_root)
        added = _added_text(head_root, changes)
        test_files = [c.path for c in changes if c.kind == "test" and c.status in ("A", "M") and not diffs.is_pytest_infra(c.path)]
        near = neighbors(head_root, changes)
        argv = mutation_argv(inp.python, head_root, [*test_files, *near])
        red = _timed("redgreen", lambda: redgreen.check_redgreen(base_root, head_root, changes, python=inp.python,
                                                                 timeout=inp.test_timeout_s, wrap_for=wrap_for, env=env, home=home,
                                                                 neighbours=near))
        checks = [
            red,
            _timed("line_coverage", lambda: line_coverage.check_line_coverage(head_root, changes, python=inp.python,
                                                                              timeout=inp.test_timeout_s, wrap=wrap_for(head_root),
                                                                              env=env, home=home)),
            _timed("mutation", lambda: mutation.check_mutation(head_root, changes, argv, n=inp.n_mutants, min_kill=inp.min_kill,
                                                               timeout_each=inp.mutant_timeout_s, seed=inp.head,
                                                               wrap=wrap_for(head_root), env=env, home=home,
                                                               red=red.measured.get("red", ()))),
            _timed("usage", lambda: usage.check_usage(head_root, changes, _base_public(base_root, changes))),
            _timed("coverage", lambda: coverage.check_coverage(inp.issue, inp.issue_body, changes, added, inp.pr_body,
                                                               sources=_sources(head_root, changes))),
            _timed("docs", lambda: docs.check_docs(base_root, head_root, changes)),
            _timed("identity", lambda: identity.check_identity(inp.author, inp.reviewer, level, inp.independent)),
            *inp.extra,
        ]
    except _Refused as refused:
        checks = [refused.check]
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        checks = [CheckResult("setup", ERROR, (f"gate could not prepare its trees: {exc}",))]
    finally:
        for root in reversed(created):  # only what this run created, by exact path
            subprocess.run(["git", "worktree", "remove", "--force", str(root)], cwd=inp.repo, capture_output=True, check=False)
        try:
            work.rmdir()
        except OSError:
            pass
    partial = any(c.name == "coverage" and c.measured.get("partial") for c in checks)
    report = GateReport(inp.pr, inp.issue, inp.head, level, tuple(checks), partial, time.monotonic() - start)
    out = inp.repo / REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / f"pr-{inp.pr}-{inp.head[:7]}.json").write_text(report.to_json() + "\n", encoding="utf-8")
    return report
