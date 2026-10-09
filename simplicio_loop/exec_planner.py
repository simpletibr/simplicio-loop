"""CLI exec planners for claude, codex, grok, gemini, agy and opencode, run as plan-only planners (issues 1431, 1432).

The planner never mutates the repo. It returns a plan JSON (``{"operations": [...]}``) that the dev-cli applies
(``simplicio-loop turbo --apply -``). Every argv therefore uses the CLI's most restrictive non-interactive mode.
Flags marked VERIFIED were checked against ``<cli> --help`` on the host (agy 1.3.2, opencode 1.18.30). gemini is not
installed here, so its flags are DOC-BASED (vendor docs) and unverified.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import time

from . import model_roles

DEFAULT_FAMILIES = ["claude", "codex", "grok", "gemini"]
KILL_GRACE_SEC = 3.0

# opencode's built-in `plan` agent denies edits but allows bash and webfetch. This config is written to a temp file and
# passed through OPENCODE_CONFIG so the planner cannot run commands or fetch URLs.
OPENCODE_DENY_CONFIG = {"permission": {"bash": "deny", "webfetch": "deny", "edit": "deny"}}

PLAN_ONLY_PREAMBLE = (
    "You are a planner only. Do NOT edit files and do NOT run commands. Reply with exactly one JSON object "
    '{"operations": [...]} describing the edits. The dev-cli applies it afterwards '
    "(`simplicio-loop turbo --apply -`). Task:\n\n"
)


class ExecPlannerError(Exception):
    """Base error for exec planner failures."""


class PlannerResult:
    """Result of running a planner via CLI exec."""

    def __init__(self, reason_code, family, role, model, effort, plan=None, error=None, execution_ms=0.0):
        self.reason_code = reason_code
        self.family = family
        self.role = role
        self.model = model
        self.effort = effort
        self.plan = plan
        self.error = error
        self.execution_ms = execution_ms

    def is_ok(self):
        return self.reason_code == "ok"

    def to_dict(self):
        return {
            "reason_code": self.reason_code,
            "family": self.family,
            "role": self.role,
            "model": self.model,
            "effort": self.effort,
            "plan": self.plan,
            "error": self.error,
            "execution_ms": self.execution_ms,
        }


def _find_cli(name):
    return shutil.which(name)


def _get_families():
    env = os.environ.get("SIMPLICIO_EXEC_FAMILIES", "").strip()
    if env:
        return [f.strip() for f in env.split(",") if f.strip()]
    return DEFAULT_FAMILIES


def _real_model(model):
    return bool(model) and model not in ("default", "auto")


def _build_argv_claude(prompt, role, model, effort, cwd):
    # VERIFIED via `claude --help`: -p, --model, --effort, --permission-mode plan, --tools, --output-format.
    argv = ["claude", "-p", prompt]
    if _real_model(model):
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    argv.extend(["--permission-mode", "plan", "--tools", "Read", "--output-format", "json"])
    return argv


def _build_argv_codex(prompt, role, model, effort, cwd):
    # VERIFIED via `codex exec --help`: -s read-only, --ephemeral, -C/--cd, -m, -c key=value.
    # DOC-BASED: the config key `model_reasoning_effort` (--help only says -c takes key=value).
    argv = ["codex", "exec", "-s", "read-only", "--ephemeral", "--cd", cwd]
    if _real_model(model):
        argv.extend(["-m", model])
    if effort:
        argv.extend(["-c", 'model_reasoning_effort="%s"' % effort])
    argv.append("-")
    return argv


def _build_argv_grok(prompt, role, model, effort, cwd):
    # VERIFIED via `grok --help`: -p, -m, --reasoning-effort, --permission-mode plan, --cwd, --output-format json.
    argv = ["grok", "-p", prompt]
    if _real_model(model):
        argv.extend(["-m", model])
    if effort:
        argv.extend(["--reasoning-effort", effort])
    argv.extend(["--permission-mode", "plan", "--cwd", cwd, "--output-format", "json"])
    return argv


def _build_argv_gemini(prompt, role, model, effort, cwd):
    # DOC-BASED (gemini not installed on this host): -p, -m, --approval-mode plan, --output-format json.
    # Gemini CLI has no effort flag, so effort is only recorded in the result.
    argv = ["gemini", "-p", prompt]
    if _real_model(model):
        argv.extend(["-m", model])
    argv.extend(["--approval-mode", "plan", "--output-format", "json"])
    return argv


def _build_argv_agy(prompt, role, model, effort, cwd):
    # VERIFIED with `agy --help` (agy 1.3.2): -p/--print, --mode (accept-edits, plan), --sandbox,
    # --output-format (text, json, stream-json), --model, --effort (low|medium|high|xhigh|max).
    argv = ["agy", "-p", prompt, "--mode", "plan", "--sandbox", "--output-format", "json"]
    if _real_model(model):
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    return argv


def _build_argv_opencode(prompt, role, model, effort, cwd):
    # VERIFIED with `opencode run --help` (opencode 1.18.30): the message argument, --format json,
    # -m provider/model, --variant (provider-specific reasoning effort), --agent. `opencode agent list` shows `plan`.
    # VERIFIED with `opencode debug agent plan`: the built-in `plan` agent allows bash and webfetch, so run_planner
    # also sets OPENCODE_CONFIG to OPENCODE_DENY_CONFIG (bash, webfetch and edit deny); the resolved plan agent then
    # lists those denies. DOC-BASED: OPENCODE_CONFIG as an env var is not listed by --help; it comes from the opencode
    # config docs, and the debug output above is what confirms it takes effect.
    argv = ["opencode", "run", prompt, "--format", "json", "--agent", "plan"]
    if _real_model(model):
        argv.extend(["-m", model])
    if effort:
        argv.extend(["--variant", effort])
    return argv


_ARGV_BUILDERS = {
    "claude": _build_argv_claude,
    "codex": _build_argv_codex,
    "grok": _build_argv_grok,
    "gemini": _build_argv_gemini,
    "agy": _build_argv_agy,
    "opencode": _build_argv_opencode,
}
SUPPORTED_FAMILIES = tuple(_ARGV_BUILDERS)

# Quota, rate-limit and auth terms, matched case-insensitively in stderr and stdout. The quota list follows the
# capacity terms in packages/dev-cli/simplicio/providers.py. None of these strings is verified against CLI output.
_QUOTA_TERMS = ("quota", "insufficient_quota", "credit balance", "billing", "usage limit")
_RATE_TERMS = ("rate limit", "rate_limit", "too many requests")
_AUTH_TERMS = ("auth", "unauthorized", "not logged in", "log in", "login", "api key")


def classify_failure(returncode, stderr, stdout):
    """Map a failed CLI run to quota_exhausted, rate_limited or auth_error; None when it is a generic failure."""
    if returncode == 0:
        return None
    text = f"{stderr}\n{stdout}".lower()
    for code, terms in (("quota_exhausted", _QUOTA_TERMS), ("rate_limited", _RATE_TERMS), ("auth_error", _AUTH_TERMS)):
        if any(term in text for term in terms):
            return code
    return None


def build_argv(family, role, prompt, model, cwd, effort=""):
    """Build the plan-only command-line argv for a specific family's CLI exec."""
    builder = _ARGV_BUILDERS.get(family)
    if not builder:
        raise ExecPlannerError(f"unsupported family: {family}")
    return builder(prompt, role, model, effort, cwd)


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


