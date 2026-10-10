"""Author flow: an LLM CLI WITH tools edits a worktree, the loop verifies, and failures go back to the SAME CLI session.

The host-mode executor (``watcher247/host_mode.run_exec``) asks a planner CLI for a JSON plan and lets dev-cli apply it. This is
the second executor, for tasks a plan cannot carry (mostly fixing simplicio-loop itself). Per round:

1. round 1 starts the session (``--session-id``); every later round is a correction (``--resume``, same uuid);
2. the loop reads the diff against the commit the run started from: an empty diff fails the round;
3. a changed path under ``plan_paths.PROTECTED_PATHS`` fails the round (verify is not run on a tree that holds one);
4. the ``verify`` command runs in the worktree; red output goes back as the next correction.

The CLI and the verify command run in the watcher sandbox with an allowlisted env (no GH_TOKEN): with no sandbox engine the run is
refused (``sandbox_unavailable``) unless the caller passes ``allow_unsandboxed=True``. Only ``claude`` is supported; the flags in
``author_argv`` were checked against ``claude --help``. Host git runs with ``core.fsmonitor=false`` so a config the CLI wrote cannot
run a program on the host. Files the repo ignores are not in the diff, so a protected path that is also ignored is not seen.
"""
from __future__ import annotations

import json
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import evidence, model_roles, plan_paths
from .watcher247 import host_mode, proc, sandbox

FAMILIES = ("claude",)
ROLE = "coordination"  # the role that edits code and fixes a failing check (squad coordinator)
ALLOWED_TOOLS = (
    "Read", "Grep", "Glob", "Edit", "Write", "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git add:*)", "Bash(git commit:*)",
)
DISALLOWED_TOOLS = "WebFetch,WebSearch"
AUTHOR_TIMEOUT_S = 900  # one CLI round
VERIFY_TIMEOUT_S = 600
GIT_TIMEOUT_S = 60
DETAIL_CAP = 1500  # the tail of a failure output kept in one failure
PROMPT_CAP = 6000  # a whole correction prompt
GIT = ["git", "-c", "core.fsmonitor=false"]
USAGE_KEYS = {"input_tokens": "input_tokens", "output_tokens": "output_tokens", "cache_read_tokens": "cache_read_input_tokens"}

Runner = Callable[..., Awaitable[proc.Result]]  # proc.run's shape: runner(argv, timeout=, cwd=, env=)

AUTHOR_PREAMBLE = (
    "You are the author. Edit the files in this worktree to do the task below. Never change these protected paths: {protected}. "
    "Do not push and do not open a pull request. The host runs {verify} after you finish and sends you any failure to correct.\n\nTask:\n\n"
)
ADVICE = {
    "verify_failed": "The verify command failed. Fix the code. Output (tail):\n{detail}",
    "protected_path": "You changed protected paths. Undo every change to them (`git diff` shows the original):\n{detail}",
    "empty_diff": "You made no change to any file. Edit the files that the task needs.",
}


class AuthorUnsupported(Exception):
    """The family has no verified author argv."""

    def __init__(self, family: str):
        super().__init__(f"author flow supports only {', '.join(FAMILIES)}; got {family!r}")
        self.family = family


@dataclass(frozen=True)
class AuthorResult:
    """``status`` ok|failed|unsupported. ``usage``: MEASURED counters from the CLI envelope, None when it reported none."""

    status: str
    rounds: int
    session_id: str
    changed: list[str]
    failures: list[dict[str, str]]
    usage: dict[str, int] | None
    reason_code: str


