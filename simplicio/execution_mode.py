"""Versioned execution-mode negotiation for coordinator-facing entrypoints."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from .atomic_execution import AttemptContext
from .plan_compiler.authority import AuthorizationError, EffectAuthorization
from .plan_compiler.mapper_context import (
    MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
    MapperContextError,
    load_mapper_context,
)
from .plan_compiler.runtime_effect_sink import RuntimeEffectSink
from .standalone_migration import StandalonePolicy, effect_unknown_pending, standalone_policy

ExecutionMode = Literal["auto", "integrated", "standalone"]
RUNTIME_EFFECT_CAPABILITY = "simplicio.effect-transaction/v1"
MAPPER_CONTEXT_SCHEMA = MAPPER_CONTEXT_SNAPSHOT_SCHEMA


@dataclass(frozen=True)
class ExecutionProfile:
    requested_mode: ExecutionMode
    effective_mode: Literal["integrated", "standalone", "blocked"]
    coordinator: dict[str, Any]
    runtime: dict[str, Any]
    mapper: dict[str, Any]
    sink: dict[str, Any]
    fallback_reason: str | None
    rollout: str
    default_eligible: bool
    reason_code: str
    standalone_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionInputError(ValueError):
    """Stable fail-closed error while resolving coordinator inputs."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PreparedExecutionInputs:
    context_snapshot: dict[str, Any] | None
    context_pack: dict[str, Any] | None
    execution_context: dict[str, Any] | None
    authorization: EffectAuthorization | None
    effect_sink: object | None
    runtime_handshake: dict[str, Any] | None
    attempt: AttemptContext | None


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
    return cast(ExecutionMode, raw)


def _allow_fallback(root: str | os.PathLike[str]) -> bool:
    raw = os.environ.get("SIMPLICIO_ALLOW_STANDALONE_FALLBACK")
    if raw is None:
        # Auto must not turn an unavailable/incompatible Runtime into a
        # mutating standalone execution by default. Coordinators may opt in
        # during the migration window; explicit ``--mode standalone`` remains
        # a separate, intentional lifecycle.
        raw = str(_config(root).get("allow_standalone_fallback", False))
    return raw.lower() in {"1", "true", "yes", "on"}


def _load_context_snapshot(
    root: str | os.PathLike[str], explicit_path: str | os.PathLike[str] | None
) -> dict[str, Any] | None:
    config = _config(root)
    raw_path = explicit_path or os.environ.get("SIMPLICIO_CONTEXT_SNAPSHOT") or config.get("context_snapshot")
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        with path.open("rb") as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ExecutionInputError("INCOMPATIBLE_CONTEXT", "context snapshot exceeds 16 MiB")
        payload = json.loads(raw.decode("utf-8"))
    except ExecutionInputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionInputError("INCOMPATIBLE_CONTEXT", "cannot read canonical context snapshot") from exc
    if not isinstance(payload, dict):
        raise ExecutionInputError("INCOMPATIBLE_CONTEXT", "context snapshot must be a JSON object")
    return payload


def _load_context_pack(
    root: str | os.PathLike[str], explicit_path: str | os.PathLike[str] | None
) -> dict[str, Any] | None:
    config = _config(root)
    raw_path = explicit_path or os.environ.get("SIMPLICIO_CONTEXT_PACK") or config.get("context_pack")
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        with path.open("rb") as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ExecutionInputError("INCOMPATIBLE_CONTEXT_PACK", "context pack exceeds 16 MiB")
        payload = json.loads(raw.decode("utf-8"))
    except ExecutionInputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionInputError("INCOMPATIBLE_CONTEXT_PACK", "cannot read canonical context pack") from exc
    if not isinstance(payload, dict):
        raise ExecutionInputError("INCOMPATIBLE_CONTEXT_PACK", "context pack must be a JSON object")
    return payload


