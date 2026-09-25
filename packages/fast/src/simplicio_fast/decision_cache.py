"""Bounded, generation-bound cache for reusable Fast decisions.

The cache stores only compact, classified decision data.  Source prompts, code,
user content, and other unbounded text are rejected at the boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any

KEY_SCHEMA = "simplicio.fast.decision-cache-key/v1"
CACHE_SCHEMA = "simplicio.fast.decision-cache/v1"
RECEIPT_SCHEMA = "simplicio.fast.decision-cache-receipt/v1"
DEFAULT_MAX_ENTRIES = 128
MAX_ENTRIES = 4096


class DecisionCacheError(ValueError):
    """Raised when a cache key or decision payload cannot be accepted safely."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class InvalidationReason:
    """Stable reason codes used in invalidation and quarantine receipts."""

    ENTRY_MISSING = "entry_missing"
    GENERATION_MISMATCH = "generation_mismatch"
    GENERATION_ADVANCED = "generation_advanced"
    MODEL_DRIFT = "model_drift"
    ARTIFACT_DRIFT = "artifact_drift"
    QUANTIZATION_DRIFT = "quantization_drift"
    TOKENIZER_DRIFT = "tokenizer_template_drift"
    BACKEND_DRIFT = "backend_drift"
    HARDWARE_DRIFT = "hardware_drift"
    PLACEMENT_DRIFT = "placement_drift"
    CONTEXT_PRESSURE_DRIFT = "context_kv_pressure_drift"
    WORKLOAD_DRIFT = "workload_drift"
    CONCURRENCY_DRIFT = "concurrency_drift"
    POLICY_VERSION_DRIFT = "policy_version_drift"
    OBSERVED_TELEMETRY_CONTRADICTION = "observed_telemetry_contradiction"
    REGRESSION_DETECTED = "regression_detected"
    CAPACITY_EVICTION = "capacity_eviction"
    MANUAL_INVALIDATION = "manual_invalidation"


_KEY_DIMENSIONS = (
    "model_digest",
    "artifact_digest",
    "quant_digest",
    "tokenizer_template_identity",
    "backend_version",
    "hardware_topology_fingerprint",
    "device_placement_class",
    "context_kv_pressure_bucket",
    "workload_class",
    "concurrency_bucket",
    "fast_policy_version",
    "generation",
)
_DRIFT_REASONS = {
    "model_digest": InvalidationReason.MODEL_DRIFT,
    "artifact_digest": InvalidationReason.ARTIFACT_DRIFT,
    "quant_digest": InvalidationReason.QUANTIZATION_DRIFT,
    "tokenizer_template_identity": InvalidationReason.TOKENIZER_DRIFT,
    "backend_version": InvalidationReason.BACKEND_DRIFT,
    "hardware_topology_fingerprint": InvalidationReason.HARDWARE_DRIFT,
    "device_placement_class": InvalidationReason.PLACEMENT_DRIFT,
    "context_kv_pressure_bucket": InvalidationReason.CONTEXT_PRESSURE_DRIFT,
    "workload_class": InvalidationReason.WORKLOAD_DRIFT,
    "concurrency_bucket": InvalidationReason.CONCURRENCY_DRIFT,
    "fast_policy_version": InvalidationReason.POLICY_VERSION_DRIFT,
}
_FORBIDDEN_PAYLOAD_MARKERS = ("prompt", "code", "user", "content", "source")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DecisionCacheError("payload_not_json") from error


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _validate_identifier(value: object, reason: str = "key_dimension_invalid") -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DecisionCacheError(reason)
    if len(value) > 256 or any(character.isspace() for character in value):
        raise DecisionCacheError("raw_content_forbidden")
    if "\0" in value:
        raise DecisionCacheError(reason)
    return value


def _validate_reason(reason: object) -> str:
    if not isinstance(reason, str) or not reason or reason != reason.strip():
        raise DecisionCacheError("invalidation_reason_invalid")
    try:
        return _validate_identifier(reason, "invalidation_reason_invalid")
    except DecisionCacheError as error:
        raise DecisionCacheError("invalidation_reason_invalid") from error


