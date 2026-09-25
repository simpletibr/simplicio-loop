"""Governed migration policy from local writes to the Runtime Effect API."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .observability import emit_event
from .utils.fs import write_text_atomic

MigrationPhase = Literal["shadow", "opt_in", "warning", "read_only", "removed"]
MutationRoute = Literal["runtime_effect_api", "standalone", "legacy_standalone", "blocked"]
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


RouteAdmissionPhase = Literal["SELECTED", "ADMITTED"]
ROUTE_ADMISSION_SCHEMA = "simplicio.dev-cli.route-admission/v1"


@dataclass(frozen=True)
class MutationRouteAdmission:
    """Immutable route selection that can be admitted once before staging."""

    requested_mode: str
    route: MutationRoute
    phase: RouteAdmissionPhase = "SELECTED"
    frozen_before_effect: bool = False

    def __post_init__(self) -> None:
        if not self.requested_mode.strip():
            raise ValueError("requested_mode must be non-empty")
        if self.phase not in {"SELECTED", "ADMITTED"}:
            raise ValueError("route admission phase is invalid")
        if self.phase == "ADMITTED" and not self.frozen_before_effect:
            raise ValueError("admitted route must be frozen before effect")
        if self.phase == "SELECTED" and self.frozen_before_effect:
            raise ValueError("selected route cannot be frozen before admission")

    def admit(self) -> MutationRouteAdmission:
        if self.phase == "ADMITTED":
            return self
        return MutationRouteAdmission(self.requested_mode, self.route, "ADMITTED", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_ADMISSION_SCHEMA,
            "requested_mode": self.requested_mode,
            "route": self.route,
            "phase": self.phase,
            "frozen_before_effect": self.frozen_before_effect,
        }


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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_lock_key(value: object) -> str:
    text = str(value or "").strip()
    return text if text and "\n" not in text and "\r" not in text else "unknown"


def effect_unknown_details(
    root: str,
    *,
    plan: Any = None,
    native_plans: list[dict[str, Any]] | None = None,
    files: list[dict[str, Any]] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build redacted causal metadata for an uncertain Runtime delegation."""
    repo = str(Path(root).resolve())
    plan_payload = plan if isinstance(plan, dict) else {}
    plan_digest = _sha256_text(_canonical_json(plan_payload))
    key = _safe_lock_key(idempotency_key or plan_payload.get("idempotency_key"))
    if key == "unknown":
        key = _sha256_text(f"{repo}\n{plan_digest}")
    evidence_file = f".simplicio/runtime-effects/reconciliation/{key}.json"
    preconditions: list[dict[str, Any]] = []
    for native_plan in native_plans or []:
        path = native_plan.get("file")
        if not isinstance(path, str) or not path:
            continue
        operations = native_plan.get("operations")
        if not isinstance(operations, list):
            operations = []
        for operation in operations or [{}]:
            if not isinstance(operation, dict):
                operation = {}
            preconditions.append(
                {
                    "path": path,
                    "before_sha256": operation.get("before_sha256")
                    or operation.get("file_sha256")
                    or "unknown",
                    "expected_after_sha256": operation.get("after_sha256") or "unknown",
                }
            )
    receipt_locator = {
        "intent": f".simplicio/runtime-effects/{key}.intent.json",
        "receipt": f".simplicio/runtime-effects/{key}.receipt.json",
        "runtime_status_command": [
            "simplicio",
            "effect",
            "status",
            "--idempotency-key",
            key,
            "--repo",
            repo,
            "--json",
        ],
    }
    recovery_command = [
        "simplicio-py",
        "reconcile",
        "--root",
        repo,
        "--idempotency-key",
        key,
        "--evidence-file",
        str(Path(repo) / Path(evidence_file)),
        "--json",
    ]
    return {
        "idempotency_key": key,
        "repo": repo,
        "plan_digest": plan_digest,
        "effect_digest": plan_digest,
        "preconditions": preconditions,
        "evidence_file": evidence_file,
        "receipt_locator": receipt_locator,
        "recovery_command": recovery_command,
        "files": list(files or []),
    }


def record_effect_unknown(root: str, details: dict[str, Any] | None = None, **kwargs: Any) -> Path:
    """Persist a complete, secret-free causal reconciliation lock."""
    supplied = dict(details or {})
    supplied.update(kwargs)
    causal = effect_unknown_details(root)
    causal.update({key: value for key, value in supplied.items() if value is not None})
    if not causal.get("idempotency_key") or causal["idempotency_key"] == "unknown":
        causal = effect_unknown_details(
            root,
            plan=supplied.get("plan"),
            native_plans=supplied.get("native_plans"),
            files=supplied.get("files"),
            idempotency_key=supplied.get("idempotency_key"),
        ) | {key: value for key, value in supplied.items() if key not in {"plan", "native_plans"}}
    payload = {
        "schema": "simplicio.dev-cli.effect-unknown-lock/v2",
        "outcome": "effect_unknown",
        **causal,
        "causal": {
            key: causal[key]
            for key in ("idempotency_key", "repo", "plan_digest", "effect_digest", "preconditions")
            if key in causal
        },
    }
    return write_text_atomic(
        Path(root) / EFFECT_UNKNOWN_LOCK,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def load_effect_unknown_lock(root: str) -> dict[str, Any] | None:
    """Read the JSON v2 lock, while recognizing the legacy text lock."""
    path = Path(root) / EFFECT_UNKNOWN_LOCK
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        fields = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        return fields or None
    return payload if isinstance(payload, dict) else None


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
        if expected_effect_boundary_digest and boundary_digest != expected_effect_boundary_digest:
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
    available: dict[str, Any] | None = None,
    plan: Any = None,
    changeset: Any = None,
    files: list[Any] | None = None,
    verification: dict[str, Any] | None = None,
    retry: dict[str, Any] | None = None,
    duration_ms: int | float | None = None,
    final_status: str | None = None,
) -> dict[str, Any]:
    """Return one stable route receipt without claiming an unobserved gate."""
    available_payload = dict(available or {})
    verification_payload = dict(verification or {})
    verification_payload.setdefault("commands", [])
    verification_payload.setdefault("results", [])
    retry_payload = dict(retry or {})
    retry_payload.setdefault("attempt", 1)
    retry_payload.setdefault("max_attempts", 1)
    retry_payload.setdefault("retryable", False)
    return {
        "schema": MUTATION_ROUTE_SCHEMA,
        "receipt_version": 1,
        "entrypoint": entrypoint,
        "route": route,
        "runtime_gated": runtime_gate_verified,
        # Keep the field for receipt readers from older releases. Normal
        # standalone selections are first-class; an explicit legacy opt-in
        # remains marked for migration/compatibility consumers.
        "legacy": route == "legacy_standalone" or bool(policy and policy.legacy_opt_in),
        "migration_phase": policy.phase if policy is not None else None,
        "available": available_payload,
        "available_tuple": [key for key, value in available_payload.items() if value is not None],
        "plan": plan,
        "changeset": changeset,
        "files": list(files or []),
        "verification": verification_payload,
        "retry": retry_payload,
        "duration_ms": duration_ms,
        "final_status": final_status or ("blocked" if route == "blocked" else "unknown"),
    }


def mutation_route_for_mode(effective_mode: str) -> MutationRoute:
    if effective_mode == "integrated":
        return "runtime_effect_api"
    if effective_mode == "standalone":
        return "standalone"
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
