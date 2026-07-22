"""Versioned execution-mode negotiation for coordinator-facing entrypoints."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ExecutionMode = Literal["auto", "integrated", "standalone"]
RUNTIME_EFFECT_CAPABILITY = "simplicio.effect-transaction/v1"
MAPPER_CONTEXT_SCHEMA = "simplicio.mapper.context-snapshot/v1"


@dataclass(frozen=True)
class ExecutionProfile:
    requested_mode: ExecutionMode
    effective_mode: Literal["integrated", "standalone", "blocked"]
    coordinator: dict[str, str]
    runtime: dict[str, Any]
    mapper: dict[str, Any]
    sink: dict[str, Any]
    fallback_reason: str | None
    rollout: str
    default_eligible: bool
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _config(root: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(root) / ".simplicio" / "execution.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def requested_mode(explicit: str | None, root: str | os.PathLike[str] = ".") -> ExecutionMode:
    """Resolve flag/API > environment > project config > auto."""
    raw = explicit or os.environ.get("SIMPLICIO_EXECUTION_MODE") or _config(root).get("mode") or "auto"
    if raw not in {"auto", "integrated", "standalone"}:
        raise ValueError("execution mode must be auto, integrated, or standalone")
    return raw


def _allow_fallback(root: str | os.PathLike[str]) -> bool:
    raw = os.environ.get("SIMPLICIO_ALLOW_STANDALONE_FALLBACK")
    if raw is None:
        raw = str(_config(root).get("allow_standalone_fallback", True))
    return raw.lower() in {"1", "true", "yes", "on"}


def negotiate_execution_mode(
    mode: str | None = None,
    *,
    root: str | os.PathLike[str] = ".",
    runtime_handshake: dict[str, Any] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    effect_sink: object | None = None,
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
) -> ExecutionProfile:
    """Negotiate only from versioned contracts; never infer from files/help/process names."""
    from .runtime_contracts import runtime_verify_contract

    requested = requested_mode(mode, root)
    handshake = runtime_handshake if runtime_handshake is not None else runtime_verify_contract()
    capabilities = handshake.get("capabilities", []) if isinstance(handshake, dict) else []
    runtime_ready = bool(handshake.get("verified")) and RUNTIME_EFFECT_CAPABILITY in capabilities
    snapshot_schema = context_snapshot.get("schema") if isinstance(context_snapshot, dict) else None
    mapper_ready = snapshot_schema == MAPPER_CONTEXT_SCHEMA
    sink_ready = effect_sink is not None and effect_sink.__class__.__name__ != "RecordingEffectSink"
    config = _config(root)
    rollout = os.environ.get("SIMPLICIO_EXECUTION_ROLLOUT", str(config.get("rollout", "shadow")))
    killed = os.environ.get("SIMPLICIO_INTEGRATED_KILL_SWITCH", "").lower() in {"1", "true", "yes", "on"}
    eligible = runtime_ready and mapper_ready and sink_ready and not killed
    runtime = {
        "verified": bool(handshake.get("verified")),
        "version": handshake.get("version"),
        "capability": RUNTIME_EFFECT_CAPABILITY,
        "capability_available": RUNTIME_EFFECT_CAPABILITY in capabilities,
        "reason": handshake.get("reason"),
    }
    mapper = {
        "schema": snapshot_schema,
        "compatible": mapper_ready,
        "digest": (context_snapshot or {}).get("digest"),
    }
    sink = {
        "configured": effect_sink is not None,
        "production": sink_ready,
        "kind": effect_sink.__class__.__name__ if effect_sink else None,
    }
    coordinator = {
        "kind": coordinator_kind or os.environ.get("SIMPLICIO_COORDINATOR_KIND", "unknown"),
        "id": coordinator_id or os.environ.get("SIMPLICIO_COORDINATOR_ID", ""),
    }
    missing = (
        "INTEGRATED_KILLED"
        if killed
        else (
            "INCOMPATIBLE_RUNTIME"
            if not runtime_ready
            else (
                "CONTEXT_REQUIRED"
                if context_snapshot is None
                else ("INCOMPATIBLE_CONTEXT" if not mapper_ready else "RUNTIME_SINK_REQUIRED")
            )
        )
    )
    if requested == "standalone":
        return ExecutionProfile(
            requested,
            "standalone",
            coordinator,
            runtime,
            mapper,
            sink,
            None,
            rollout,
            False,
            "STANDALONE_EXPLICIT",
        )
    if requested == "integrated":
        return ExecutionProfile(
            requested,
            "integrated" if eligible else "blocked",
            coordinator,
            runtime,
            mapper,
            sink,
            None,
            rollout,
            eligible,
            "INTEGRATED_READY" if eligible else missing,
        )
    if eligible and rollout in {"canary", "default"}:
        return ExecutionProfile(
            requested,
            "integrated",
            coordinator,
            runtime,
            mapper,
            sink,
            None,
            rollout,
            True,
            "AUTO_INTEGRATED",
        )
    if not _allow_fallback(root):
        return ExecutionProfile(
            requested, "blocked", coordinator, runtime, mapper, sink, None, rollout, False, missing
        )
    return ExecutionProfile(
        requested,
        "standalone",
        coordinator,
        runtime,
        mapper,
        sink,
        "SHADOW_OBSERVATION" if eligible else missing,
        rollout,
        eligible,
        "AUTO_DEGRADED",
    )


def capabilities_report(mode: str | None = None, *, root: str = ".") -> dict[str, Any]:
    return {
        "schema": "simplicio.dev-cli.execution-capabilities/v1",
        "execution_profile": negotiate_execution_mode(mode, root=root).to_dict(),
    }