async def _kill_process_tree(proc, grace_sec=KILL_GRACE_SEC):
    """SIGTERM the whole process group, then SIGKILL whatever survives the grace period."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + grace_sec
    while time.monotonic() < deadline:
        try:
            await asyncio.wait_for(proc.wait(), timeout=0.05)
        except asyncio.TimeoutError:
            pass
        if proc.returncode is not None and not _group_alive(pgid):
            return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    await proc.wait()


async def _run_subprocess(argv, stdin_text=None, timeout_sec=60.0, cwd=None, grace_sec=KILL_GRACE_SEC, env=None):
    """Run a subprocess in its own session and return (stdout, stderr, returncode); kill the tree on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin_text else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_text.encode("utf-8") if stdin_text else None),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        await _kill_process_tree(proc, grace_sec)
        raise
    return stdout_bytes.decode("utf-8", errors="replace"), stderr_bytes.decode("utf-8", errors="replace"), proc.returncode


def _plan_from(obj):
    if isinstance(obj, dict):
        if "operations" in obj or "need" in obj:  # `need`: lines the planner could not see (turbo_window)
            return obj
        # claude/grok `--output-format json` wrap the model text in an envelope: {"result": "<text>"}
        inner = obj.get("result")
        if isinstance(inner, str):
            return _find_plan(inner)
    return None


