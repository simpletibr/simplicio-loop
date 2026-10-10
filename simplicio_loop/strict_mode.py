"""Strict operator-only loop mode.

When ``SIMPLICIO_LOOP_STRICT`` is on, the loop refuses silent degradation to
LLM hand-survey / hand-edit: the two bound operators (``simplicio-mapper``,
``simplicio-dev-cli``) are mandatory, evidence is mandatory, and mutation
authority stays fail-closed. Execution is always standalone -- there is no
Runtime/MCP backend in this stack.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Mapping, Optional, Sequence

from .error_truncation import truncate_error_with_cause

TRUE_VALUES = frozenset({"1", "true", "yes", "on", "strict", "full-stack", "required"})
FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled", "standalone", "legacy"})

CORE_OPERATORS: tuple[str, ...] = ("simplicio-mapper", "simplicio-dev-cli")


def _env(env: Optional[Mapping[str, str]] = None) -> Mapping[str, str]:
    return os.environ if env is None else env


def env_flag(name: str, *, env: Optional[Mapping[str, str]] = None, default: str = "") -> str:
    return str(_env(env).get(name, default) or "").strip().lower()


def is_truthy(value: str) -> bool:
    return value in TRUE_VALUES


def is_falsy(value: str) -> bool:
    return value in FALSE_VALUES


def strict_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when strict operator-only mode is armed."""
    source = _env(env)
    if is_truthy(env_flag("SIMPLICIO_LOOP_STRICT", env=source)):
        return True
    mode = env_flag("SIMPLICIO_LOOP_MODE", env=source)
    if mode in {"strict", "full-stack"}:
        return True
    # Active orchestrator state + explicit SIMPLICIO_LOOP=1 also arms strict for hosts.
    if is_truthy(env_flag("SIMPLICIO_LOOP", env=source)) and is_truthy(
        env_flag("SIMPLICIO_LOOP_STRICT_DEFAULT", env=source, default="0")
    ):
        return True
    return False


def _short_error(text: str) -> str:
    return truncate_error_with_cause(text, head_chars=100, tail_chars=100, total_limit=200)


