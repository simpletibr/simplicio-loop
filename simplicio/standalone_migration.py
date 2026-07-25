"""Governed migration policy from local writes to the Runtime Effect API."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .observability import emit_event
from .utils.fs import write_text_atomic

MigrationPhase = Literal["shadow", "opt_in", "warning", "read_only", "removed"]
MutationRoute = Literal["runtime_effect_api", "legacy_standalone", "blocked"]
MIGRATION_PHASES = ("shadow", "opt_in", "warning", "read_only", "removed")
MUTATION_ROUTE_SCHEMA = "simplicio.dev-cli.mutation-route/v1"
ROLLOUT_EVIDENCE_SCHEMA = "simplicio.dev-cli.standalone-rollout-evidence/v1"
ROLLOUT_EVIDENCE_PATH = ".simplicio/standalone-rollout-evidence.json"
EFFECT_UNKNOWN_LOCK = ".simplicio/effect-unknown.lock"
_REQUIRED_ROLLOUT_RECEIPTS = (
    "runtime_loop",
    "offline_parity",
    "clean_install",
    "upgrade",
    "downgrade",
    "rollback",
)


@dataclass(frozen=True)
class StandalonePolicy:
    phase: MigrationPhase
    legacy_opt_in: bool
    write_allowed: bool
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RolloutReadiness:
    target_phase: MigrationPhase
    ready: bool
    reason_codes: tuple[str, ...]
    receipt_ids: dict[str, str]
    producer_versions: dict[str, str]
    effect_boundary_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def migration_phase(config: dict[str, Any] | None = None) -> MigrationPhase:
    raw = os.environ.get("SIMPLICIO_STANDALONE_MIGRATION_PHASE")
    if raw is None and config is not None:
        raw = str(config.get("standalone_migration_phase", "shadow"))
    value = "shadow" if raw is None else raw.strip().lower()
    if value not in MIGRATION_PHASES:
        return "read_only"
    return cast(MigrationPhase, value)


def standalone_policy(
    config: dict[str, Any] | None = None,
    *,
    previous_effect_outcome: str | None = None,
) -> StandalonePolicy:
    """Resolve compatibility without ever falling back after an unknown effect."""
    phase = migration_phase(config)
    env_opt_in = os.environ.get("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE")
    configured = (config or {}).get("enable_legacy_standalone_write", False)
    opted_in = _truthy(env_opt_in if env_opt_in is not None else configured)
    if previous_effect_outcome == "effect_unknown":
        return StandalonePolicy(phase, opted_in, False, "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED")
    if phase in {"read_only", "removed"}:
        return StandalonePolicy(phase, opted_in, False, "LEGACY_STANDALONE_READ_ONLY")
    if phase in {"opt_in", "warning"} and not opted_in:
        return StandalonePolicy(phase, False, False, "LEGACY_STANDALONE_OPT_IN_REQUIRED")
    reason = "LEGACY_STANDALONE_OPTED_IN" if opted_in else "LEGACY_STANDALONE_SHADOW"
    return StandalonePolicy(phase, opted_in, True, reason)


def effect_unknown_pending(root: str) -> bool:
    return (Path(root) / EFFECT_UNKNOWN_LOCK).is_file()


def record_effect_unknown(root: str) -> Path:
    """Persist a secret-free reconciliation lock before another invocation."""
    return write_text_atomic(
        Path(root) / EFFECT_UNKNOWN_LOCK,
        "schema=simplicio.dev-cli.effect-unknown-lock/v1\noutcome=effect_unknown\n",
    )


def clear_effect_unknown(root: str, *, runtime_reconciled: bool) -> None:
    """Clear only after the caller has verified Runtime's causal outcome."""
    if not runtime_reconciled:
        raise ValueError("Runtime reconciliation proof is required")
    (Path(root) / EFFECT_UNKNOWN_LOCK).unlink(missing_ok=True)


def standalone_policy_for_root(root: str, *, previous_effect_outcome: str | None = None) -> StandalonePolicy:
    path = Path(root) / ".simplicio" / "execution.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    outcome = previous_effect_outcome or ("effect_unknown" if effect_unknown_pending(root) else None)
    return standalone_policy(config, previous_effect_outcome=outcome)