def _load_execution_context(
    root: str | os.PathLike[str], explicit_path: str | os.PathLike[str] | None
) -> dict[str, Any] | None:
    config = _config(root)
    raw_path = (
        explicit_path or os.environ.get("SIMPLICIO_EXECUTION_CONTEXT") or config.get("execution_context")
    )
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        with path.open("rb") as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ExecutionInputError("INCOMPATIBLE_EXECUTION_CONTEXT", "execution context exceeds 16 MiB")
        payload = json.loads(raw.decode("utf-8"))
    except ExecutionInputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionInputError(
            "INCOMPATIBLE_EXECUTION_CONTEXT", "cannot read Mapper execution context"
        ) from exc
    if not isinstance(payload, dict):
        raise ExecutionInputError("INCOMPATIBLE_EXECUTION_CONTEXT", "execution context must be a JSON object")
    return payload


def _load_authorization(
    root: str | os.PathLike[str], explicit_path: str | os.PathLike[str] | None
) -> EffectAuthorization | None:
    config = _config(root)
    raw_path = (
        explicit_path
        or os.environ.get("SIMPLICIO_EFFECT_AUTHORIZATION")
        or config.get("effect_authorization")
    )
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EffectAuthorization.from_dict(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, AuthorizationError) as exc:
        raise ExecutionInputError(
            "INCOMPATIBLE_AUTHORIZATION", "cannot load coordinator-issued effect authorization"
        ) from exc


def _attempt_context(
    *,
    attempt_id: str | None,
    lease_id: str | None,
    fencing_token: str | None,
    context_handle: str | None,
) -> AttemptContext | None:
    values = (
        attempt_id or os.environ.get("SIMPLICIO_ATTEMPT_ID"),
        lease_id or os.environ.get("SIMPLICIO_LEASE_ID"),
        fencing_token or os.environ.get("SIMPLICIO_FENCING_TOKEN"),
        context_handle or os.environ.get("SIMPLICIO_CONTEXT_HANDLE"),
    )
    if not any(values):
        return None
    if not all(value and value.strip() for value in values):
        raise ExecutionInputError(
            "COORDINATOR_CONTEXT_REQUIRED",
            "all coordinator attempt fields are required: attempt, lease, fence, and context handle",
        )
    return AttemptContext(*cast(tuple[str, str, str, str], values))


