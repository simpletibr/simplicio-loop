"""CLI exec planner launcher: invokes claude, codex, grok, gemini CLIs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from . import model_roles

DEFAULT_FAMILIES = ["claude", "codex", "grok", "gemini"]


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


def _build_argv_claude(prompt, role, model, cwd):
    argv = ["claude", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    argv.extend(["--output-format", "json"])
    return argv


def _build_argv_codex(prompt, role, model, cwd):
    argv = ["codex", "exec", "--cd", cwd]
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    argv.append("-")
    return argv


def _build_argv_grok(prompt, role, model, cwd):
    argv = ["grok", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    argv.extend(["--output-format", "json"])
    return argv


def _build_argv_gemini(prompt, role, model, cwd):
    argv = ["gemini", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    argv.extend(["--output-format", "json"])
    return argv


_ARGV_BUILDERS = {
    "claude": _build_argv_claude,
    "codex": _build_argv_codex,
    "grok": _build_argv_grok,
    "gemini": _build_argv_gemini,
}


def build_argv(family, role, prompt, model, cwd):
    """Build the command-line argv for a specific family's CLI exec."""
    builder = _ARGV_BUILDERS.get(family)
    if not builder:
        raise ExecPlannerError(f"unsupported family: {family}")
    return builder(prompt, role, model, cwd)


async def _run_subprocess(argv, stdin_text=None, timeout_sec=60.0, cwd=None):
    """Run a subprocess and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin_text else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_text.encode("utf-8") if stdin_text else None),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        raise

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return stdout, stderr, proc.returncode


def _extract_plan_json(output):
    """Extract and validate plan JSON from CLI output."""
    import re

    try:
        obj = json.loads(output)
        if isinstance(obj, dict) and "operations" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    start = output.find("{")
    end = output.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(output[start : end + 1])
            if isinstance(obj, dict) and "operations" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError("plan JSON not found or invalid")


async def run_planner(family, role, prompt, cwd=None, timeout_sec=60.0):
    """Run the planner CLI for a specific family and role."""
    import time

    start_ms = time.monotonic()

    try:
        resolved = model_roles.resolve(family, role)
        model = resolved["model"]
        effort = resolved["effort"]
    except model_roles.ModelRoleError as e:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("bad_role", family, role, "", "", error=str(e), execution_ms=elapsed_ms)

    cli_bin = _find_cli(family)
    if not cli_bin:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("cli_missing", family, role, model, effort, error=f"CLI '{family}' not found", execution_ms=elapsed_ms)

    try:
        argv = build_argv(family, role, prompt, model, cwd or ".")
    except ExecPlannerError as e:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("bad_argv", family, role, model, effort, error=str(e), execution_ms=elapsed_ms)

    stdin_text = prompt if family == "codex" else None
    try:
        stdout, stderr, returncode = await _run_subprocess(argv, stdin_text=stdin_text, timeout_sec=timeout_sec, cwd=cwd)
    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("timeout", family, role, model, effort, error=f"timeout", execution_ms=elapsed_ms)

    if "auth" in stderr.lower():
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("auth_error", family, role, model, effort, error=f"auth error", execution_ms=elapsed_ms)

    if returncode != 0:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("process_error", family, role, model, effort, error=f"exit {returncode}", execution_ms=elapsed_ms)

    try:
        plan = _extract_plan_json(stdout)
    except ValueError as e:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult("bad_plan", family, role, model, effort, error=str(e), execution_ms=elapsed_ms)

    elapsed_ms = (time.monotonic() - start_ms) * 1000
    return PlannerResult("ok", family, role, model, effort, plan=plan, execution_ms=elapsed_ms)


async def run_planner_with_fallback(role, prompt, cwd=None, timeout_sec=60.0, families=None):
    """Try to run planner with each family in order, falling back on non-fatal errors."""
    try_families = families or _get_families()
    last_result = None

    for family in try_families:
        result = await run_planner(family, role, prompt, cwd, timeout_sec)

        if result.reason_code in ("bad_role", "bad_argv"):
            return result

        if result.is_ok():
            return result

        last_result = result

    return last_result or PlannerResult("no_families", "", role, "", "", error="no families")
