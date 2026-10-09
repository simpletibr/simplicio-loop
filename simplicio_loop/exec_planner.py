"""CLI exec planners for claude, codex, grok, gemini, agy and opencode, run as plan-only planners (issues 1431, 1432).

The planner never mutates the repo. It returns a plan JSON (``{"operations": [...]}``) that the dev-cli applies
(``simplicio-loop turbo --apply -``). Every argv therefore uses the CLI's most restrictive non-interactive mode.
Flags marked VERIFIED were checked against ``<cli> --help`` on the host. gemini, agy and opencode are not installed
here, so their flags are DOC-BASED (vendor docs) and unverified.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import time

from . import model_roles

DEFAULT_FAMILIES = ["claude", "codex", "grok", "gemini"]
KILL_GRACE_SEC = 3.0

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
    # VERIFIED on the review host with `agy --help` (version not recorded in the PR): -p/--print, --mode plan,
    # --sandbox, --output-format json, --model, --effort (low|medium|high|xhigh|max). agy is not installed in the
    # container that wrote this, so these were not reproduced here.
    argv = ["agy", "-p", prompt, "--mode", "plan", "--sandbox", "--output-format", "json"]
    if _real_model(model):
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    return argv


def _build_argv_opencode(prompt, role, model, effort, cwd):
    # VERIFIED on the review host with `opencode run --help`: the message argument, --format json, -m provider/model,
    # --variant (effort, provider-specific), --agent. `opencode agent list` confirms the `plan` agent exists.
    # PARTIAL: the `plan` agent denies edits (except plan .md files) but allows bash, so the read-only limit is
    # by instruction, not by permission. The preamble tells the planner not to run commands.
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


async def _run_subprocess(argv, stdin_text=None, timeout_sec=60.0, cwd=None, grace_sec=KILL_GRACE_SEC):
    """Run a subprocess in its own session and return (stdout, stderr, returncode); kill the tree on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin_text else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
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
        if "operations" in obj:
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


async def run_planner(family, role, prompt, cwd=None, timeout_sec=60.0, grace_sec=KILL_GRACE_SEC):
    """Run the planner CLI for a specific family and role."""
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

    stdin_text = full_prompt if family == "codex" else None
    try:
        stdout, stderr, returncode = await _run_subprocess(
            argv, stdin_text=stdin_text, timeout_sec=timeout_sec, cwd=cwd, grace_sec=grace_sec
        )
    except asyncio.TimeoutError:
        return _result("timeout", family, role, model, effort, started, error="timeout")

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


async def run_planner_with_fallback(role, prompt, cwd=None, timeout_sec=60.0, families=None, grace_sec=KILL_GRACE_SEC):
    """Try to run planner with each family in order, falling back on non-fatal errors."""
    last_result = None
    for family in families or _get_families():
        result = await run_planner(family, role, prompt, cwd, timeout_sec, grace_sec)
        if result.reason_code in ("bad_role", "bad_argv") or result.is_ok():
            return result
        last_result = result
    return last_result or PlannerResult("no_families", "", role, "", "", error="no families")
