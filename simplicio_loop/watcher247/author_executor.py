"""The author flow as the second executor of the 24/7 watcher (``SIMPLICIO_247_EXECUTOR=author``, #1669).

The default executor (``plan``) is host_mode.run_exec: the LLM returns a JSON plan and dev-cli applies it. With ``author`` an
LLM CLI that has tools edits the item's own worktree (``author_flow.run_author``), the loop runs verify, and a red verify goes back to
the SAME CLI session as a correction. The tick then delivers an ``ok`` result with the same path as the plan flow (commit, push,
draft PR, squad review). A result that is not ``ok`` raises ``AuthorFailed``: the tick releases the claim as it does for any failed run.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import author_flow, execution_report, model_roles
from . import budget, config, host_mode, proc, sandbox, state, worktrees

EXECUTOR_ENV = "SIMPLICIO_247_EXECUTOR"
ROUNDS_ENV = "SIMPLICIO_247_AUTHOR_ROUNDS"
RUN_TESTS_ENV = "SIMPLICIO_247_AUTHOR_RUN_TESTS"
EXECUTORS = ("plan", "author")
DEFAULT_ROUNDS = 3
INVALID = "executor_env_invalid"
NEEDS_EXEC = "author_needs_exec"
HEAD_MOVED = "head_moved"
# The host is set up wrong, not the item: the attempt is given back (like PointDeferred) and the item waits out the retry backoff.
CONFIGURATION = frozenset({"unsupported_family", "sandbox_unavailable", "claude_login_missing", "cli_unavailable", "home_unavailable"})


class AuthorFailed(RuntimeError):
    """The author flow did not finish ok. ``reason_code`` is the claim's reason; ``exec_steps`` the one step it ran."""

    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code

    @property
    def configuration(self) -> bool:
        """True when the host's setup caused it (``CONFIGURATION``): it does not count as an attempt of the item."""
        return self.reason_code in CONFIGURATION


def selected(environ: Mapping[str, str] | None = None) -> str:
    """``plan`` (unset or empty) or ``author``. Any other value is a ValueError that names the allowed ones."""
    environ = os.environ if environ is None else environ
    value = environ.get(EXECUTOR_ENV)
    if not value:  # an EnvironmentFile line `SIMPLICIO_247_EXECUTOR=` sets it to the empty string: that is unset
        return "plan"
    if value not in EXECUTORS:
        raise ValueError(f"{EXECUTOR_ENV}={value!r} is not valid: use {' or '.join(EXECUTORS)} (unset means plan)")
    return value


def rounds(environ: Mapping[str, str] | None = None) -> int:
    """The correction rounds, 1 to ``author_flow.MAX_ROUNDS``; ValueError for anything else."""
    environ = os.environ if environ is None else environ
    raw = environ.get(ROUNDS_ENV)
    if raw is None:
        return DEFAULT_ROUNDS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if not 1 <= value <= author_flow.MAX_ROUNDS or str(value) != raw.strip():
        raise ValueError(f"{ROUNDS_ENV}={raw!r} is not valid: use a whole number from 1 to {author_flow.MAX_ROUNDS} (unset means {DEFAULT_ROUNDS})")
    return value