def prepare_execution_inputs(
    mode: str | None = None,
    *,
    root: str | os.PathLike[str] = ".",
    context_snapshot: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
    execution_context: dict[str, Any] | None = None,
    authorization: EffectAuthorization | None = None,
    context_snapshot_path: str | os.PathLike[str] | None = None,
    context_pack_path: str | os.PathLike[str] | None = None,
    execution_context_path: str | os.PathLike[str] | None = None,
    authorization_path: str | os.PathLike[str] | None = None,
    effect_sink: object | None = None,
    runtime_handshake: dict[str, Any] | None = None,
    attempt: AttemptContext | None = None,
    attempt_id: str | None = None,
    lease_id: str | None = None,
    fencing_token: str | None = None,
    context_handle: str | None = None,
) -> PreparedExecutionInputs:
    """Resolve installed-entrypoint inputs without probing in standalone mode."""
    if requested_mode(mode, root) == "standalone":
        # Standalone still needs to consume an explicitly supplied context pack.
        # Previously the path arguments were silently ignored in this branch, so
        # Loop's local degraded context never reached the task precondition gate.
        resolved_pack = (
            context_pack if context_pack is not None else _load_context_pack(root, context_pack_path)
        )
        return PreparedExecutionInputs(
            context_snapshot,
            resolved_pack,
            execution_context,
            authorization,
            effect_sink,
            runtime_handshake,
            attempt,
        )

    resolved_context = (
        context_snapshot
        if context_snapshot is not None
        else _load_context_snapshot(root, context_snapshot_path)
    )
    resolved_pack = context_pack if context_pack is not None else _load_context_pack(root, context_pack_path)
    resolved_execution_context = (
        execution_context
        if execution_context is not None
        else _load_execution_context(root, execution_context_path)
    )
    resolved_authorization = (
        authorization if authorization is not None else _load_authorization(root, authorization_path)
    )
    resolved_sink = effect_sink
    offline_runtime = os.environ.get("SIMPLICIO_RUNTIME_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if resolved_sink is None and (os.environ.get("SIMPLICIO_RUNTIME_URL", "").strip() or offline_runtime):
        resolved_sink = RuntimeEffectSink.from_environment(root=Path(root))
    resolved_handshake = runtime_handshake
    handshake = getattr(resolved_sink, "capability_handshake", None)
    if resolved_handshake is None and callable(handshake):
        resolved_handshake = handshake()
    resolved_attempt = attempt or _attempt_context(
        attempt_id=attempt_id,
        lease_id=lease_id,
        fencing_token=fencing_token,
        context_handle=context_handle,
    )
    return PreparedExecutionInputs(
        resolved_context,
        resolved_pack,
        resolved_execution_context,
        resolved_authorization,
        resolved_sink,
        resolved_handshake,
        resolved_attempt,
    )


def blocked_input_profile(
    mode: str | None,
    error: ExecutionInputError,
    *,
    root: str | os.PathLike[str] = ".",
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
) -> ExecutionProfile:
    """Build complete diagnostics for input failures before negotiation."""
    config = _config(root)
    pending = "effect_unknown" if effect_unknown_pending(str(root)) else None
    policy = standalone_policy(config, previous_effect_outcome=pending)
    return ExecutionProfile(
        requested_mode(mode, root),
        "blocked",
        {
            "kind": coordinator_kind or os.environ.get("SIMPLICIO_COORDINATOR_KIND", "unknown"),
            "id": coordinator_id or os.environ.get("SIMPLICIO_COORDINATOR_ID", ""),
        },
        {
            "verified": False,
            "version": None,
            "capability": RUNTIME_EFFECT_CAPABILITY,
            "capability_available": False,
            "reason": "not-probed-after-input-error",
        },
        {
            "schema": None,
            "compatible": False,
            "digest": None,
            "contract_error": error.code,
        },
        {"configured": False, "production": False, "kind": None},
        None,
        os.environ.get("SIMPLICIO_EXECUTION_ROLLOUT", str(config.get("rollout", "default"))),
        False,
        error.code,
        policy.to_dict(),
    )


def require_coordinator_attempt(
    profile: ExecutionProfile, attempt: AttemptContext | None
) -> ExecutionProfile:
    """Fail closed when an otherwise integrated selection lacks an atomic attempt."""
    if profile.effective_mode != "integrated" or attempt is not None:
        return profile
    return replace(
        profile,
        effective_mode="blocked",
        coordinator={**profile.coordinator, "attempt_ready": False},
        default_eligible=False,
        reason_code="COORDINATOR_CONTEXT_REQUIRED",
    )


def negotiate_execution_mode(
    mode: str | None = None,
    *,
    root: str | os.PathLike[str] = ".",
    runtime_handshake: dict[str, Any] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    effect_sink: object | None = None,
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
    previous_effect_outcome: str | None = None,
    read_only: bool = False,
) -> ExecutionProfile:
    """Negotiate only from versioned contracts; never infer from files/help/process names."""
    requested = requested_mode(mode, root)
    config = _config(root)
    rollout = os.environ.get("SIMPLICIO_EXECUTION_ROLLOUT", str(config.get("rollout", "default")))
    coordinator = {
        "kind": coordinator_kind or os.environ.get("SIMPLICIO_COORDINATOR_KIND", "unknown"),
        "id": coordinator_id or os.environ.get("SIMPLICIO_COORDINATOR_ID", ""),
    }
    persisted_outcome = "effect_unknown" if effect_unknown_pending(str(root)) else None
    policy: StandalonePolicy = standalone_policy(
        config,
        previous_effect_outcome=previous_effect_outcome or persisted_outcome,
    )
    if requested == "standalone":
        if read_only:
            return ExecutionProfile(
                requested,
                "standalone",
                coordinator,
                {
                    "verified": False,
                    "version": None,
                    "capability": RUNTIME_EFFECT_CAPABILITY,
                    "capability_available": False,
                    "reason": "not-probed-standalone",
                },
                {"schema": None, "compatible": False, "digest": None, "contract_error": None},
                {"configured": False, "production": False, "kind": None},
                None,
                rollout,
                False,
                "STANDALONE_READ_ONLY",
                policy.to_dict(),
            )
        effective: Literal["standalone", "blocked"] = "standalone" if policy.write_allowed else "blocked"
        return ExecutionProfile(
            requested,
            effective,
            coordinator,
            {
                "verified": False,
                "version": None,
                "capability": RUNTIME_EFFECT_CAPABILITY,
                "capability_available": False,
                "reason": "not-probed-standalone",
            },
            {"schema": None, "compatible": False, "digest": None, "contract_error": None},
            {"configured": False, "production": False, "kind": None},
            None,
            rollout,
            False,
            "STANDALONE_EXPLICIT" if policy.write_allowed else policy.reason_code,
            policy.to_dict(),
        )

    from .runtime_contracts import runtime_verify_contract

    raw_handshake = runtime_handshake if runtime_handshake is not None else runtime_verify_contract()
    handshake = (
        raw_handshake
        if isinstance(raw_handshake, dict)
        else {
            "verified": False,
            "version": None,
            "capabilities": [],
            "reason": "RUNTIME_HANDSHAKE_INVALID",
        }
    )
    capabilities = handshake.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    runtime_ready = bool(handshake.get("verified")) and RUNTIME_EFFECT_CAPABILITY in capabilities
    snapshot_schema = context_snapshot.get("schema") if isinstance(context_snapshot, dict) else None
    mapper_error: str | None = None
    mapper_adapter = None
    if context_snapshot is not None:
        try:
            mapper_adapter = load_mapper_context(context_snapshot, source_root=str(root))
        except MapperContextError as exc:
            mapper_error = exc.code
    mapper_ready = mapper_adapter is not None
    sink_ready = isinstance(effect_sink, RuntimeEffectSink)
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
        "digest": (
            hashlib.sha256(mapper_adapter.payload_bytes).hexdigest() if mapper_adapter is not None else None
        ),
        "contract_error": mapper_error,
    }
    sink = {
        "configured": effect_sink is not None,
        "production": sink_ready,
        "kind": effect_sink.__class__.__name__ if effect_sink else None,
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
    if read_only:
        return ExecutionProfile(
            requested,
            "standalone",
            coordinator,
            runtime,
            mapper,
            sink,
            "READ_ONLY_EXECUTION",
            rollout,
            eligible,
            "INTEGRATED_READ_ONLY" if requested == "integrated" else "AUTO_READ_ONLY",
            policy.to_dict(),
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
            policy.to_dict(),
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
            policy.to_dict(),
        )
    if not _allow_fallback(root) or not policy.write_allowed:
        reason = policy.reason_code if not policy.write_allowed else missing
        return ExecutionProfile(
            requested,
            "blocked",
            coordinator,
            runtime,
            mapper,
            sink,
            None,
            rollout,
            False,
            reason,
            policy.to_dict(),
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
        policy.to_dict(),
    )


def capabilities_report(
    mode: str | None = None,
    *,
    root: str = ".",
    context_snapshot_path: str | os.PathLike[str] | None = None,
    context_pack_path: str | os.PathLike[str] | None = None,
    execution_context_path: str | os.PathLike[str] | None = None,
    authorization_path: str | os.PathLike[str] | None = None,
    attempt_id: str | None = None,
    lease_id: str | None = None,
    fencing_token: str | None = None,
    context_handle: str | None = None,
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
) -> dict[str, Any]:
    try:
        prepared = prepare_execution_inputs(
            mode,
            root=root,
            context_snapshot_path=context_snapshot_path,
            context_pack_path=context_pack_path,
            execution_context_path=execution_context_path,
            authorization_path=authorization_path,
            attempt_id=attempt_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            context_handle=context_handle,
        )
    except ExecutionInputError as exc:
        profile = blocked_input_profile(
            mode,
            exc,
            root=root,
            coordinator_kind=coordinator_kind,
            coordinator_id=coordinator_id,
        )
        return {
            "schema": "simplicio.dev-cli.execution-capabilities/v1",
            "execution_profile": profile.to_dict(),
        }
    profile = negotiate_execution_mode(
        mode,
        root=root,
        runtime_handshake=prepared.runtime_handshake,
        context_snapshot=prepared.context_snapshot,
        effect_sink=prepared.effect_sink,
        coordinator_kind=coordinator_kind,
        coordinator_id=coordinator_id,
    )
    profile = require_coordinator_attempt(profile, prepared.attempt)
    return {
        "schema": "simplicio.dev-cli.execution-capabilities/v1",
        "execution_profile": profile.to_dict(),
    }
