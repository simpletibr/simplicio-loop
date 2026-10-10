"""Author flow: an LLM CLI WITH tools edits a worktree, the loop verifies, and failures go back to the SAME CLI session.

The host-mode executor (``watcher247/host_mode.run_exec``) asks a planner CLI for a JSON plan and lets dev-cli apply it. This is
the second executor, for tasks a plan cannot carry (mostly fixing simplicio-loop itself). Per round:

1. round 1 starts the session (``--session-id``); every later round is a correction (``--resume``, same uuid);
2. ``changed`` is the difference between a file system snapshot taken before round 1 and one taken after the CLI
   (``author_isolation``; git is never asked): no change fails the round (``empty_diff``);
3. a changed path under ``plan_paths.PROTECTED_PATHS`` fails the round (verify is not run on a tree that holds one);
4. the ``verify`` command runs in the worktree, and a snapshot after it catches what IT wrote: the verify command runs the author's
   code (a conftest), so a protected path it creates fails the round (``protected_path``) even when verify passed. Red output
   goes back as the next correction.

A CLI round that hits the time limit (``author_timeout``) is not fatal while rounds remain: the loop keeps the worktree, takes the
snapshot, and the next round resumes the same session with a continuation prompt. A timeout counts as a round. The last round that
times out ends the run (``timeout``) and ``changed`` still lists the files.

``changed`` in the result is always the original snapshot against the last one taken (after verify, or after a CLI error).

The CLI runs with a private HOME that holds a copy of the login and nothing else (settings it could load are removed before each
round, and ``--setting-sources user`` never reads the worktree's ``.claude``). The verify command sees an empty HOME. Neither gets an
API key: the login is the file. Both run in the watcher sandbox with an allowlisted env (no GH_TOKEN) and
``PYTHONDONTWRITEBYTECODE=1``: with no sandbox engine the run is refused (``sandbox_unavailable``) unless the caller passes
``allow_unsandboxed=True``. Only ``claude`` is supported; the flags in ``author_argv`` were checked against ``claude --help``. The
sandbox keeps the network open: the author's code can reach the network. A SIGTERM or SIGHUP on the main thread unwinds the run, so
the private HOME is deleted; after a SIGKILL the next run sweeps it.

The login must not reach a file the host commits. ``author_argv`` denies the file tools (Read, Grep, Glob, Edit, Write) the private
HOME and the login file (``deny_rules``), and every snapshot is followed by a scan: a changed file that holds the login file or one of
its tokens fails the round with ``secret_in_diff`` (the detail names the file, never the secret).
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import author_isolation, evidence, input_ceiling, model_roles, plan_paths
from .watcher247 import host_mode, proc, sandbox

FAMILIES = ("claude",)
ROLE = "coordination"  # the role that edits code and fixes a failing check (squad coordinator)
# No `git add` / `git commit`: in the sandbox a commit never finishes (read-only .git), and the loop reads files, not git.
ALLOWED_TOOLS = (
    "Read", "Grep", "Glob", "Edit", "Write", "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)",
    "Bash(git status:*)", "Bash(git diff:*)",
)
DISALLOWED_TOOLS = "WebFetch,WebSearch"
DENIED_FILE_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write")  # every file tool the CLI has without Bash
AUTHOR_TIMEOUT_S = 900  # one CLI round (the default; see ``author_timeout``)
TIMEOUT_ENV = "SIMPLICIO_247_AUTHOR_TIMEOUT_S"
TIMEOUT_MIN_S, TIMEOUT_MAX_S = 60, 3600
VERIFY_TIMEOUT_S = 600
MAX_ROUNDS = 10
DETAIL_CAP = 1500  # the tail of a failure output kept in one failure
PROMPT_CAP = 6000  # a whole correction prompt
USAGE_KEYS = {"input_tokens": "input_tokens", "output_tokens": "output_tokens", "cache_read_tokens": "cache_read_input_tokens"}
NO_BYTECODE = {"PYTHONDONTWRITEBYTECODE": "1"}  # a .pyc beside a protected module would be code the loop never reads

Runner = Callable[..., Awaitable[proc.Result]]  # proc.run's shape: runner(argv, timeout=, cwd=, env=)

AUTHOR_PREAMBLE = (
    "You are the author. Edit the files in this worktree to do the task below. Never change these protected paths: {protected}. "
    "Do not push and do not open a pull request. The host runs {verify} after you finish and sends you any failure to correct.\n\n{no_run}Task:\n\n"
)
NO_RUN_NOTE = ("You cannot run tests or any command here: you can only read, search and edit files. "
               "The host runs the verify and sends you the failures; do not try to run them yourself.\n\n")
ADVICE = {
    "verify_failed": "The verify command failed. Fix the code. Output (tail):\n{detail}",
    "protected_path": ("You changed protected paths or Python bytecode. Undo every change to a protected path (restore its original content). "
                       "Delete every .pyc and .pyo you made. Do not make bytecode: PYTHONDONTWRITEBYTECODE=1 is set.\n{detail}"),
    "empty_diff": "You made no change to any file. Edit the files that the task needs.",
    "timeout": ("Your last round ended at the time limit. Continue from the current state of the worktree: first run what is left of the task, "
                "do not redo finished work, then stop."),
    "secret_in_diff": ("A file you changed holds a secret (a copy of the login of this session or one of its tokens). "
                       "Delete the secret from these files and never read or copy it:\n{detail}"),
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


def deny_rules(private_home: Path, real_home: Path) -> list[str]:
    """``--disallowedTools`` rules that keep the file tools off the login: the private HOME, and the ``.claude`` folder and the login
    file of both HOMEs. ``Tool(//abs/path/**)`` is Claude Code's permission rule for an absolute path (one leading ``/`` is relative to
    the settings file, ``//`` is the file system root); a deny rule wins over any allow rule. The login file has a rule of its own.
    """
    paths = []
    for home, whole in ((private_home, True), (real_home, False)):
        base = "/" + os.fspath(home)  # an absolute path starts with "/": the rule starts with "//"
        paths += ([f"{base}/**"] if whole else []) + [f"{base}/{author_isolation.LOGIN.parent}/**", f"{base}/{author_isolation.LOGIN}"]
    return [f"{tool}({path})" for tool in DENIED_FILE_TOOLS for path in paths]


def author_argv(family: str, prompt: str, *, session: str, resume: bool, model: str, effort: str, run_tests: bool = True,
                deny: Sequence[str] = ()) -> list[str]:
    """The claude argv for one round. ``allowedTools`` and ``disallowedTools`` take lists, so a flag follows each list.

    ``deny`` (see ``deny_rules``) goes after the web tools in ``disallowedTools``, one argument each.

    ``run_tests=False`` leaves the CLI only the file tools: no ``Bash(...)`` entry at all. pytest runs the author's conftest in the
    CLI's own sandbox, with the private HOME (the login) mounted and the network open, and ``git status`` / ``git diff`` run a program
    that the HOME's ``.gitconfig`` names. The host still runs ``verify`` (empty HOME, no login) and sends its failures back.
    """
    if family not in FAMILIES:
        raise AuthorUnsupported(family)
    tools = ALLOWED_TOOLS if run_tests else tuple(tool for tool in ALLOWED_TOOLS if not tool.startswith("Bash("))
    argv = ["claude", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    argv += ["--permission-mode", "acceptEdits", "--allowedTools", *tools, "--disallowedTools", DISALLOWED_TOOLS, *deny,
             "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "user", "--output-format", "json"]
    return argv + (["--resume", session] if resume else ["--session-id", session])


def timeout_in_range(value: object) -> bool:
    """True for an integer (not a bool) from ``TIMEOUT_MIN_S`` to ``TIMEOUT_MAX_S``."""
    return isinstance(value, int) and not isinstance(value, bool) and TIMEOUT_MIN_S <= value <= TIMEOUT_MAX_S


def author_timeout(environ: Mapping[str, str] | None = None) -> int:
    """The time limit of one CLI round, in seconds: ``SIMPLICIO_247_AUTHOR_TIMEOUT_S`` when it is a whole number from 60 to 3600.

    Any other value (empty, text, a float, a sign, a space inside, out of range) is ignored and ``AUTHOR_TIMEOUT_S`` is used.
    """
    raw = (os.environ if environ is None else environ).get(TIMEOUT_ENV, "").strip()
    if raw.isascii() and raw.isdigit() and timeout_in_range(value := int(raw)):
        return value
    return AUTHOR_TIMEOUT_S


def _tail(text: str, cap: int = DETAIL_CAP) -> str:
    """Redact first (a cut must not split a secret), then keep the last ``cap`` characters."""
    return evidence.redact_sensitive_text(text)[-cap:]


def correction_prompt(failures: list[dict[str, str]]) -> str:
    """The text of a correction round from the failures of the last one (kinds in ``ADVICE``), without secrets, capped.

    A round that only timed out is not a failure to correct: its text is the continuation alone.
    """
    if failures and all(f["kind"] == "timeout" for f in failures):
        return ADVICE["timeout"]
    parts = [ADVICE[f["kind"]].format(detail=_tail(f["detail"])) for f in failures]
    return ("Your last round did not pass.\n\n" + "\n\n".join(parts))[:PROMPT_CAP]


def _envelope(stdout: str) -> dict[str, Any] | None:
    """The CLI's JSON envelope, or None when its output is not a JSON object."""
    try:
        envelope = json.loads(stdout)
    except ValueError:
        return None
    return envelope if isinstance(envelope, dict) else None


def _usage(envelope: dict[str, Any]) -> dict[str, int]:
    """The integer counters of the envelope's ``usage``; a key the CLI left out (or filled with a non-integer) is absent."""
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {key: usage[source] for key, source in USAGE_KEYS.items()
            if isinstance(usage.get(source), int) and not isinstance(usage[source], bool)}


def _protected(changed: list[str], worktree: Path) -> list[str]:
    reasons = (plan_paths.refusal(path, worktree) or plan_paths.protected_refusal(path, worktree) or author_isolation.bytecode_refusal(path)
               for path in changed)
    return [reason for reason in reasons if reason]


class _Run:
    """One author run: the state a result reports, the sandboxed launches and the snapshots."""

    def __init__(self, worktree: Path, verify: str | None, rounds: int, runner: Runner, allow_unsandboxed: bool, run_tests: bool = True,
                 timeout_s: int = AUTHOR_TIMEOUT_S):
        self.timeout_s = timeout_s if timeout_in_range(timeout_s) else AUTHOR_TIMEOUT_S
        self.worktree, self.verify, self.rounds, self.runner, self.allow_unsandboxed = worktree, verify, rounds, runner, allow_unsandboxed
        self.run_tests = run_tests
        self.session = str(uuid.uuid4())
        self.n = 0  # the round in progress; 0 before the first
        self.changed: list[str] = []
        self.usage: dict[str, int] = {}
        self.measured = 0
        self.before: dict[str, str] = {}
        self.login_files: tuple[Path, ...] = ()
        self.secrets: set[bytes] = set()  # the bytes of the login and its tokens: in memory only, never in a log or a detail

    def result(self, status: str, reason: str, failures: list[dict[str, str]]) -> AuthorResult:
        usage = {**self.usage, "measured_rounds": self.measured} if self.measured else None
        return AuthorResult(status, self.n, "" if self.n == 0 else self.session, self.changed, failures, usage, reason)

    def fail(self, reason: str, detail: str) -> AuthorResult:
        return self.result("failed", reason, [{"kind": reason, "detail": detail}])

    def refusal(self, family: str) -> AuthorResult | None:
        """The result of a run that must not start (family, rounds, sandbox, binary), or None."""
        if family not in FAMILIES:
            return self.result("unsupported", "unsupported_family", [{"kind": "unsupported_family", "detail": str(AuthorUnsupported(family))}])
        if not 1 <= self.rounds <= MAX_ROUNDS:
            return self.fail("bad_rounds", f"rounds must be from 1 to {MAX_ROUNDS}; got {self.rounds}")
        if not self.allow_unsandboxed:
            if sandbox.engine() is None:
                return self.fail("sandbox_unavailable", "no bwrap on this host")
            if shutil.which(family, path=os.environ.get("PATH") or sandbox.DEFAULT_PATH) is None:  # inside bwrap a miss is an opaque exit 1
                return self.fail("cli_unavailable", f"{family} is not on PATH")
        return None

    def wrap(self, argv: list[str], view: sandbox.HomeView) -> list[str]:
        return argv if self.allow_unsandboxed else sandbox.wrap(argv, clone=self.worktree, state_dir=self.worktree, home=view)

    async def launch(self, argv: list[str], view: sandbox.HomeView, env: dict[str, str], timeout: int):
        """(run, None), or (None, (reason_code, detail)) when the process did not start or did not finish."""
        try:
            return await self.runner(self.wrap(argv, view), timeout=timeout, cwd=self.worktree, env=env), None
        except TimeoutError:  # before OSError: it is one
            return None, ("timeout", f"{argv[0]} did not finish in {timeout}s")
        except sandbox.SandboxUnavailable as exc:
            return None, ("sandbox_unavailable", str(exc))
        except OSError as exc:
            return None, ("argv_too_long" if exc.errno == errno.E2BIG else "cli_unavailable", str(exc))

    async def observe(self) -> list[str]:
        """Take a snapshot now; ``changed`` is the original one against it."""
        self.changed = author_isolation.diff(self.before, await asyncio.to_thread(author_isolation.snapshot, self.worktree))
        return self.changed

    async def findings(self, changed: list[str]) -> list[dict[str, str]]:
        """The failures in the changed files themselves: a protected path, then a copy of the login (``secret_in_diff``, last: it is the reason)."""
        failures = []
        if planted := _protected(changed, self.worktree):
            failures.append({"kind": "protected_path", "detail": "\n".join(planted)})
        # read again every time: the CLI may refresh the tokens in its home; the old values stay in the set
        self.secrets |= await asyncio.to_thread(author_isolation.login_secrets, *self.login_files)
        if held := await asyncio.to_thread(author_isolation.leaks, self.worktree, changed, self.secrets):
            failures.append({"kind": "secret_in_diff", "detail": "\n".join(f"{path}: holds the login or one of its tokens" for path in held)})
        return failures

    async def check(self, env: dict[str, str], view: sandbox.HomeView) -> list[dict[str, str]]:
        """Run verify and look at what it wrote; the failures, none when it is green and planted nothing protected or secret."""
        run, error = await self.launch(["sh", "-c", self.verify], view, env, VERIFY_TIMEOUT_S)
        failures = []
        if error:
            failures.append({"kind": "verify_failed", "detail": f"{error[0]}: {error[1]}"})
        elif run.returncode:
            failures.append({"kind": "verify_failed", "detail": f"exit {run.returncode}\n{run.stdout}\n{run.stderr}"})
        return failures + await self.findings(await self.observe())  # verify ran the author's code after the check that came before it

    async def go(self, family: str, task_text: str, home: Path, real_home: Path) -> AuthorResult:
        resolved = model_roles.resolve(family, ROLE)
        cli_env = {**sandbox.scrubbed_env(os.environ, home=home), **NO_BYTECODE}  # HOME is the private one; no API key, no GH_TOKEN
        cli_view = sandbox.HomeView(real_home, rw=(str(home.relative_to(real_home)),), ro=host_mode.FAMILY_HOME[family]["ro"])
        verify_env = {**sandbox.scrubbed_env(os.environ, home=real_home), **NO_BYTECODE}  # the sandbox shows an empty HOME
        verify_view = sandbox.HomeView(real_home)
        prompt = (AUTHOR_PREAMBLE.format(protected=", ".join(plan_paths.PROTECTED_PATHS), verify=f"`{self.verify}`" if self.verify else "no command",
                                                  no_run="" if self.run_tests else NO_RUN_NOTE) + task_text)
        try:
            ceiling = input_ceiling.resolve_ceiling(self.worktree)
            projection = input_ceiling.Projection.estimated(prompt)
            input_ceiling.enforce_budget(projection, ceiling)
        except input_ceiling.CeilingConfigError as e:
            return self.fail("ceiling_invalid", str(e))
        except input_ceiling.InputCeilingExceeded:
            return self.fail("input_ceiling_exceeded", "prompt exceeds ceiling")
        self.login_files = (home / author_isolation.LOGIN, real_home / author_isolation.LOGIN)
        self.secrets = await asyncio.to_thread(author_isolation.login_secrets, *self.login_files)
        deny = deny_rules(home, real_home)
        self.before = await asyncio.to_thread(author_isolation.snapshot, self.worktree)
        failures: list[dict[str, str]] = []
        for self.n in range(1, self.rounds + 1):
            author_isolation.reset_config(home)
            argv = author_argv(family, prompt, session=self.session, resume=self.n > 1, model=resolved["model"], effort=resolved["effort"],
                               run_tests=self.run_tests, deny=deny)
            run, error = await self.launch(argv, cli_view, cli_env, self.timeout_s)
            if error:
                await self.observe()
                if error[0] != "timeout":
                    return self.fail(*error)
                # the work stays: the next round resumes the session; a timeout in the last round is the result
                failures = [{"kind": "timeout", "detail": error[1]}]
                prompt = correction_prompt(failures)
                continue
            envelope = _envelope(run.stdout)
            counters = _usage(envelope or {})
            for key, value in counters.items():
                self.usage[key] = self.usage.get(key, 0) + value
            self.measured += bool(counters)
            if run.returncode or (envelope or {}).get("is_error") is True:
                await self.observe()
                return self.fail("cli_error", _tail(f"{run.stdout}\n{run.stderr}"))
            if envelope is None:
                await self.observe()
                return self.fail("bad_envelope", _tail(f"the CLI exited 0 without a JSON object:\n{run.stdout}"))

            changed = await self.observe()
            failures = await self.findings(changed) if changed else [{"kind": "empty_diff", "detail": ""}]
            if changed and not failures and self.verify:
                failures = await self.check(verify_env, verify_view)
            if not failures:
                return self.result("ok", "ok" if self.verify else "ok_unverified", [])
            prompt = correction_prompt(failures)
        return self.result("failed", failures[-1]["kind"], [{**f, "detail": _tail(f["detail"])} for f in failures])


async def run_author(task_text: str, worktree: str | os.PathLike[str], *, family: str = "claude", verify: str | None = None,
                     rounds: int = 3, runner: Runner = proc.run, allow_unsandboxed: bool = False, run_tests: bool = True,
                     timeout_s: int = AUTHOR_TIMEOUT_S) -> AuthorResult:
    """Author, verify and correct in ``worktree`` for at most ``rounds`` rounds. A failed round is a result, not an exception.

    ``timeout_s``: the time limit of one CLI round (60 to 3600; another value means ``AUTHOR_TIMEOUT_S``). A round that hits it is not
    fatal while rounds remain: the next one resumes the session. The last round that hits it ends the run as ``failed`` / ``timeout``.

    ``run_tests=False``: the CLI gets only the file tools (see ``author_argv``); the verify command still runs on the host side.
    """
    run = _Run(Path(worktree), verify, rounds, runner, allow_unsandboxed, run_tests, timeout_s)
    if refused := run.refusal(family):
        return refused
    real_home = Path.home()
    with author_isolation.terminating():  # a SIGTERM raises SystemExit here, and the finally below runs
        try:
            home = author_isolation.make_home(real_home, run.session)
        except author_isolation.LoginMissing as exc:
            return run.fail("claude_login_missing", str(exc))
        except OSError as exc:
            return run.fail("home_unavailable", f"cannot make the private HOME: {exc} (set {author_isolation.HOME_BASE_ENV} to a writable folder inside the HOME)")
        try:
            return await run.go(family, task_text, home, real_home)
        except author_isolation.SnapshotTimeout as exc:
            return run.fail("snapshot_timeout", str(exc))
        finally:
            author_isolation.drop_home(home)
