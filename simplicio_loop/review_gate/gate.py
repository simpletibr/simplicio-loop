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

from . import coverage, diffs, docs, identity, mutation, redgreen, usage
from .diffs import FileChange
from .identity import Agent
from .model import ERROR, CheckResult, GateReport

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
    wrap_for: Callable[[Path], Callable[[list], list]] = lambda root: (lambda argv: argv)  # noqa: E731
    extra: tuple[CheckResult, ...] = field(default=())  # checks run elsewhere (endpoint_compare ...) with their cause


def _git(repo: Path, *args: str, timeout: float = 120) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {done.stderr.strip()[-200:]}")
    return done.stdout


def default_env(root: Path) -> dict[str, str]:
    paths = [p for p in (".", "packages/dev-cli", "packages/mapper") if p == "." or (root / p).is_dir()]
    return {"PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}


def neighbors(root: Path, changes: list[FileChange]) -> list[str]:
    """Tests (outside the changed ones) that import a changed production module, so a mutant is also tried against them."""
    changed_tests = {c.path for c in changes if c.kind == "test"}
    stems = {Path(c.path).stem for c in changes if c.kind == "code" and c.status in ("A", "M")}
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


def _base_public(base_root: Path, changes: list[FileChange]) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    for c in changes:
        if c.kind == "code" and c.status == "M" and (base_root / c.path).is_file():
            out[c.path] = frozenset(usage.public_names((base_root / c.path).read_text(encoding="utf-8")))
    return out


def run_gate(inp: GateInput) -> GateReport:
    start = time.monotonic()
    changes = diffs.changed_files(inp.repo, inp.base, inp.head)
    level = identity.classify_level(changes)
    work = inp.repo / REPORT_DIR / f"pr-{inp.pr}-{inp.head[:7]}"
    base_root, head_root = work / "base", work / "head"
    created: list[Path] = []
    try:
        work.mkdir(parents=True, exist_ok=False)
        for root, rev in ((base_root, inp.base), (head_root, inp.head)):
            _git(inp.repo, "worktree", "add", "--detach", "--quiet", str(root), rev)
            created.append(root)
        env = default_env(head_root)
        added = _added_text(head_root, changes)
        test_files = [c.path for c in changes if c.kind == "test" and c.status in ("A", "M") and not c.path.endswith("conftest.py")]
        tests = [*test_files, *neighbors(head_root, changes)]
        argv = [inp.python, "-m", "pytest", "-q", "-x", "--tb=no", "-p", "no:cacheprovider", "-o", "addopts=", *tests] if tests else []
        checks = [
            _timed("redgreen", lambda: redgreen.check_redgreen(base_root, head_root, changes, python=inp.python,
                                                               timeout=inp.test_timeout_s, wrap=inp.wrap_for(head_root), env=env)),
            _timed("mutation", lambda: mutation.check_mutation(head_root, changes, argv, n=inp.n_mutants, min_kill=inp.min_kill,
                                                               timeout_each=inp.mutant_timeout_s, seed=inp.head,
                                                               wrap=inp.wrap_for(head_root), env=env)),
            _timed("usage", lambda: usage.check_usage(head_root, changes, _base_public(base_root, changes))),
            _timed("coverage", lambda: coverage.check_coverage(inp.issue, inp.issue_body, changes, added, inp.pr_body)),
            _timed("docs", lambda: docs.check_docs(base_root, head_root, changes)),
            _timed("identity", lambda: identity.check_identity(inp.author, inp.reviewer, level, inp.independent)),
            *inp.extra,
        ]
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
