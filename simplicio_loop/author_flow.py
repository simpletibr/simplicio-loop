"""Author flow: an LLM CLI WITH tools edits a worktree, the loop verifies, and failures go back to the SAME CLI session.

The host-mode executor (``watcher247/host_mode.run_exec``) asks a planner CLI for a JSON plan and lets dev-cli apply it. This is
the second executor, for tasks a plan cannot carry (mostly fixing simplicio-loop itself). Per round:

1. round 1 starts the session (``--session-id``); every later round is a correction (``--resume``, same uuid);
2. ``changed`` is the difference between a file system snapshot taken before round 1 and one taken after the CLI
   (``author_isolation``; git is never asked): no change fails the round (``empty_diff``);
3. a changed path under ``plan_paths.PROTECTED_PATHS`` fails the round (verify is not run on a tree that holds one);
4. the ``verify`` command runs in the worktree, and a third snapshot catches what IT wrote: the verify command runs the author's
   code (a conftest), so a protected path it creates fails the round (``protected_path``) even when verify passed. Red output
   goes back as the next correction.

The CLI runs with a private HOME that holds a copy of the login and nothing else (settings it could load are removed before each
round, and ``--setting-sources user`` never reads the worktree's ``.claude``). The verify command sees an empty HOME. Both run in the
watcher sandbox with an allowlisted env (no GH_TOKEN): with no sandbox engine the run is refused (``sandbox_unavailable``) unless the
caller passes ``allow_unsandboxed=True``. Only ``claude`` is supported; the flags in ``author_argv`` were checked against
``claude --help``. The sandbox keeps the network open: the author's code can reach the network.
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from . import author_isolation, evidence, model_roles, plan_paths
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
DETAIL_CAP = 1500  # the tail of a failure output kept in one failure
PROMPT_CAP = 6000  # a whole correction prompt
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
             "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "user", "--output-format", "json"]
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


def _protected(changed: list[str], worktree: Path) -> list[str]:
    reasons = (plan_paths.refusal(path, worktree) or plan_paths.protected_refusal(path, worktree) for path in changed)
    return [reason for reason in reasons if reason]


async def run_author(task_text: str, worktree: str | os.PathLike[str], *, family: str = "claude", verify: str | None = None,
                     rounds: int = 3, runner: Runner = proc.run, allow_unsandboxed: bool = False) -> AuthorResult:
    """Author, verify and correct in ``worktree`` for at most ``rounds`` rounds. A failed round is a result, not an exception."""
    worktree = Path(worktree)
    session = str(uuid.uuid4())
    done = {"changed": [], "usage": {}, "measured": 0}

    def result(status: str, n: int, reason: str, failures: list[dict[str, str]]) -> AuthorResult:
        usage = {**done["usage"], "measured_rounds": done["measured"]} if done["measured"] else None
        return AuthorResult(status, n, "" if n == 0 else session, done["changed"], failures, usage, reason)

    if family not in FAMILIES:
        return result("unsupported", 0, "unsupported_family", [{"kind": "unsupported_family", "detail": str(AuthorUnsupported(family))}])
    if rounds < 1:
        return result("failed", 0, "bad_rounds", [{"kind": "bad_rounds", "detail": f"rounds must be 1 or more; got {rounds}"}])
    if not allow_unsandboxed and sandbox.engine() is None:
        return result("failed", 0, "sandbox_unavailable", [{"kind": "sandbox_unavailable", "detail": "no bwrap on this host"}])

    real_home = Path.home()
    try:
        home = author_isolation.make_home(real_home, session)
    except author_isolation.LoginMissing as exc:
        return result("failed", 0, "claude_login_missing", [{"kind": "claude_login_missing", "detail": str(exc)}])

    def wrap(argv: list[str], view: sandbox.HomeView) -> list[str]:
        return argv if allow_unsandboxed else sandbox.wrap(argv, clone=worktree, state_dir=worktree, home=view)

    async def launch(argv: list[str], view: sandbox.HomeView, env: dict[str, str], timeout: int):
        """(run, None), or (None, (reason_code, detail)) when the process did not start or did not finish."""
        try:
            return await runner(wrap(argv, view), timeout=timeout, cwd=worktree, env=env), None
        except TimeoutError:  # before OSError: it is one
            return None, ("timeout", f"{argv[0]} did not finish in {timeout}s")
        except sandbox.SandboxUnavailable as exc:
            return None, ("sandbox_unavailable", str(exc))
        except OSError as exc:
            return None, ("argv_too_long" if exc.errno == errno.E2BIG else "cli_unavailable", str(exc))

    resolved = model_roles.resolve(family, ROLE)
    cli_env = sandbox.scrubbed_env(os.environ, home=home, keep=host_mode.FAMILY_ENV[family])  # HOME is the private one
    cli_view = sandbox.HomeView(real_home, rw=(str(home.relative_to(real_home)),), ro=host_mode.FAMILY_HOME[family]["ro"])
    verify_env = sandbox.scrubbed_env(os.environ, home=real_home)  # no provider key; the sandbox shows an empty HOME
    verify_view = sandbox.HomeView(real_home)
    prompt = AUTHOR_PREAMBLE.format(protected=", ".join(plan_paths.PROTECTED_PATHS), verify=f"`{verify}`" if verify else "no command") + task_text

    try:
        before = await asyncio.to_thread(author_isolation.snapshot, worktree)
        for n in range(1, rounds + 1):
            author_isolation.reset_config(home)
            argv = author_argv(family, prompt, session=session, resume=n > 1, model=resolved["model"], effort=resolved["effort"])
            run, error = await launch(argv, cli_view, cli_env, AUTHOR_TIMEOUT_S)
            if error:
                return result("failed", n, error[0], [{"kind": error[0], "detail": error[1]}])
            counters = _usage(run.stdout)
            for key, value in counters.items():
                done["usage"][key] = done["usage"].get(key, 0) + value
            done["measured"] += bool(counters)
            if run.returncode or _envelope_error(run.stdout):
                return result("failed", n, "cli_error", [{"kind": "cli_error", "detail": _tail(f"{run.stdout}\n{run.stderr}")}])

            changed = author_isolation.diff(before, await asyncio.to_thread(author_isolation.snapshot, worktree))
            done["changed"] = changed
            failures: list[dict[str, str]] = []
            if not changed:
                failures.append({"kind": "empty_diff", "detail": ""})
            elif reasons := _protected(changed, worktree):
                failures.append({"kind": "protected_path", "detail": "\n".join(reasons)})
            elif verify:
                check, error = await launch(["sh", "-c", verify], verify_view, verify_env, VERIFY_TIMEOUT_S)
                if error:
                    failures.append({"kind": "verify_failed", "detail": f"{error[0]}: {error[1]}"})
                elif check.returncode:
                    failures.append({"kind": "verify_failed", "detail": f"exit {check.returncode}\n{check.stdout}\n{check.stderr}"})
                planted = _protected(author_isolation.diff(before, await asyncio.to_thread(author_isolation.snapshot, worktree)), worktree)
                if planted:  # the verify command ran the author's code after the check above
                    failures.append({"kind": "protected_path", "detail": "\n".join(planted)})
            if not failures:
                return result("ok", n, "ok" if verify else "ok_unverified", [])
            prompt = correction_prompt(failures)
        return result("failed", rounds, failures[-1]["kind"], [{**f, "detail": _tail(f["detail"])} for f in failures])
    finally:
        author_isolation.drop_home(real_home, home)
