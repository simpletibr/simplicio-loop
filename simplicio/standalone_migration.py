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
EFFECT_UNKNOWN_LOCK = ".simplicio/effect-unknown.lock"


@dataclass(frozen=True)
class StandalonePolicy:
    phase: MigrationPhase
    legacy_opt_in: bool
    write_allowed: bool
    reason_code: str

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
