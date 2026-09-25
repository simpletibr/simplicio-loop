"""Fail-closed validator for the versioned Fast<->Local contract surface."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

CONTRACT_SCHEMA = "simplicio.fast-local/v1"
CONTRACT_VERSION = "1.0"
MANIFEST_SCHEMA = "simplicio.fast-local.manifest/v1"
TELEMETRY_LEVELS = ("minimal", "standard", "deep")
INVALIDATION_TRIGGERS = (
    "model_drift",
    "backend_drift",
    "hardware_drift",
    "context_drift",
    "concurrency_drift",
)
DRIFT_FIELDS = (
    ("model_digest", "model_drift"),
    ("backend_digest", "backend_drift"),
    ("hardware_digest", "hardware_drift"),
    ("context_digest", "context_drift"),
    ("concurrency_digest", "concurrency_drift"),
)
TELEMETRY_FIELDS = (
    "tokens_per_second",
    "ttft_ms",
    "acceptance_rate",
    "memory_used_bytes",
    "bandwidth_bytes_per_second",
    "transfer_bytes",
    "cache_pressure_ratio",
    "stage_timings_ms",
)
TELEMETRY_REQUIRED = {
    "minimal": frozenset(("tokens_per_second", "memory_used_bytes")),
    "standard": frozenset(
        (
            "tokens_per_second",
            "memory_used_bytes",
            "ttft_ms",
            "acceptance_rate",
            "bandwidth_bytes_per_second",
            "transfer_bytes",
        )
    ),
    "deep": frozenset(TELEMETRY_FIELDS),
}
TELEMETRY_UNAVAILABLE = frozenset(TELEMETRY_FIELDS)
UNAVAILABLE_REASONS = frozenset(
    ("not_collected", "not_supported", "not_exposed", "not_applicable", "redacted")
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class ContractSurfaceError(ValueError):
    """Stable fail-closed reason code for an invalid contract message."""

    def __init__(self, reason_code: str, path: str = "") -> None:
        self.reason_code = reason_code
        self.path = path
        super().__init__(f"{reason_code}:{path}" if path else reason_code)


def _fail(reason: str, path: str = "") -> None:
    raise ContractSurfaceError(reason, path)


def _map(value: object, reason: str, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _fail(reason, path)
    return value


def _keys(
    value: Mapping[str, Any], required: set[str], optional: set[str], path: str
) -> None:
    missing = sorted(required - set(value))
    if missing:
        _fail("required_field_missing", f"{path}.{missing[0]}")
    unknown = sorted(set(value) - required - optional)
    if unknown:
        _fail("unknown_field", f"{path}.{unknown[0]}")


def _text(value: object, reason: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(reason, path)
    return value


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ContractSurfaceError("payload_not_json") from error


def digest_for(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def validate_contract_version(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]+", value) is None:
        _fail("contract_version_invalid", "contract_version")
    major, minor = (int(part) for part in value.split(".", 1))
    if major != 1:
        _fail("contract_major_unsupported", "contract_version")
    if (major, minor) != (1, 0):
        _fail("contract_version_unsupported", "contract_version")
    return value


def _digest(value: object, path: str) -> str:
    text = _text(value, "digest_invalid", path)
    if _DIGEST.fullmatch(text) is None:
        _fail("digest_invalid", path)
    return text


def _generation(value: object, path: str = "generation") -> dict[str, Any]:
    generation = _map(value, "generation_invalid", path)
    fields = {
        "generation_id",
        "source_revision",
        "hardware_digest",
        "model_digest",
        "backend_digest",
        "context_digest",
        "concurrency_digest",
    }
    _keys(generation, fields, set(), path)
    _text(generation["generation_id"], "generation_id_invalid", f"{path}.generation_id")
    if (
        not isinstance(generation["source_revision"], str)
        or _REVISION.fullmatch(generation["source_revision"]) is None
    ):
        _fail("source_revision_invalid", f"{path}.source_revision")
    for field in fields - {"generation_id", "source_revision"}:
        _digest(generation[field], f"{path}.{field}")
    return dict(generation)


def _unavailable(value: object, allowed: frozenset[str]) -> dict[str, str]:
    fields = _map(value, "unavailable_invalid", "payload.unavailable")
    for field, reason in fields.items():
        if field not in allowed:
            _fail("unavailable_field_invalid", f"payload.unavailable.{field}")
        if reason not in UNAVAILABLE_REASONS:
            _fail("unavailable_reason_invalid", f"payload.unavailable.{field}")
    return {key: fields[key] for key in sorted(fields)}


def _timestamp(value: object, path: str) -> None:
    if _TIMESTAMP.fullmatch(_text(value, "timestamp_invalid", path)) is None:
        _fail("timestamp_invalid", path)


def _capability(value: object, path: str) -> dict[str, Any]:
    capability = _map(value, "capability_invalid", path)
    _keys(capability, {"status"}, {"details"}, path)
    if capability["status"] not in {"supported", "unsupported", "unavailable"}:
        _fail("capability_status_invalid", f"{path}.status")
    if (
        "details" in capability
        and not isinstance(capability["details"], list)
        or "details" in capability
        and any(
            not isinstance(item, str) or not item.strip()
            for item in capability["details"]
        )
    ):
        _fail("capability_details_invalid", f"{path}.details")
    return dict(capability)


def _telemetry_metrics(
    value: object, level: str, unavailable: Mapping[str, str]
) -> dict[str, Any]:
    metrics = _map(value, "telemetry_invalid", "payload.telemetry")
    _keys(metrics, set(), set(TELEMETRY_FIELDS), "payload.telemetry")
    required = TELEMETRY_REQUIRED[level]
    for field in required:
        if field not in metrics:
            _fail("required_field_missing", f"payload.telemetry.{field}")
    for field in unavailable:
        if field in metrics:
            _fail("field_present_and_unavailable", f"payload.telemetry.{field}")
    normalized = dict(metrics)
    for field, metric in metrics.items():
        if field in {"acceptance_rate", "cache_pressure_ratio"}:
            if (
                isinstance(metric, bool)
                or not isinstance(metric, (int, float))
                or not 0 <= metric <= 1
            ):
                _fail("telemetry_ratio_invalid", f"payload.telemetry.{field}")
        elif field in {"memory_used_bytes", "transfer_bytes"}:
            if isinstance(metric, bool) or not isinstance(metric, int) or metric < 0:
                _fail("telemetry_bytes_invalid", f"payload.telemetry.{field}")
        elif field == "stage_timings_ms":
            timings = _map(
                metric, "stage_timings_invalid", "payload.telemetry.stage_timings_ms"
            )
            if any(
                not isinstance(name, str)
                or not name.strip()
                or isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or duration < 0
                for name, duration in timings.items()
            ):
                _fail("stage_timings_invalid", "payload.telemetry.stage_timings_ms")
            normalized[field] = {key: timings[key] for key in sorted(timings)}
        elif (
            isinstance(metric, bool)
            or not isinstance(metric, (int, float))
            or metric < 0
        ):
            _fail("telemetry_value_invalid", f"payload.telemetry.{field}")
    return normalized


def _telemetry_payload(value: object) -> dict[str, Any]:
    payload = _map(value, "payload_invalid", "payload")
    required = {
        "sample_id",
        "observed_at",
        "level",
        "hardware",
        "capabilities",
        "execution_plan",
        "telemetry",
        "unavailable",
        "telemetry_digest",
    }
    _keys(payload, required, set(), "payload")
    _text(payload["sample_id"], "sample_id_invalid", "payload.sample_id")
    _timestamp(payload["observed_at"], "payload.observed_at")
    level = payload["level"]
    if level not in TELEMETRY_LEVELS:
        _fail("telemetry_level_invalid", "payload.level")
    unavailable = _unavailable(payload["unavailable"], TELEMETRY_UNAVAILABLE)
    if TELEMETRY_REQUIRED[level].intersection(unavailable):
        _fail("required_field_unavailable", "payload.unavailable")
    hardware = _map(payload["hardware"], "hardware_invalid", "payload.hardware")
    _keys(
        hardware,
        {"fingerprint", "device_count"},
        {"devices", "memory_total_bytes"},
        "payload.hardware",
    )
    _digest(hardware["fingerprint"], "payload.hardware.fingerprint")
    if (
        isinstance(hardware["device_count"], bool)
        or not isinstance(hardware["device_count"], int)
        or hardware["device_count"] < 1
    ):
        _fail("hardware_device_count_invalid", "payload.hardware.device_count")
    capabilities = _map(
        payload["capabilities"], "capabilities_invalid", "payload.capabilities"
    )
    _keys(
        capabilities,
        {"speculation", "placement", "kernels"},
        set(),
        "payload.capabilities",
    )
    plan = _map(
        payload["execution_plan"], "execution_plan_invalid", "payload.execution_plan"
    )
    _keys(plan, {"digest", "reason_codes"}, {"plan_id"}, "payload.execution_plan")
    _digest(plan["digest"], "payload.execution_plan.digest")
    if not isinstance(plan["reason_codes"], list) or any(
        not isinstance(item, str) or not item.strip() for item in plan["reason_codes"]
    ):
        _fail("reason_codes_invalid", "payload.execution_plan.reason_codes")
    normalized = dict(payload)
    normalized["hardware"] = dict(hardware)
    normalized["capabilities"] = {
        name: _capability(capabilities[name], f"payload.capabilities.{name}")
        for name in ("speculation", "placement", "kernels")
    }
    normalized["execution_plan"] = dict(plan)
    normalized["execution_plan"]["reason_codes"] = sorted(plan["reason_codes"])
    normalized["telemetry"] = _telemetry_metrics(
        payload["telemetry"], level, unavailable
    )
    normalized["unavailable"] = unavailable
    _digest(payload["telemetry_digest"], "payload.telemetry_digest")
    return normalized


def _decision_payload(value: object) -> dict[str, Any]:
    payload = _map(value, "payload_invalid", "payload")
    required = {
        "decision_id",
        "source_telemetry_digest",
        "speculation_policy",
        "placement_recommendation",
        "context_batch_policy",
        "confidence",
        "reason_codes",
        "invalidation_triggers",
        "unavailable",
        "decision_digest",
    }
    _keys(payload, required, {"expires_at"}, "payload")
    _text(payload["decision_id"], "decision_id_invalid", "payload.decision_id")
    _digest(payload["source_telemetry_digest"], "payload.source_telemetry_digest")
    unavailable = _unavailable(payload["unavailable"], frozenset({"expires_at"}))
    if "expires_at" in payload:
        _timestamp(payload["expires_at"], "payload.expires_at")
        if "expires_at" in unavailable:
            _fail("field_present_and_unavailable", "payload.expires_at")
    policy = _map(
        payload["speculation_policy"],
        "speculation_policy_invalid",
        "payload.speculation_policy",
    )
    _keys(policy, {"enabled", "strategy"}, set(), "payload.speculation_policy")
    if (
        not isinstance(policy["enabled"], bool)
        or policy["strategy"] not in {"disabled", "draft_verify", "tree"}
        or policy["enabled"]
        and policy["strategy"] == "disabled"
    ):
        _fail("speculation_policy_invalid", "payload.speculation_policy")
    placement = _map(
        payload["placement_recommendation"],
        "placement_recommendation_invalid",
        "payload.placement_recommendation",
    )
    _keys(
        placement, {"target", "reason_code"}, set(), "payload.placement_recommendation"
    )
    _text(
        placement["target"],
        "placement_target_invalid",
        "payload.placement_recommendation.target",
    )
    _text(
        placement["reason_code"],
        "placement_reason_invalid",
        "payload.placement_recommendation.reason_code",
    )
    batch = _map(
        payload["context_batch_policy"],
        "context_batch_policy_invalid",
        "payload.context_batch_policy",
    )
    _keys(batch, {"batch_size", "ranking"}, set(), "payload.context_batch_policy")
    if (
        isinstance(batch["batch_size"], bool)
        or not isinstance(batch["batch_size"], int)
        or batch["batch_size"] < 1
        or batch["ranking"]
        not in {"latency", "throughput", "balanced", "cache_locality"}
    ):
        _fail("context_batch_policy_invalid", "payload.context_batch_policy")
    if (
        isinstance(payload["confidence"], bool)
        or not isinstance(payload["confidence"], (int, float))
        or not 0 <= payload["confidence"] <= 1
    ):
        _fail("confidence_invalid", "payload.confidence")
    reasons = payload["reason_codes"]
    triggers = payload["invalidation_triggers"]
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item.strip() for item in reasons)
    ):
        _fail("reason_codes_invalid", "payload.reason_codes")
    if (
        not isinstance(triggers, list)
        or not triggers
        or any(item not in INVALIDATION_TRIGGERS for item in triggers)
    ):
        _fail("invalidation_triggers_invalid", "payload.invalidation_triggers")
    normalized = dict(payload)
    normalized["speculation_policy"] = dict(policy)
    normalized["placement_recommendation"] = dict(placement)
    normalized["context_batch_policy"] = dict(batch)
    normalized["reason_codes"] = sorted(reasons)
    normalized["invalidation_triggers"] = [
        item for item in INVALIDATION_TRIGGERS if item in triggers
    ]
    normalized["unavailable"] = unavailable
    _digest(payload["decision_digest"], "payload.decision_digest")
    return normalized


def _verify_digest(message: Mapping[str, Any], field: str) -> None:
    unsigned = json.loads(canonical_json(message))
    supplied = unsigned["payload"].pop(field)
    if supplied != digest_for(unsigned):
        _fail(f"{field.removesuffix('_digest')}_digest_mismatch", f"payload.{field}")


def validate_message(
    value: object, *, expected_message_type: str | None = None
) -> dict[str, Any]:
    """Validate and normalize one message; dict ordering cannot affect the result."""
    message = _map(value, "message_invalid", "message")
    _keys(
        message,
        {"schema", "contract_version", "message_type", "generation", "payload"},
        set(),
        "message",
    )
    if message["schema"] != CONTRACT_SCHEMA:
        _fail("schema_invalid", "message.schema")
    validate_contract_version(message["contract_version"])
    message_type = message["message_type"]
    if message_type not in {"telemetry_snapshot", "decision_receipt"}:
        _fail("message_type_invalid", "message.message_type")
    if expected_message_type is not None and message_type != expected_message_type:
        _fail("message_type_mismatch", "message.message_type")
    normalized = json.loads(canonical_json(message))
    normalized["generation"] = _generation(normalized["generation"])
    normalized["payload"] = (
        _telemetry_payload(normalized["payload"])
        if message_type == "telemetry_snapshot"
        else _decision_payload(normalized["payload"])
    )
    _verify_digest(
        normalized,
        "telemetry_digest"
        if message_type == "telemetry_snapshot"
        else "decision_digest",
    )
    return normalized


def validate_telemetry_snapshot(value: object) -> dict[str, Any]:
    return validate_message(value, expected_message_type="telemetry_snapshot")


def validate_decision_receipt(value: object) -> dict[str, Any]:
    return validate_message(value, expected_message_type="decision_receipt")


def invalidation_triggers(
    previous_generation: Mapping[str, Any], current_generation: Mapping[str, Any]
) -> tuple[str, ...]:
    previous = _generation(previous_generation, "previous_generation")
    current = _generation(current_generation, "current_generation")
    return tuple(
        trigger for field, trigger in DRIFT_FIELDS if previous[field] != current[field]
    )


def contract_manifest() -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "contract": CONTRACT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "version_rules": {
            "supported": "1.0",
            "major_mismatch": "reject",
            "minor_mismatch": "reject_requires_migration",
            "breaking_change": "bump_major_and_publish_migration_note",
            "additive_change": "bump_minor_and_publish_migration_note",
            "unknown_fields": "reject",
        },
        "telemetry_levels": {
            level: sorted(fields) for level, fields in TELEMETRY_REQUIRED.items()
        },
        "invalidation": {field: trigger for field, trigger in DRIFT_FIELDS},
        "field_policy": {
            "unavailable_encoding": "payload.unavailable[field_path]=stable_reason",
            "null_is_not_unavailable": True,
            "required_unavailable": "reject",
        },
        "ownership": {
            "simplicio-local": [
                "hardware",
                "capabilities",
                "telemetry",
                "execution_plan",
                "execution",
            ],
            "simplicio-fast": [
                "policy_decisions",
                "decision_receipts",
                "invalidation_triggers",
            ],
            "shared": ["versioned_envelope", "generation_binding"],
        },
    }


__all__ = [
    "CONTRACT_SCHEMA",
    "CONTRACT_VERSION",
    "INVALIDATION_TRIGGERS",
    "TELEMETRY_LEVELS",
    "ContractSurfaceError",
    "canonical_json",
    "contract_manifest",
    "digest_for",
    "invalidation_triggers",
    "validate_contract_version",
    "validate_decision_receipt",
    "validate_message",
    "validate_telemetry_snapshot",
]
