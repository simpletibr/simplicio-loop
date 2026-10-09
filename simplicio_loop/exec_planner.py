"""CLI exec planner launcher: invokes claude, codex, grok, gemini CLIs in headless mode.

Each CLI is used as the invoking model in host mode: it reads a prompt via stdin,
runs 'simplicio-loop turbo --task ...', writes the plan, and runs 'turbo --apply -'.
Mutation is always done by dev-cli, never by the invoked agent.

The planner resolves model and effort from model_roles per family and role.
Selection order comes from env SIMPLICIO_EXEC_FAMILIES (default: claude,codex,grok,gemini).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Optional

from . import model_roles

# Families supported by exec planners, in preference order
DEFAULT_FAMILIES = ["claude", "codex", "grok", "gemini"]


class ExecPlannerError(Exception):
    """Base error for exec planner failures."""


class PlannerResult:
    """Result of running a planner via CLI exec."""

    def __init__(
        self,
        reason_code: str,
        family: str,
        role: str,
        model: str,
        effort: str,
        plan: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        execution_ms: float = 0.0,
    ):
        self.reason_code = reason_code  # ok, cli_missing, timeout, bad_plan, auth_error
        self.family = family
        self.role = role
        self.model = model
        self.effort = effort
        self.plan = plan
        self.error = error
        self.execution_ms = execution_ms

    def is_ok(self) -> bool:
        return self.reason_code == "ok"

    def to_dict(self) -> dict[str, Any]:
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


def _find_cli(name: str) -> Optional[str]:
    """Find a CLI binary on PATH. Return its absolute path or None."""
    return shutil.which(name)


def _get_families() -> list[str]:
    """Get the list of families to try, in order."""
    env = os.environ.get("SIMPLICIO_EXEC_FAMILIES", "").strip()
    if env:
        return [f.strip() for f in env.split(",") if f.strip()]
    return DEFAULT_FAMILIES


def _build_argv_claude(prompt: str, role: str, model: str, cwd: str) -> list[str]:
    """Build argv for 'claude -p PROMPT --model M --output-format json'."""
    argv = ["claude", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    argv.extend(["--output-format", "json"])
    return argv


def _build_argv_codex(prompt: str, role: str, model: str, cwd: str) -> list[str]:
    """Build argv for 'codex exec --cd DIR --model M -'."""
    argv = ["codex", "exec"]
    argv.extend(["--cd", cwd])
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    # Codex accepts prompt via stdin when no prompt arg is given (- means stdin)
    argv.append("-")
    return argv


def _build_argv_grok(prompt: str, role: str, model: str, cwd: str) -> list[str]:
    """Build argv for 'grok -p PROMPT --model M --output-format json'."""
    argv = ["grok", "-p", prompt]
    if model and model not in ("default", "auto"):
        argv.extend(["--model", model])
    argv.extend(["--output-format", "json"])
    return argv


def _build_argv_gemini(prompt: str, role: str, model: str, cwd: str) -> list[str]:
    """Build argv for 'gemini -p PROMPT --model M --output-format json'."""
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


def build_argv(family: str, role: str, prompt: str, model: str, cwd: str) -> list[str]:
    """Build the command-line argv for a specific family's CLI exec.

    Args:
        family: One of claude, codex, grok, gemini
        role: One of planning, coordination, execution
        prompt: The full prompt text
        model: Model ID from model_roles.resolve() or None
        cwd: Working directory

    Returns:
        The argv list (command + args, no shell)

    Raises:
        ExecPlannerError: if family is not supported
    """
    builder = _ARGV_BUILDERS.get(family)
    if not builder:
        raise ExecPlannerError(f"unsupported family: {family}")
    return builder(prompt, role, model, cwd)


async def _run_subprocess(
    argv: list[str],
    stdin_text: Optional[str] = None,
    timeout_sec: float = 60.0,
    cwd: Optional[str] = None,
) -> tuple[str, str, int]:
    """Run a subprocess and return (stdout, stderr, returncode).

    Raises:
        asyncio.TimeoutError: if the command times out
    """
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


def _extract_plan_json(output: str) -> dict[str, Any]:
    """Extract and validate plan JSON from CLI output.

    The plan format is: {"operations": [{"path": "...", "find": "...", "replace": "..."}]}

    Raises:
        ValueError: if the JSON is invalid or missing operations
    """
    # Try to parse as raw JSON first
    try:
        obj = json.loads(output)
        if isinstance(obj, dict) and "operations" in obj and isinstance(obj["operations"], list):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON in fenced code blocks
    import re

    fenced = re.search(r"```(?:json)?\\s*(\\{.*\\})\\s*```", output, re.S)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            if isinstance(obj, dict) and "operations" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

    # Last attempt: find any JSON object
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


async def run_planner(
    family: str,
    role: str,
    prompt: str,
    cwd: Optional[str] = None,
    timeout_sec: float = 60.0,
) -> PlannerResult:
    """Run the planner CLI for a specific family and role.

    Args:
        family: One of claude, codex, grok, gemini
        role: One of planning, coordination, execution
        prompt: The full prompt text
        cwd: Working directory (defaults to current dir)
        timeout_sec: Timeout in seconds for the subprocess

    Returns:
        PlannerResult with reason_code and details
    """
    import time

    start_ms = time.monotonic()

    # Resolve model and effort from model_roles
    try:
        resolved = model_roles.resolve(family, role)
        model = resolved["model"]
        effort = resolved["effort"]
    except model_roles.ModelRoleError as e:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="bad_role",
            family=family,
            role=role,
            model="",
            effort="",
            error=str(e),
            execution_ms=elapsed_ms,
        )

    # Check if the CLI is available
    cli_bin = _find_cli(family)
    if not cli_bin:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="cli_missing",
            family=family,
            role=role,
            model=model,
            effort=effort,
            error=f"CLI '{family}' not found on PATH",
            execution_ms=elapsed_ms,
        )

    # Build argv
    try:
        argv = build_argv(family, role, prompt, model, cwd or ".")
    except ExecPlannerError as e:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="bad_argv",
            family=family,
            role=role,
            model=model,
            effort=effort,
            error=str(e),
            execution_ms=elapsed_ms,
        )

    # Run the subprocess
    stdin_text = prompt if family == "codex" else None
    try:
        stdout, stderr, returncode = await _run_subprocess(
            argv, stdin_text=stdin_text, timeout_sec=timeout_sec, cwd=cwd
        )
    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="timeout",
            family=family,
            role=role,
            model=model,
            effort=effort,
            error=f"subprocess timed out after {timeout_sec}s",
            execution_ms=elapsed_ms,
        )

    # Check for auth/quota errors in stderr
    if "auth" in stderr.lower() or "unauthorized" in stderr.lower():
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="auth_error",
            family=family,
            role=role,
            model=model,
            effort=effort,
            error=f"authentication error: {stderr[:200]}",
            execution_ms=elapsed_ms,
        )

    if returncode != 0:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="process_error",
            family=family,
            role=role,
            model=model,
            effort=effort,
            error=f"process exited with code {returncode}: {stderr[:200]}",
            execution_ms=elapsed_ms,
        )

    # Extract and validate plan JSON
    try:
        plan = _extract_plan_json(stdout)
    except ValueError as e:
        elapsed_ms = (time.monotonic() - start_ms) * 1000
        return PlannerResult(
            reason_code="bad_plan",
            family=family,
            role=role,
            model=model,
            effort=effort,
            error=f"plan JSON invalid: {str(e)}",
            execution_ms=elapsed_ms,
        )

    elapsed_ms = (time.monotonic() - start_ms) * 1000
    return PlannerResult(
        reason_code="ok",
        family=family,
        role=role,
        model=model,
        effort=effort,
        plan=plan,
        execution_ms=elapsed_ms,
    )


async def run_planner_with_fallback(
    role: str,
    prompt: str,
    cwd: Optional[str] = None,
    timeout_sec: float = 60.0,
    families: Optional[list[str]] = None,
) -> PlannerResult:
    """Try to run planner with each family in order, falling back on non-fatal errors.

    Falls back on: cli_missing, auth_error, timeout, bad_plan.
    Stops on: bad_role, bad_argv (programming errors).

    Args:
        role: One of planning, coordination, execution
        prompt: The full prompt text
        cwd: Working directory
        timeout_sec: Timeout per family
        families: List of families to try (default: SIMPLICIO_EXEC_FAMILIES)

    Returns:
        The first successful PlannerResult, or the last error result
    """
    try_families = families or _get_families()

    last_result: Optional[PlannerResult] = None

    for family in try_families:
        result = await run_planner(family, role, prompt, cwd, timeout_sec)

        if result.reason_code == "bad_role" or result.reason_code == "bad_argv":
            # Programming error: stop immediately
            return result

        if result.is_ok():
            return result

        # Non-fatal error: try the next family
        last_result = result

    # All families failed; return the last result
    return last_result or PlannerResult(
        reason_code="no_families",
        family="",
        role=role,
        model="",
        effort="",
        error="no families available to try",
    )
