"""Turbo --verify for the watcher: detect the target repo's test command, build the turbo argv,
and decide from turbo's JSON whether to open a PR, retry or stop (dead).

A PR opens only when the tests passed. A repo with no detectable test command still gets a PR,
labelled UNVERIFIED|no_test_command, never presented as verified.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PYTEST = "python3 -m pytest -q"
NPM = "npm test --silent"
CARGO = "cargo test"
MAKE = "make test"
UNVERIFIED = "UNVERIFIED|no_test_command"

_NPM_PLACEHOLDER = "no test specified"  # npm init's default `test` script is not a test suite
_MAKE_TEST_TARGET = re.compile(r"^test\s*:", re.MULTILINE)
_REASON_CAP = 400  # the tail of the test output; the caller caps the whole error at 500


def _has_text(path: Path, marker: str) -> bool:
    return path.is_file() and marker in path.read_text(errors="replace")


def _has_pytest_evidence(dest: Path) -> bool:
    """A bare pyproject.toml proves nothing (pytest exits 5 when it collects no tests)."""
    return (
        _has_text(dest / "pyproject.toml", "[tool.pytest.ini_options]")
        or (dest / "pytest.ini").is_file()
        or _has_text(dest / "setup.cfg", "[tool:pytest]")
        or (dest / "conftest.py").is_file()
        or any((dest / "tests").rglob("test_*.py"))
    )


def _npm_test_script(dest: Path) -> str | None:
    package = dest / "package.json"
    if not package.is_file():
        return None
    try:
        scripts = json.loads(package.read_text(errors="replace")).get("scripts")
    except (ValueError, AttributeError):
        return None
    test = scripts.get("test") if isinstance(scripts, dict) else None
    if not isinstance(test, str) or not test.strip() or _NPM_PLACEHOLDER in test:
        return None
    return test


def detect_test_command(dest: Path) -> str | None:
    """The test command of the repo checked out at dest, or None when none is detectable."""
    if _has_pytest_evidence(dest):
        return PYTEST
    if _npm_test_script(dest) is not None:
        return NPM
    if (dest / "Cargo.toml").is_file():
        return CARGO
    makefile = dest / "Makefile"
    if makefile.is_file() and _MAKE_TEST_TARGET.search(makefile.read_text(errors="replace")):
        return MAKE
    return None


def turbo_argv(dest: Path, task: str, test_cmd: str | None) -> list[str]:
    argv = ["simplicio-loop", "turbo", "--repo", str(dest), "--provider", "openrouter", "--task", task]
    if test_cmd is not None:
        argv += ["--verify", test_cmd]
    return argv


def retry_or_dead(attempts: int, max_attempts: int) -> str:
    return "dead" if attempts >= max_attempts else "retry"


@dataclass(frozen=True)
class Decision:
    action: str  # "pr" | "retry" | "dead"
    label: str   # the verification line for the PR body and the issue comment
    reason: str = ""


def decide(document: dict, test_cmd: str | None, attempts: int, max_attempts: int) -> Decision:
    """From turbo's JSON and the repo's test command: open the PR, or retry/stop with the reason."""
    status = document.get("status") or "failed"
    report = document.get("verify") if isinstance(document.get("verify"), dict) else None
    if test_cmd is not None and report is not None and not report.get("passed"):
        tail = (report.get("output_tail") or "verify failed without output")[-_REASON_CAP:]
        return Decision(retry_or_dead(attempts, max_attempts), f"MEASURED|verify_failed: `{test_cmd}`",
                        f"verify failed: {tail}")
    if status != "ok":
        reason = document.get("detail") or document.get("reason_code") or status
        return Decision(retry_or_dead(attempts, max_attempts), UNVERIFIED, reason)
    if test_cmd is None:
        return Decision("pr", UNVERIFIED)
    if report is None:  # fail closed: asked for --verify, got no report
        return Decision(retry_or_dead(attempts, max_attempts), UNVERIFIED, "verify did not report a pass")
    return Decision("pr", f"MEASURED|verify_passed: `{test_cmd}`")