def rollout_readiness(
    payload: Any,
    *,
    target_phase: MigrationPhase,
    expected_effect_boundary_digest: str = "",
) -> RolloutReadiness:
    """Validate promotion evidence without inferring cross-repository success."""
    reasons: list[str] = []
    receipt_ids: dict[str, str] = {}
    producer_versions: dict[str, str] = {}
    boundary_digest = ""
    if not isinstance(payload, dict) or payload.get("schema") != ROLLOUT_EVIDENCE_SCHEMA:
        reasons.append("ROLLOUT_EVIDENCE_SCHEMA_INVALID")
    else:
        if payload.get("target_phase") != target_phase:
            reasons.append("ROLLOUT_TARGET_PHASE_MISMATCH")
        receipts = payload.get("receipts")
        if not isinstance(receipts, dict):
            reasons.append("ROLLOUT_RECEIPTS_INVALID")
        else:
            for name in _REQUIRED_ROLLOUT_RECEIPTS:
                value = receipts.get(name)
                if not isinstance(value, str) or not value.strip():
                    reasons.append(f"ROLLOUT_RECEIPT_MISSING:{name}")
                else:
                    receipt_ids[name] = value.strip()
        versions = payload.get("producer_versions")
        if not isinstance(versions, dict):
            reasons.append("ROLLOUT_PRODUCER_VERSIONS_INVALID")
        else:
            for name in ("dev_cli", "loop", "runtime"):
                value = versions.get(name)
                if not isinstance(value, str) or not value.strip():
                    reasons.append(f"ROLLOUT_PRODUCER_VERSION_MISSING:{name}")
                else:
                    producer_versions[name] = value.strip()
        unresolved = payload.get("unresolved_effect_unknown")
        if not isinstance(unresolved, int) or isinstance(unresolved, bool) or unresolved != 0:
            reasons.append("ROLLOUT_EFFECT_UNKNOWN_UNRESOLVED")
        boundary_digest = str(payload.get("effect_boundary_digest") or "")
        if (
            expected_effect_boundary_digest
            and boundary_digest != expected_effect_boundary_digest
        ):
            reasons.append("ROLLOUT_EFFECT_BOUNDARY_BASELINE_MISMATCH")
    return RolloutReadiness(
        target_phase=target_phase,
        ready=not reasons,
        reason_codes=tuple(reasons),
        receipt_ids=receipt_ids,
        producer_versions=producer_versions,
        effect_boundary_digest=boundary_digest,
    )


def rollout_readiness_for_root(
    root: str,
    *,
    target_phase: MigrationPhase,
    expected_effect_boundary_digest: str = "",
) -> RolloutReadiness:
    path = Path(root) / ROLLOUT_EVIDENCE_PATH
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    return rollout_readiness(
        payload,
        target_phase=target_phase,
        expected_effect_boundary_digest=expected_effect_boundary_digest,
    )


def mutation_receipt(
    route: MutationRoute,
    *,
    entrypoint: str,
    policy: StandalonePolicy | None = None,
    runtime_gate_verified: bool = False,
) -> dict[str, Any]:
    """Return additive route metadata without claiming an unobserved Runtime gate."""
    return {
        "schema": MUTATION_ROUTE_SCHEMA,
        "entrypoint": entrypoint,
        "route": route,
        "runtime_gated": runtime_gate_verified,
        "legacy": route == "legacy_standalone",
        "migration_phase": policy.phase if policy is not None else None,
    }


def mutation_route_for_mode(effective_mode: str) -> MutationRoute:
    if effective_mode == "integrated":
        return "runtime_effect_api"
    if effective_mode == "standalone":
        return "legacy_standalone"
    return "blocked"


def emit_mutation_route(
    *,
    root: str,
    entrypoint: str,
    route: MutationRoute,
    reason_code: str,
    policy: StandalonePolicy | None = None,
) -> None:
    """Emit aggregate-safe routing telemetry; never include plans, prompts, or secrets."""
    emit_event(
        "mutation_route_selected",
        {
            "schema": MUTATION_ROUTE_SCHEMA,
            "entrypoint": entrypoint,
            "route": route,
            "reason_code": reason_code,
            "migration_phase": policy.phase if policy is not None else None,
            "legacy_opt_in": policy.legacy_opt_in if policy is not None else False,
        },
        level="warning" if route != "runtime_effect_api" else "info",
        root=root,
    )