def _find_plan(text):
    try:
        plan = _plan_from(json.loads(text))
        if plan:
            return plan
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return _plan_from(json.loads(text[start : end + 1]))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _extract_plan_json(output):
    """Extract and validate plan JSON from CLI output."""
    plan = _find_plan(output)
    if plan is None:
        raise ValueError("plan JSON not found or invalid")
    return plan


def _result(code, family, role, model, effort, started, plan=None, error=None):
    return PlannerResult(code, family, role, model, effort, plan=plan, error=error, execution_ms=(time.monotonic() - started) * 1000)


async def run_planner(family, role, prompt, cwd=None, timeout_sec=60.0, grace_sec=KILL_GRACE_SEC, wrap=None, env=None,
                      config_dir=None):
    """Run the planner CLI for a specific family and role.

    ``wrap`` maps the argv to the argv actually spawned (the watcher passes its sandbox); the default is the identity.
    ``env`` is the whole environment of the subprocess; the default inherits the caller's.
    ``config_dir`` is where the opencode deny config is written (default: the system temp dir). A sandbox that mounts a
    tmpfs on /tmp hides that file, so opencode would then run WITHOUT the deny rules: pass a directory the sandbox binds.
    """
    started = time.monotonic()
    try:
        resolved = model_roles.resolve(family, role)
    except model_roles.ModelRoleError as e:
        return _result("bad_role", family, role, "", "", started, error=str(e))
    model, effort = resolved["model"], resolved["effort"]

    if not _find_cli(family):
        return _result("cli_missing", family, role, model, effort, started, error=f"CLI '{family}' not found")

    full_prompt = PLAN_ONLY_PREAMBLE + prompt
    try:
        argv = build_argv(family, role, full_prompt, model, cwd or ".", effort)
    except ExecPlannerError as e:
        return _result("bad_argv", family, role, model, effort, started, error=str(e))

    if wrap is not None:
        argv = wrap(argv)  # before any temp file exists: a refusing wrapper must not leave one behind
    stdin_text = full_prompt if family == "codex" else None
    config_path = None
    if family == "opencode":
        if config_dir is not None:
            os.makedirs(config_dir, exist_ok=True)
        fd, config_path = tempfile.mkstemp(prefix="simplicio-opencode-", suffix=".json", dir=config_dir)
        with os.fdopen(fd, "w") as handle:
            json.dump(OPENCODE_DENY_CONFIG, handle)
        env = {**(os.environ if env is None else env), "OPENCODE_CONFIG": config_path}
    try:
        stdout, stderr, returncode = await _run_subprocess(
            argv, stdin_text=stdin_text, timeout_sec=timeout_sec, cwd=cwd, grace_sec=grace_sec, env=env
        )
    except asyncio.TimeoutError:
        return _result("timeout", family, role, model, effort, started, error="timeout")
    finally:
        if config_path:
            try:
                os.unlink(config_path)
            except OSError:
                pass

    failure = classify_failure(returncode, stderr, stdout)
    if failure:
        return _result(failure, family, role, model, effort, started, error=f"exit {returncode}: {failure}")
    if returncode != 0:
        return _result("process_error", family, role, model, effort, started, error=f"exit {returncode}")
    try:
        plan = _extract_plan_json(stdout)
    except ValueError as e:
        return _result("bad_plan", family, role, model, effort, started, error=str(e))
    return _result("ok", family, role, model, effort, started, plan=plan)


async def run_planner_with_fallback(role, prompt, cwd=None, timeout_sec=60.0, families=None, grace_sec=KILL_GRACE_SEC,
                                    wrap=None, env_for=None, config_dir=None):
    """Try to run planner with each family in order, falling back on non-fatal errors.

    ``wrap`` and ``env_for(family)`` are passed to run_planner (the argv wrapper and the per-family environment).
    """
    last_result = None
    for family in families or _get_families():
        result = await run_planner(family, role, prompt, cwd, timeout_sec, grace_sec, wrap=wrap,
                                   env=env_for(family) if env_for else None, config_dir=config_dir)
        if result.reason_code in ("bad_role", "bad_argv") or result.is_ok():
            return result
        last_result = result
    return last_result or PlannerResult("no_families", "", role, "", "", error="no families")