def cli_runs_tests(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the CLI may run pytest itself: only ``SIMPLICIO_247_AUTHOR_RUN_TESTS=1``. The host verify runs the tests either way.

    On, the author's conftest runs inside the CLI's sandbox, where the private HOME (a copy of the login) is mounted and the network is open.
    """
    return (os.environ if environ is None else environ).get(RUN_TESTS_ENV) == "1"


def refusal(environ: Mapping[str, str] | None = None) -> str | None:
    """The message that stops the watcher at startup, or None. The rounds are read only when the author executor is on."""
    try:
        if selected(environ) == "author":
            rounds(environ)
    except ValueError as exc:
        return str(exc)
    return None


def family_of(executor: host_mode.Executor) -> str:
    """The first usable family that the author flow supports; else the first usable one (the flow then refuses it: unsupported_family)."""
    return next((f for f in executor.families if f in author_flow.FAMILIES), executor.families[0] if executor.families else "")


def _model(family: str) -> dict[str, str]:
    try:
        return model_roles.resolve(family, author_flow.ROLE)
    except model_roles.ModelRoleError:
        return {"model": "", "effort": ""}


def report_of(dest: Path, issue: dict, repo: str, result: author_flow.AuthorResult, family: str, wall_ms: int,
              run_id: str | None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """(steps, execution report) of one author run, in the shape of run_exec: one step with role, family, model, effort, outcome, reason.

    Tokens are the CLI's own counters (cli_measured) or absent; ``measured_rounds`` says for how many rounds the CLI reported any.
    """
    resolved = _model(family)
    ok = result.status == "ok"
    usage = result.usage or {}
    tokens = {name: usage.get(name) for name in ("input_tokens", "output_tokens", "cache_read_tokens")}
    report = execution_report.new_report(dest)
    if run_id:
        report["run_id"] = run_id
    execution_report.record_task(
        report, task_id=f"{repo}#{issue['number']}-author", title=f"watcher author {issue['number']}: {author_flow.ROLE}",
        issue=str(issue["number"]), wall_ms=wall_ms, outcome="COMPLETE" if ok else "FAIL", operators=["author-flow"],
        tokens_in=tokens["input_tokens"], tokens_out=tokens["output_tokens"])
    report["tasks"][-1]["tokens"]["tokens_cached"] = tokens["cache_read_tokens"]  # the CLI's cache read counter, or None
    report["tasks"][-1].update({
        "step": 1, "role": author_flow.ROLE, "family": family, "model": resolved["model"], "effort": resolved["effort"],
        "rounds": result.rounds, "measured_rounds": usage.get("measured_rounds", 0), "author_status": result.status,
        "reason_code": result.reason_code, "failures": [f["kind"] for f in result.failures]})
    report["status"] = "COMPLETE" if ok else "FAILED"
    step = {"role": author_flow.ROLE, "family": family, "model": resolved["model"], "effort": resolved["effort"],
            "outcome": "ok" if ok else "failed", **({} if ok else {"reason": result.reason_code})}
    return [step], report


def describe(result: author_flow.AuthorResult) -> str:
    """One line for the log and the claim: the reason, the rounds, the failure kinds and the MEASURED usage (``none`` when the CLI gave none)."""
    kinds = ",".join(f["kind"] for f in result.failures) or "none"
    usage = " ".join(f"{k}={v}" for k, v in sorted(result.usage.items())) if result.usage else "none"
    return f"reason_code={result.reason_code} rounds={result.rounds} failures={kinds} usage={usage}"


async def head_moved(dest: Path, head: str) -> str:
    """Why the worktree's HEAD is not the item's branch ``head``, or '' when it is. The author can rewrite HEAD in the admin dir."""
    expected = f"refs/heads/{head}"
    found = await proc.run(["git", "symbolic-ref", "HEAD"], cwd=dest)
    actual = found.stdout.strip() if found.returncode == 0 else ""
    if actual == expected:
        return ""
    return f"HEAD of the worktree is {actual or 'not a branch'}, not {expected}"


async def run(dest: Path, repo: str, issue: dict, task: str, test_cmd: str | None, executor: host_mode.Executor, head: str,
              run_id: str | None = None) -> dict[str, Any]:
    """Author, verify and correct in the item's worktree. Returns the claim fields of an ``ok`` run; raises ``AuthorFailed`` otherwise.

    ``head`` is the item's branch: an ``ok`` run whose worktree HEAD is somewhere else fails with ``head_moved`` (nothing is committed).
    Nothing is committed or pushed here: the tick delivers after this returns. The author flow gets no token and no env of the watcher.
    """
    number = int(issue["number"])
    ident = state.key_of(repo, number)
    if dest != worktrees.item_path(repo, number):
        raise AuthorFailed(f"author worktree {dest} is not the item's own worktree", "worktree_mismatch")
    family = family_of(executor)
    started = time.monotonic()
    result = await author_flow.run_author(
        task, dest, family=family, verify=test_cmd, rounds=rounds(), runner=proc.run,
        allow_unsandboxed=os.environ.get(sandbox.OPT_OUT) == "1", run_tests=cli_runs_tests())
    if result.rounds:
        await budget.record("model_calls", result.rounds)  # one call per round that really ran
    moved = await head_moved(dest, head) if result.status == "ok" else ""
    if moved:
        result = replace(result, status="failed", reason_code=HEAD_MOVED, failures=[{"kind": HEAD_MOVED, "detail": moved}])
    steps, report = report_of(dest, issue, repo, result, family, int((time.monotonic() - started) * 1000), run_id)
    report["finished_at_unix"] = int(time.time())
    try:
        execution_report.write_report(dest, report)
    except Exception as exc:  # the report is a record: losing it must not hide what the author did
        state.log(f"author report not written {ident}: {exc}")
    line = describe(result) + (f" detail={moved}" if moved else "")
    state.log(f"author {ident} {result.status} {line}")
    if result.status != "ok":
        error = AuthorFailed(f"author {result.status}: {line}"[:500], result.reason_code)
        error.exec_steps = steps
        raise error
    label = f"MEASURED|verify_passed: `{test_cmd}`" if test_cmd and result.reason_code == "ok" else "UNVERIFIED|no_test_command"
    claim: dict[str, Any] = {"turbo_status": "ok", "exit_code": 0, "verify": label, "executor": "author", "steps": steps,
                             "rounds": result.rounds}
    if result.usage:
        claim["usage"] = result.usage
    return claim
