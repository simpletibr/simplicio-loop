"""Turbo --verify for the watcher: the repo's own test command, the turbo argv,
and the decision from turbo's JSON whether to open a PR, retry or stop (dead).

The command is `verify` in the repo's loop.toml on the default branch (see `configured_command`): nothing is detected
and there is no fallback, so a repo without it is not worked on. A PR opens only when the tests passed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

UNVERIFIED = "UNVERIFIED|no_test_command"

_REASON_CAP = 400  # the tail of the test output; the caller caps the whole error at 500


def configured_command(config: object) -> str | None:
    """The `verify` command of a parsed loop.toml table: a non-blank string, stripped. None for anything else."""
    command = config.get("verify") if isinstance(config, dict) else None
    if isinstance(command, str) and command.strip():
        return command.strip()
    return None


def turbo_argv(dest: Path, task: str, test_cmd: str | None) -> list[str]:
    """The headless openrouter run: opt-in only (SIMPLICIO_EXECUTOR=openrouter), see host_mode."""
    argv = ["simplicio-loop", "turbo", "--repo", str(dest), "--provider", "openrouter", "--task", task]
    if test_cmd is not None:
        argv += ["--verify", test_cmd]
    return argv


def turbo_request_argv(dest: Path, task: str, run_id: str | None = None, windows: Sequence[dict] = ()) -> list[str]:
    """Host mode step 1: Mapper orients and turbo prints the request (task, map slice, files, format, rules).

    With a ``run_id`` turbo continues the run the watcher opened at intake instead of starting its own.
    """
    argv = ["simplicio-loop", "turbo", "--repo", str(dest), "--task", task]
    if run_id is not None:
        argv += ["--run-id", run_id]
    for window in windows:  # lines the planner asked for (`need`): the request shows them too
        argv += ["--window", f"{window['path']}:{window['start']}-{window['end']}"]
    return argv


def turbo_apply_argv(dest: Path, test_cmd: str | None, run_id: str, leave_open: bool = False) -> list[str]:
    """Host mode step 2: dev-cli applies the plan piped on stdin, continuing the run step 1 started.

    ``leave_open``: an ok run stays open after verify, for the watcher to write its pr stage and close it.
    """
    argv = ["simplicio-loop", "turbo", "--repo", str(dest), "--apply", "-", "--run-id", run_id]
    if leave_open:
        argv.append("--leave-open")
    if test_cmd is not None:
        argv += ["--verify", test_cmd]
    return argv


def parse_turbo(stdout: str) -> dict:
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.rfind('{"schema"')
        if start < 0:
            start = text.rfind("{")
        if start < 0:
            return {"status": "failed", "detail": text[-400:]}
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return {"status": "failed", "detail": text[-400:]}


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