def _probe_version(
    binary: str,
    args: Sequence[str] = ("--version",),
    timeout: float = 8.0,
    *,
    path: Optional[str] = None,
) -> dict[str, Any]:
    resolved = path or shutil.which(binary)
    if not resolved:
        return {"binary": binary, "present": False, "operational": False, "version": "", "error": "not on PATH"}
    try:
        completed = subprocess.run(
            [resolved, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        ok = completed.returncode == 0
        version = ""
        if ok:
            text = (completed.stdout or completed.stderr or "").strip()
            version = text.splitlines()[0] if text else "ok"
        return {
            "binary": binary,
            "present": True,
            "operational": ok,
            "version": version,
            "error": "" if ok else _short_error(completed.stderr or completed.stdout or "probe failed"),
            "path": resolved,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "binary": binary,
            "present": True,
            "operational": False,
            "version": "",
            "error": _short_error(str(exc)),
            "path": resolved,
        }


def mapper_status(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Probe the survey operator in-process: it ships inside this distribution."""
    del env
    try:
        from simplicio_mapper import __version__ as version
    except ImportError:
        return {
            "binary": "simplicio-mapper", "present": False, "operational": False, "version": "",
            "error": "package_not_installed", "reason": "package_not_installed",
            "package": "simplicio_mapper",
        }
    return {
        "binary": "simplicio-mapper", "present": True, "operational": True, "version": str(version),
        "error": "", "package": "simplicio-loop",
    }


def _sanitize_version_banner(version: str) -> str:
    """Drop argparse usage banners accidentally captured as version strings."""
    text = (version or "").strip()
    if not text:
        return ""
    first = text.splitlines()[0].strip()
    lowered = first.lower()
    if lowered.startswith("usage:") or lowered.startswith("options:") or lowered.startswith("positional arguments"):
        return ""
    return first


def _load_dev_cli_capabilities() -> dict[str, Any]:
    from simplicio.capabilities import load_capabilities_manifest

    return load_capabilities_manifest()


def action_operator_status(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Probe the operate binary in-process, no --version/--help subprocess.

    ``simplicio-dev-cli capabilities --json`` and
    ``simplicio.capabilities.load_capabilities_manifest()`` read the exact
    same packaged manifest; a caller that shares the interpreter (this loop)
    reads it directly instead of spawning the binary. A missing/unimportable
    manifest fails closed with a typed reason -- there is no legacy
    subprocess fallback.
    """
    del env
    try:
        manifest = _load_dev_cli_capabilities()
    except Exception as exc:  # pragma: no cover - defensive: uninstalled/broken package
        return {
            "binary": "simplicio-dev-cli",
            "present": False,
            "operational": False,
            "version": "",
            "error": f"dev_cli_capabilities_unavailable: {exc}"[:200],
            "reason": "dev_cli_capabilities_unavailable",
            "role": "operate",
            "resolved_as": "simplicio-dev-cli",
        }
    package = manifest.get("package") if isinstance(manifest.get("package"), Mapping) else {}
    entrypoints = manifest.get("entrypoints") if isinstance(manifest.get("entrypoints"), Mapping) else {}
    version = str(package.get("version") or "")
    resolved_as = str(entrypoints.get("adapter") or "simplicio-dev-cli")
    return {
        "binary": resolved_as,
        "present": True,
        "operational": True,
        "version": version,
        "error": "",
        "role": "operate",
        "resolved_as": resolved_as,
        "package": str(package.get("name") or "simplicio-cli"),
        "capabilities_schema": manifest.get("schema"),
    }


def python_alias_status(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """``simplicio-py``'s status: the same package/version as ``simplicio-dev-cli``."""
    status = action_operator_status(env)
    if not status["operational"]:
        return {"binary": "simplicio-py", "present": False, "operational": False,
                "version": "", "error": status.get("error", "")}
    return {"binary": "simplicio-py", "present": True, "operational": True,
            "version": status.get("version", ""), "error": ""}


def required_bound_operators(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """Binaries the running loop must keep available.

    Always: mapper + operate (dev-cli or py alias checked separately by callers).
    """
    del env
    return list(CORE_OPERATORS)


def missing_required_operators(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """Return required binaries that are missing or non-operational."""
    missing: list[str] = []
    required = required_bound_operators(env)
    # Operate role: either alias satisfies simplicio-dev-cli requirement.
    action_ok = action_operator_status(env)["operational"]
    for name in required:
        if name == "simplicio-dev-cli":
            if not action_ok:
                missing.append("simplicio-dev-cli")
            continue
        if name == "simplicio-mapper":
            if not mapper_status(env)["operational"]:
                missing.append(name)
            continue
        # any other required binary still gets a real subprocess probe
        status = _probe_version(name, ("--version",))
        if not status["operational"]:
            missing.append(name)
    return missing


def resolve_execution_profile(env: Optional[Mapping[str, str]] = None) -> str:
    """Return the execution profile. Always ``standalone`` -- there is no
    Runtime/MCP backend in this stack.
    """
    del env
    return "standalone"


def hand_edit_forbidden(env: Optional[Mapping[str, str]] = None) -> bool:
    """Under strict mode, host hand-edit tools must not mutate the repo."""
    if strict_enabled(env):
        return True
    return is_truthy(env_flag("SIMPLICIO_LOOP_FORBID_HAND_EDIT", env=env))


def evidence_required_locked(env: Optional[Mapping[str, str]] = None) -> bool:
    """Strict mode refuses evidence_required=false on the scratchpad."""
    return strict_enabled(env)


def recommended_env(env: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Env vars for a strict, **economy-parallel** armada (default).

    Prefers the fastest token path (mapper handoff) and bounded
    parallel workers (Prism slots + AUTO_FAN_OUT + asyncio). Opt out with
    ``SIMPLICIO_ECONOMY_PARALLEL=0`` for a minimal strict envelope only.
    """
    try:
        from .economy_profile import economy_parallel_enabled, economy_parallel_env

        if economy_parallel_enabled(env):
            return economy_parallel_env(env=env)
    except Exception:
        pass
    # Minimal strict fallback
    out = {
        "SIMPLICIO_LOOP": "1",
        "SIMPLICIO_LOOP_STRICT": "1",
        "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY": "1",
        "SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT": "1",
        "SIMPLICIO_EXECUTION_PROFILE": "standalone",
        "SIMPLICIO_LOOP_FORBID_HAND_EDIT": "1",
        "SIMPLICIO_OPERATOR_ALWAYS_LATEST": "1",
        "SIMPLICIO_LOOP_AUTO_FAN_OUT": "1",
    }
    return out


def preflight_payload(repo: str, *, strict: bool = False, env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Build the machine-readable preflight document (strict-aware)."""
    source = dict(_env(env))
    if strict:
        source["SIMPLICIO_LOOP_STRICT"] = "1"
    mapper = mapper_status(source)
    action = action_operator_status(source)
    # simplicio-py is the same installed package/version as simplicio-dev-cli
    # (in-process, via the capabilities manifest -- no subprocess probe).
    py_alias = python_alias_status(source)
    operators = [
        {
            "name": "simplicio-mapper",
            "present": mapper["operational"],
            "version": mapper.get("version", ""),
            "error": mapper.get("error", ""),
        },
        {
            "name": "simplicio-dev-cli",
            "present": action["operational"],
            "version": action.get("version", ""),
            "error": action.get("error", ""),
            "resolved_as": action.get("resolved_as", "simplicio-dev-cli"),
        },
        {
            "name": "simplicio-py",
            "present": bool(py_alias["operational"]),
            "version": py_alias.get("version", "") if py_alias["operational"] else "",
            "error": py_alias.get("error", "") if not py_alias["operational"] else "",
        },
    ]
    required = required_bound_operators(source)
    missing = missing_required_operators(source)
    profile = resolve_execution_profile(source)
    strict_on = strict_enabled(source)
    all_present = not missing
    return {
        "schema": "simplicio.preflight/v1",
        "repo": repo,
        "strict": strict_on,
        "all_present": all_present,
        "operators": operators,
        "required_operators": required,
        "mapper_required": True,
        "mapper_context_policy": {
            "preparation": "central",
            "workers": "consume_matching_generation_read_only",
            "stale_context": "block_and_refresh_centrally",
            "provider_cache": "unverified_until_provider_usage_receipt",
        },
        "missing_operators": missing,
        "execution_profile": profile,
        "hand_edit_forbidden": hand_edit_forbidden(source),
        "recommended_env": recommended_env(source) if strict_on else {},
    }


__all__ = [
    "CORE_OPERATORS",
    "action_operator_status",
    "evidence_required_locked",
    "hand_edit_forbidden",
    "mapper_status",
    "missing_required_operators",
    "preflight_payload",
    "python_alias_status",
    "recommended_env",
    "required_bound_operators",
    "resolve_execution_profile",
    "strict_enabled",
]