def _validate_safe_payload(value: Any) -> Any:
    """Return a JSON-safe copy while rejecting likely raw-content fields."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DecisionCacheError("payload_not_json")
        return value
    if isinstance(value, str):
        return _validate_identifier(value, "payload_invalid")
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise DecisionCacheError("payload_invalid")
            lowered = key.lower()
            if any(marker in lowered for marker in _FORBIDDEN_PAYLOAD_MARKERS):
                raise DecisionCacheError("raw_content_forbidden")
            normalized[key] = _validate_safe_payload(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_validate_safe_payload(item) for item in value]
    raise DecisionCacheError("payload_invalid")


@dataclass(frozen=True, slots=True)
class DecisionCacheKey:
    """Minimum classified dimensions needed to safely reuse a decision."""

    model_digest: str
    artifact_digest: str
    quant_digest: str
    backend_version: str
    hardware_topology_fingerprint: str
    device_placement_class: str
    context_kv_pressure_bucket: str
    workload_class: str
    concurrency_bucket: str
    fast_policy_version: str
    generation: str
    tokenizer_template_identity: str | None = None

    def __post_init__(self) -> None:
        for name in _KEY_DIMENSIONS:
            value = getattr(self, name)
            if name == "tokenizer_template_identity" and value is None:
                continue
            _validate_identifier(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": KEY_SCHEMA,
            "model_digest": self.model_digest,
            "artifact_digest": self.artifact_digest,
            "quant_digest": self.quant_digest,
            "tokenizer_template_identity": self.tokenizer_template_identity,
            "backend_version": self.backend_version,
            "hardware_topology_fingerprint": self.hardware_topology_fingerprint,
            "device_placement_class": self.device_placement_class,
            "context_kv_pressure_bucket": self.context_kv_pressure_bucket,
            "workload_class": self.workload_class,
            "concurrency_bucket": self.concurrency_bucket,
            "fast_policy_version": self.fast_policy_version,
            "generation": self.generation,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class DecisionCacheEntry:
    """A validated decision and its compact expected telemetry."""

    key: DecisionCacheKey
    decision: Mapping[str, Any]
    expectation: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.to_dict(),
            "key_digest": self.key.digest,
            "decision": deepcopy(dict(self.decision)),
            "expectation": deepcopy(dict(self.expectation)),
        }


class DecisionCache:
    """Thread-safe bounded LRU cache whose entries belong to one generation."""

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        *,
        generation: str | None = None,
    ) -> None:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or not 1 <= max_entries <= MAX_ENTRIES
        ):
            raise DecisionCacheError("cache_capacity_invalid")
        if generation is not None:
            generation = _validate_identifier(generation)
        self.max_entries = max_entries
        self._active_generation = generation
        self._entries: OrderedDict[str, DecisionCacheEntry] = OrderedDict()
        self._invalidations: OrderedDict[str, str] = OrderedDict()
        self._quarantined: OrderedDict[str, str] = OrderedDict()
        self._disabled: OrderedDict[str, str] = OrderedDict()
        self._metrics = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
            "invalidations": 0,
            "quarantines": 0,
            "disabled": 0,
            "evictions": 0,
        }
        self._lock = RLock()

    @property
    def generation(self) -> str | None:
        with self._lock:
            return self._active_generation

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _remember(
        self,
        store: OrderedDict[str, str],
        key_digest: str,
        reason: str,
    ) -> None:
        store.pop(key_digest, None)
        store[key_digest] = reason
        while len(store) > self.max_entries:
            store.popitem(last=False)

    def _clear_generation_locked(self, generation: str) -> list[str]:
        invalidated = sorted(self._entries)
        for key_digest in invalidated:
            self._remember(
                self._invalidations,
                key_digest,
                InvalidationReason.GENERATION_ADVANCED,
            )
        self._entries.clear()
        self._quarantined.clear()
        self._disabled.clear()
        self._active_generation = generation
        self._metrics["invalidations"] += len(invalidated)
        return invalidated

    def _receipt(
        self,
        *,
        operation: str,
        outcome: str,
        reason: str,
        key: DecisionCacheKey | None = None,
        invalidated_key_digests: Sequence[str] = (),
        evicted_key_digests: Sequence[str] = (),
        contradiction_fields: Sequence[str] = (),
        decision: Mapping[str, Any] | None = None,
        removed: bool | None = None,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "operation": operation,
            "outcome": outcome,
            "reason": reason,
        }
        if key is not None:
            receipt["key_digest"] = key.digest
            receipt["generation"] = key.generation
        elif self._active_generation is not None:
            receipt["generation"] = self._active_generation
        if decision is not None:
            receipt["decision"] = deepcopy(dict(decision))
        if removed is not None:
            receipt["removed"] = removed
        if invalidated_key_digests:
            receipt["invalidated_key_digests"] = sorted(invalidated_key_digests)
        if evicted_key_digests:
            receipt["evicted_key_digests"] = sorted(evicted_key_digests)
        if contradiction_fields:
            receipt["contradiction_fields"] = sorted(contradiction_fields)
        return receipt

    def activate_generation(self, generation: str) -> dict[str, Any]:
        """Switch generations and explicitly invalidate all older entries."""

        generation = _validate_identifier(generation)
        with self._lock:
            previous = self._active_generation
            if previous == generation:
                return self._receipt(
                    operation="activate_generation",
                    outcome="unchanged",
                    reason="generation_unchanged",
                )
            invalidated = self._clear_generation_locked(generation)
            return self._receipt(
                operation="activate_generation",
                outcome="activated",
                reason=(
                    "generation_initialized"
                    if previous is None
                    else InvalidationReason.GENERATION_ADVANCED
                ),
                invalidated_key_digests=invalidated,
            )

    def put(
        self,
        key: DecisionCacheKey,
        decision: Mapping[str, Any],
        *,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a compact decision and return a deterministic store receipt."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("cache_key_invalid")
        safe_decision = _validate_safe_payload(decision)
        safe_expected = _validate_safe_payload({} if expected is None else expected)
        if not isinstance(safe_decision, dict) or not isinstance(safe_expected, dict):
            raise DecisionCacheError("payload_invalid")
        with self._lock:
            generation_reason = "generation_current"
            invalidated: list[str] = []
            if self._active_generation is None:
                self._active_generation = key.generation
                generation_reason = "generation_initialized"
            elif self._active_generation != key.generation:
                invalidated = self._clear_generation_locked(key.generation)
                generation_reason = InvalidationReason.GENERATION_ADVANCED

            key_digest = key.digest
            if key_digest in self._disabled:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="put",
                    outcome="disabled",
                    reason=self._disabled[key_digest],
                    key=key,
                    invalidated_key_digests=invalidated,
                )
            if key_digest in self._quarantined:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="put",
                    outcome="quarantined",
                    reason=self._quarantined[key_digest],
                    key=key,
                    invalidated_key_digests=invalidated,
                )

            replacing = key_digest in self._entries
            self._entries.pop(key_digest, None)
            self._entries[key_digest] = DecisionCacheEntry(
                key, safe_decision, safe_expected
            )
            self._invalidations.pop(key_digest, None)
            self._metrics["stores"] += 1
            evicted: list[str] = []
            while len(self._entries) > self.max_entries:
                evicted_digest, _ = self._entries.popitem(last=False)
                evicted.append(evicted_digest)
                self._remember(
                    self._invalidations,
                    evicted_digest,
                    InvalidationReason.CAPACITY_EVICTION,
                )
            self._metrics["evictions"] += len(evicted)
            reason = generation_reason
            if generation_reason == "generation_current":
                reason = "entry_replaced" if replacing else "stored"
            return self._receipt(
                operation="put",
                outcome="stored",
                reason=reason,
                key=key,
                invalidated_key_digests=invalidated,
                evicted_key_digests=evicted,
            )

    def lookup(
        self,
        key: DecisionCacheKey,
        *,
        observed: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Look up a decision without ever silently applying stale state."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("cache_key_invalid")
        safe_observed = _validate_safe_payload({} if observed is None else observed)
        if not isinstance(safe_observed, dict):
            raise DecisionCacheError("payload_invalid")
        with self._lock:
            if self._active_generation is None:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="lookup",
                    outcome="miss",
                    reason="generation_uninitialized",
                    key=key,
                )
            if key.generation != self._active_generation:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="lookup",
                    outcome="miss",
                    reason=InvalidationReason.GENERATION_MISMATCH,
                    key=key,
                )

            key_digest = key.digest
            if key_digest in self._disabled:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="lookup",
                    outcome="disabled",
                    reason=self._disabled[key_digest],
                    key=key,
                )
            if key_digest in self._quarantined:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="lookup",
                    outcome="quarantined",
                    reason=self._quarantined[key_digest],
                    key=key,
                )
            if key_digest not in self._entries:
                self._metrics["misses"] += 1
                return self._receipt(
                    operation="lookup",
                    outcome="invalidated"
                    if key_digest in self._invalidations
                    else "miss",
                    reason=self._invalidations.get(
                        key_digest, InvalidationReason.ENTRY_MISSING
                    ),
                    key=key,
                )

            entry = self._entries[key_digest]
            contradiction_fields = sorted(
                field
                for field, expected_value in entry.expectation.items()
                if field in safe_observed and safe_observed[field] != expected_value
            )
            if contradiction_fields:
                self._entries.pop(key_digest, None)
                self._remember(
                    self._quarantined,
                    key_digest,
                    InvalidationReason.OBSERVED_TELEMETRY_CONTRADICTION,
                )
                self._metrics["invalidations"] += 1
                self._metrics["quarantines"] += 1
                return self._receipt(
                    operation="lookup",
                    outcome="quarantined",
                    reason=InvalidationReason.OBSERVED_TELEMETRY_CONTRADICTION,
                    key=key,
                    contradiction_fields=contradiction_fields,
                    removed=True,
                )

            self._entries.move_to_end(key_digest)
            self._metrics["hits"] += 1
            return self._receipt(
                operation="lookup",
                outcome="hit",
                reason="cache_hit",
                key=key,
                decision=entry.decision,
            )

    def invalidate(self, key: DecisionCacheKey, *, reason: str) -> dict[str, Any]:
        """Remove one entry and retain the explicit reason for the next lookup."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("cache_key_invalid")
        reason = _validate_reason(reason)
        with self._lock:
            key_digest = key.digest
            removed = self._entries.pop(key_digest, None) is not None
            self._remember(self._invalidations, key_digest, reason)
            if removed:
                self._metrics["invalidations"] += 1
            return self._receipt(
                operation="invalidate",
                outcome="invalidated" if removed else "miss",
                reason=reason,
                key=key,
                removed=removed,
            )

    def invalidate_drift(
        self,
        key: DecisionCacheKey,
        *,
        dimensions: Sequence[str],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Invalidate entries matching all stable dimensions except listed drift."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("cache_key_invalid")
        if not isinstance(dimensions, (tuple, list)) or not dimensions:
            raise DecisionCacheError("drift_dimensions_invalid")
        drift_dimensions = tuple(dimensions)
        if any(dimension not in _DRIFT_REASONS for dimension in drift_dimensions):
            raise DecisionCacheError("drift_dimensions_invalid")
        if len(set(drift_dimensions)) != len(drift_dimensions):
            raise DecisionCacheError("drift_dimensions_invalid")
        reason = _validate_reason(
            reason if reason is not None else _DRIFT_REASONS[drift_dimensions[0]]
        )
        requested = key.to_dict()
        with self._lock:
            invalidated: list[str] = []
            for key_digest, entry in list(self._entries.items()):
                candidate = entry.key.to_dict()
                if candidate["generation"] != requested["generation"]:
                    continue
                stable_dimensions = set(_DRIFT_REASONS).difference(drift_dimensions)
                if not all(
                    candidate[dimension] == requested[dimension]
                    for dimension in stable_dimensions
                ):
                    continue
                if not any(
                    candidate[dimension] != requested[dimension]
                    for dimension in drift_dimensions
                ):
                    continue
                self._entries.pop(key_digest, None)
                self._remember(self._invalidations, key_digest, reason)
                invalidated.append(key_digest)
            invalidated.sort()
            self._metrics["invalidations"] += len(invalidated)
            return self._receipt(
                operation="invalidate_drift",
                outcome="invalidated" if invalidated else "miss",
                reason=reason,
                key=key,
                invalidated_key_digests=invalidated,
            )

    def quarantine(self, key: DecisionCacheKey, *, reason: str) -> dict[str, Any]:
        """Remove an entry and block reuse until the generation changes."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("cache_key_invalid")
        reason = _validate_reason(reason)
        with self._lock:
            key_digest = key.digest
            removed = self._entries.pop(key_digest, None) is not None
            self._remember(self._quarantined, key_digest, reason)
            self._metrics["quarantines"] += 1
            if removed:
                self._metrics["invalidations"] += 1
            return self._receipt(
                operation="quarantine",
                outcome="quarantined",
                reason=reason,
                key=key,
                removed=removed,
            )

    def disable_for_regression(
        self,
        key: DecisionCacheKey,
        *,
        reason: str = InvalidationReason.REGRESSION_DETECTED,
    ) -> dict[str, Any]:
        """Disable one decision immediately after a measured regression."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("cache_key_invalid")
        reason = _validate_reason(reason)
        with self._lock:
            key_digest = key.digest
            removed = self._entries.pop(key_digest, None) is not None
            self._remember(self._disabled, key_digest, reason)
            self._metrics["disabled"] += 1
            if removed:
                self._metrics["invalidations"] += 1
            return self._receipt(
                operation="disable",
                outcome="disabled",
                reason=reason,
                key=key,
                removed=removed,
            )

    def receipt(self) -> dict[str, Any]:
        """Return deterministic bounded state and counters without cached payloads."""

        with self._lock:
            return {
                "schema": RECEIPT_SCHEMA,
                "operation": "state",
                "outcome": "summary",
                "generation": self._active_generation,
                "capacity": self.max_entries,
                "size": len(self._entries),
                "key_digests": sorted(self._entries),
                "quarantined": [
                    {"key_digest": key_digest, "reason": reason}
                    for key_digest, reason in sorted(self._quarantined.items())
                ],
                "disabled": [
                    {"key_digest": key_digest, "reason": reason}
                    for key_digest, reason in sorted(self._disabled.items())
                ],
                "metrics": dict(sorted(self._metrics.items())),
            }

    def snapshot(self) -> dict[str, Any]:
        """Return a versioned, content-safe representation for a caller to persist."""

        with self._lock:
            return {
                "schema": CACHE_SCHEMA,
                "generation": self._active_generation,
                "capacity": self.max_entries,
                "entries": [
                    self._entries[key_digest].to_dict()
                    for key_digest in sorted(self._entries)
                ],
                "quarantined": [
                    {"key_digest": key_digest, "reason": reason}
                    for key_digest, reason in sorted(self._quarantined.items())
                ],
                "disabled": [
                    {"key_digest": key_digest, "reason": reason}
                    for key_digest, reason in sorted(self._disabled.items())
                ],
            }


__all__ = [
    "CACHE_SCHEMA",
    "DEFAULT_MAX_ENTRIES",
    "KEY_SCHEMA",
    "MAX_ENTRIES",
    "RECEIPT_SCHEMA",
    "DecisionCache",
    "DecisionCacheEntry",
    "DecisionCacheError",
    "DecisionCacheKey",
    "InvalidationReason",
]