def author_argv(family: str, prompt: str, *, session: str, resume: bool, model: str, effort: str) -> list[str]:
    """The claude argv for one round. ``allowedTools`` and ``disallowedTools`` take lists, so a flag follows each list."""
    if family not in FAMILIES:
        raise AuthorUnsupported(family)
    argv = ["claude", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    argv += ["--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", DISALLOWED_TOOLS,
             "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "project", "--output-format", "json"]
    return argv + (["--resume", session] if resume else ["--session-id", session])


def _tail(text: str, cap: int = DETAIL_CAP) -> str:
    """Redact first (a cut must not split a secret), then keep the last ``cap`` characters."""
    return evidence.redact_sensitive_text(text)[-cap:]


def correction_prompt(failures: list[dict[str, str]]) -> str:
    """The text of a correction round from the failures of the last one (kinds in ``ADVICE``), without secrets, capped."""
    parts = [ADVICE[f["kind"]].format(detail=_tail(f["detail"])) for f in failures]
    return ("Your last round did not pass.\n\n" + "\n\n".join(parts))[:PROMPT_CAP]


def _usage(stdout: str) -> dict[str, int]:
    """The integer counters of the CLI envelope's ``usage``; a key the CLI left out (or filled with a non-integer) is absent."""
    try:
        usage = json.loads(stdout).get("usage")
    except (ValueError, AttributeError):
        return {}
    if not isinstance(usage, dict):
        return {}
    return {key: usage[source] for key, source in USAGE_KEYS.items()
            if isinstance(usage.get(source), int) and not isinstance(usage[source], bool)}


def _envelope_error(stdout: str) -> bool:
    try:
        return json.loads(stdout).get("is_error") is True
    except (ValueError, AttributeError):
        return False


async def _git(runner: Runner, args: list[str], worktree: Path, env: dict[str, str]) -> proc.Result:
    return await runner([*GIT, *args], timeout=GIT_TIMEOUT_S, cwd=worktree, env=env)


async def _changed(runner: Runner, worktree: Path, env: dict[str, str], base: str) -> list[str] | None:
    """Paths changed since ``base`` (edited, staged, committed, deleted, new): ``git diff`` plus the untracked files; None when git fails."""
    tracked = await _git(runner, ["diff", "--name-only", "--no-renames", "-z", base], worktree, env)
    new = await _git(runner, ["ls-files", "--others", "--exclude-standard", "-z"], worktree, env)
    if tracked.returncode or new.returncode:
        return None
    return sorted({path for out in (tracked.stdout, new.stdout) for path in out.split("\0") if path})


def _protected(changed: list[str], worktree: Path) -> list[str]:
    reasons = (plan_paths.refusal(path, worktree) or plan_paths.protected_refusal(path, worktree) for path in changed)
    return [reason for reason in reasons if reason]


async def run_author(task_text: str, worktree: str | os.PathLike[str], *, family: str = "claude", verify: str | None = None,
                     rounds: int = 3, runner: Runner = proc.run, allow_unsandboxed: bool = False) -> AuthorResult:
    """Author, verify and correct in ``worktree`` for at most ``rounds`` rounds. Never raises for a failed round."""
    worktree = Path(worktree)
    session = str(uuid.uuid4())
    done = {"changed": [], "usage": {}, "measured": 0}

    def result(status: str, n: int, reason: str, failures: list[dict[str, str]]) -> AuthorResult:
        usage = {**done["usage"], "measured_rounds": done["measured"]} if done["measured"] else None
        return AuthorResult(status, n, "" if n == 0 else session, done["changed"], failures, usage, reason)

    if family not in FAMILIES:
        return result("unsupported", 0, "unsupported_family", [{"kind": "unsupported_family", "detail": str(AuthorUnsupported(family))}])
    if not allow_unsandboxed and sandbox.engine() is None:
        return result("failed", 0, "sandbox_unavailable", [{"kind": "sandbox_unavailable", "detail": "no bwrap on this host"}])

    def wrap(argv: list[str], home: sandbox.HomeView | None = None) -> list[str]:
        return argv if allow_unsandboxed else sandbox.wrap(argv, clone=worktree, state_dir=worktree, home=home)

    resolved = model_roles.resolve(family, ROLE)
    env = sandbox.scrubbed_env(os.environ, home=Path.home(), keep=host_mode.FAMILY_ENV[family])
    plain_env = sandbox.scrubbed_env(os.environ, home=Path.home())  # verify sees no provider key either
    head = await _git(runner, ["rev-parse", "HEAD"], worktree, plain_env)
    if head.returncode:
        return result("failed", 0, "git_error", [{"kind": "git_error", "detail": _tail(head.stderr)}])
    base = head.stdout.strip()

    protected = ", ".join(plan_paths.PROTECTED_PATHS)
    prompt = AUTHOR_PREAMBLE.format(protected=protected, verify=f"`{verify}`" if verify else "no command") + task_text
    for n in range(1, rounds + 1):
        argv = author_argv(family, prompt, session=session, resume=n > 1, model=resolved["model"], effort=resolved["effort"])
        try:
            run = await runner(wrap(argv, host_mode.home_view(family)), timeout=AUTHOR_TIMEOUT_S, cwd=worktree, env=env)
        except TimeoutError:
            return result("failed", n, "timeout", [{"kind": "timeout", "detail": f"{family} did not answer in {AUTHOR_TIMEOUT_S}s"}])
        except sandbox.SandboxUnavailable as exc:
            return result("failed", n, "sandbox_unavailable", [{"kind": "sandbox_unavailable", "detail": str(exc)}])
        counters = _usage(run.stdout)
        for key, value in counters.items():
            done["usage"][key] = done["usage"].get(key, 0) + value
        done["measured"] += bool(counters)
        if run.returncode or _envelope_error(run.stdout):
            return result("failed", n, "cli_error", [{"kind": "cli_error", "detail": _tail(f"{run.stdout}\n{run.stderr}")}])

        changed = await _changed(runner, worktree, plain_env, base)
        if changed is None:
            return result("failed", n, "git_error", [{"kind": "git_error", "detail": "git diff failed"}])
        done["changed"] = changed
        failures: list[dict[str, str]] = []
        if not changed:
            failures.append({"kind": "empty_diff", "detail": ""})
        elif reasons := _protected(changed, worktree):
            failures.append({"kind": "protected_path", "detail": "\n".join(reasons)})
        elif verify:
            try:
                check = await runner(wrap(["sh", "-c", verify]), timeout=VERIFY_TIMEOUT_S, cwd=worktree, env=plain_env)
            except TimeoutError:
                failures.append({"kind": "verify_failed", "detail": f"verify did not finish in {VERIFY_TIMEOUT_S}s"})
            else:
                if check.returncode:
                    failures.append({"kind": "verify_failed", "detail": f"exit {check.returncode}\n{check.stdout}\n{check.stderr}"})
        if not failures:
            return result("ok", n, "ok" if verify else "ok_unverified", [])
        prompt = correction_prompt(failures)
    return result("failed", rounds, failures[-1]["kind"], [{**f, "detail": _tail(f["detail"])} for f in failures])
