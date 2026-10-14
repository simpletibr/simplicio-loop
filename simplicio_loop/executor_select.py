"""Executor selection for the 24/7 watcher (issue 1432).

``SIMPLICIO_EXECUTOR`` picks the path: ``exec`` (the default; headless CLI exec planners), ``host`` (the invoking
model runs turbo itself, nothing is spawned here) or ``openrouter`` (explicit opt-in; needs ``OPENROUTER_API_KEY``).
``SIMPLICIO_EXEC_FAMILIES`` orders the exec families. ``openrouter`` is a mode, never an exec family, so it is never
a silent fallback.

Exec runs try each family in order. A quota, rate-limit, auth or missing-CLI failure falls through to the next one,
and every failed attempt is kept in ``attempts``. When none succeeds the result is ``blocked`` with
``reason_code=all_executors_exhausted``.
"""

from __future__ import annotations

import os

from . import exec_planner, setup_cli

MODES = ("host", "exec", "openrouter")
DEFAULT_MODE = "exec"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
# Failures that mean "this family cannot take the work now": the next family is tried.
# bad_role and bad_argv are configuration errors and stop the walk, as in exec_planner.run_planner_with_fallback.
_STOP_CODES = ("bad_role", "bad_argv")


class ExecutorSelectError(ValueError):
    """The environment asks for an executor that cannot run."""


def _env(env):
    return os.environ if env is None else env


def select_mode(env=None):
    """The executor mode from SIMPLICIO_EXECUTOR. Unknown values and openrouter without a key fail closed."""
    values = _env(env)
    raw = values.get("SIMPLICIO_EXECUTOR", "").strip().lower()
    if not raw:
        mode = DEFAULT_MODE
    elif raw in MODES:
        mode = raw
    else:
        raise ExecutorSelectError(f"unknown executor '{raw}' (SIMPLICIO_EXECUTOR must be one of: {', '.join(MODES)})")
    if mode == "openrouter" and not values.get(OPENROUTER_KEY_ENV, "").strip():
        raise ExecutorSelectError("openrouter selected but OPENROUTER_API_KEY is not set")
    return mode


def exec_families(env=None):
    """The exec family order from SIMPLICIO_EXEC_FAMILIES, or the planner defaults when it is unset.

    The defaults put first the family of the default host that `simplicio-loop setup` chose, when it has one."""
    raw = _env(env).get("SIMPLICIO_EXEC_FAMILIES", "")
    families = [f.strip() for f in raw.split(",") if f.strip()]
    if not families:
        first = setup_cli.default_family(_env(env))
        families = list(exec_planner.DEFAULT_FAMILIES)
        if first in exec_planner.SUPPORTED_FAMILIES:
            families = [first, *(f for f in families if f != first)]
    for family in families:
        if family == "openrouter":
            raise ExecutorSelectError("openrouter is an executor mode (SIMPLICIO_EXECUTOR), not an exec family")
        if family not in exec_planner.SUPPORTED_FAMILIES:
            raise ExecutorSelectError(f"unknown family '{family}'")
    return families


def resolve(env=None):
    """{"mode", "families"}: the exec family order in exec mode, no families in host or openrouter mode."""
    mode = select_mode(env)
    return {"mode": mode, "families": exec_families(env) if mode == "exec" else []}


def _outcome(status, reason_code, family, plan, attempts):
    return {"status": status, "reason_code": reason_code, "family": family, "plan": plan, "attempts": attempts}


async def run_with_fallback(role, prompt, cwd=None, timeout_sec=60.0, grace_sec=exec_planner.KILL_GRACE_SEC, env=None, *, repo_root):
    """Run the exec families in env order and return the first plan, or a blocked outcome with every attempt."""
    resolved = resolve(env)
    if resolved["mode"] != "exec":
        raise ExecutorSelectError(f"run_with_fallback runs exec families only; SIMPLICIO_EXECUTOR is {resolved['mode']}")
    attempts = []
    for family in resolved["families"]:
        result = await exec_planner.run_planner(family, role, prompt, cwd, timeout_sec, grace_sec, repo_root=repo_root)
        if result.is_ok():
            return _outcome("ok", "ok", family, result.plan, attempts)
        attempts.append({"family": family, "reason_code": result.reason_code, "error": result.error})
        if result.reason_code in _STOP_CODES:
            return _outcome("blocked", result.reason_code, None, None, attempts)
    return _outcome("blocked", "all_executors_exhausted", None, None, attempts)
