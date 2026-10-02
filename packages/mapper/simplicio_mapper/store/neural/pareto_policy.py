"""Deterministic representation selection for Fast.

This module is a decision and evidence layer only.  Simplicio Local owns model
loading, KV-cache allocation, kernels, and execution after a representation is
selected.  Missing measurements stay unknown; they are never silently treated
as zeroes or as a performance win.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

PARETO_POLICY_SCHEMA = "simplicio.fast.pareto-policy/v1"
CANDIDATE_SCHEMA = "simplicio.fast.pareto-candidate/v1"
RECEIPT_SCHEMA = "simplicio.fast.pareto-policy-receipt/v1"
INVALIDATION_SCHEMA = "simplicio.fast.pareto-policy-invalidation/v1"
POLICY_VERSION = "pareto-policy-v1"
DECISION_OWNER = "simplicio-fast"
EXECUTION_OWNER = "simplicio-local"


class ParetoPolicyError(ValueError):
    """Raised when a policy input violates the bounded selection contract."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class RepresentationKind(str, Enum):
    """Representation families that Fast may recommend to Local."""

    DENSE_QUANT = "dense_quant"
    SQTN = "sqtn"
    MIXED = "mixed"

    @classmethod
    def parse(cls, value: str | RepresentationKind) -> RepresentationKind:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ParetoPolicyError("candidate_representation_invalid")
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "dense": cls.DENSE_QUANT,
            "dense_quantized": cls.DENSE_QUANT,
            "dense_quantization": cls.DENSE_QUANT,
            "sqtn_quant": cls.SQTN,
        }
        try:
            return aliases[normalized] if normalized in aliases else cls(normalized)
        except ValueError as error:
            raise ParetoPolicyError("candidate_representation_invalid") from error


class Profile(str, Enum):
    """User-facing policy priorities."""

    QUALITY = "quality"
    BALANCED = "balanced"
    MEMORY = "memory"
    MINIMAL = "minimal"

    @classmethod
    def parse(cls, value: str | Profile) -> Profile:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as error:
            raise ParetoPolicyError("profile_invalid") from error


UserProfile = Profile
Representation = RepresentationKind


def _text(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ParetoPolicyError(reason)
    return value.strip()


def _number(value: Any, reason: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise ParetoPolicyError(reason)
    try:
        normalized = float(value)
    except (TypeError, ValueError) as error:
        raise ParetoPolicyError(reason) from error
    if not math.isfinite(normalized) or normalized < minimum:
        raise ParetoPolicyError(reason)
    return normalized


def _optional_number(value: Any, reason: str) -> float | None:
    return None if value is None else _number(value, reason)


def _integer(value: Any, reason: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ParetoPolicyError(reason)
    return value


def _optional_integer(value: Any, reason: str) -> int | None:
    return None if value is None else _integer(value, reason)


def _optional_text(value: Any, reason: str) -> str | None:
    return None if value is None else _text(value, reason)


def _coalesce(primary: Any, alias: Any, reason: str) -> Any:
    if primary is not None and alias is not None and primary != alias:
        raise ParetoPolicyError(reason)
    return primary if primary is not None else alias


def _safe_json(value: Any, reason: str = "evidence_invalid") -> Any:
    """Copy bounded JSON evidence while rejecting non-deterministic values."""

    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ParetoPolicyError(reason)
        return value
    if isinstance(value, str):
        return _text(value, reason)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[_text(key, reason)] = _safe_json(item, reason)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (tuple, list)):
        return [_safe_json(item, reason) for item in value]
    raise ParetoPolicyError(reason)


def _nested_value(value: Mapping[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = value
        for part in path:
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


@dataclass(frozen=True, slots=True, init=False)
class RepresentationCandidate:
    """One measured or reported representation option.

    The required quality value is normalized to ``0..1``.  All other metrics
    are optional so callers can report exactly which telemetry exists.  The
    constructor accepts both descriptive names (``name``/``representation``)
    and common wire aliases (``candidate_id``/``kind``, ``tok_s``/``ttft``).
    """

    name: str
    representation: RepresentationKind
    quality: float
    resident_bytes: int | None
    peak_bytes: int | None
    bytes_per_token: float | None
    kv_bytes_per_token: float | None
    tokens_per_second: float | None
    ttft_ms: float | None
    transfer_bytes: int | None
    transfer_ms: float | None
    disk_bytes: int | None
    disk_ms: float | None
    energy_joules: float | None
    available: bool
    hardware_fingerprint: str | None
    context_fingerprint: str | None
    workload_fingerprint: str | None
    evidence: Mapping[str, Any]

    def __init__(
        self,
        name: str | None = None,
        representation: str | RepresentationKind | None = None,
        quality: float | None = None,
        resident_bytes: int | None = None,
        peak_bytes: int | None = None,
        bytes_per_token: float | None = None,
        kv_bytes_per_token: float | None = None,
        tokens_per_second: float | None = None,
        ttft_ms: float | None = None,
        *,
        candidate_id: str | None = None,
        kind: str | RepresentationKind | None = None,
        bytes_token: float | None = None,
        kv_bytes_token: float | None = None,
        tok_s: float | None = None,
        ttft: float | None = None,
        transfer_bytes: int | None = None,
        transfer_ms: float | None = None,
        disk_bytes: int | None = None,
        disk_ms: float | None = None,
        energy_joules: float | None = None,
        transfer: Mapping[str, Any] | None = None,
        disk: Mapping[str, Any] | None = None,
        energy: Mapping[str, Any] | None = None,
        available: bool = True,
        hardware_fingerprint: str | None = None,
        context_fingerprint: str | None = None,
        workload_fingerprint: str | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        resolved_name = _coalesce(name, candidate_id, "candidate_identity_invalid")
        resolved_representation = _coalesce(
            representation, kind, "candidate_representation_invalid"
        )
        _text(resolved_name, "candidate_identity_invalid")
        parsed_representation = RepresentationKind.parse(resolved_representation)
        if quality is None:
            raise ParetoPolicyError("candidate_quality_invalid")
        normalized_quality = _number(quality, "candidate_quality_invalid")
        if normalized_quality > 1.0:
            raise ParetoPolicyError("candidate_quality_invalid")

        resolved_bytes_token = _coalesce(
            bytes_per_token, bytes_token, "candidate_metric_conflict"
        )
        resolved_kv_bytes_token = _coalesce(
            kv_bytes_per_token, kv_bytes_token, "candidate_metric_conflict"
        )
        resolved_tok_s = _coalesce(
            tokens_per_second, tok_s, "candidate_metric_conflict"
        )
        resolved_ttft = _coalesce(ttft_ms, ttft, "candidate_metric_conflict")

        if not isinstance(available, bool):
            raise ParetoPolicyError("candidate_availability_invalid")
        raw_evidence: dict[str, Any] = dict(evidence or {})
        for key, value in (("transfer", transfer), ("disk", disk), ("energy", energy)):
            if value is not None:
                if not isinstance(value, Mapping):
                    raise ParetoPolicyError("evidence_invalid")
                raw_evidence.setdefault(key, dict(value))
        safe_evidence = _safe_json(raw_evidence)
        assert isinstance(safe_evidence, dict)

        resolved_transfer_bytes = _coalesce(
            transfer_bytes,
            _nested_value(safe_evidence, ("transfer_bytes",), ("transfer", "bytes")),
            "candidate_metric_conflict",
        )
        resolved_transfer_ms = _coalesce(
            transfer_ms,
            _nested_value(
                safe_evidence,
                ("transfer_ms",),
                ("transfer", "milliseconds"),
                ("transfer", "ms"),
            ),
            "candidate_metric_conflict",
        )
        resolved_disk_bytes = _coalesce(
            disk_bytes,
            _nested_value(safe_evidence, ("disk_bytes",), ("disk", "bytes")),
            "candidate_metric_conflict",
        )
        resolved_disk_ms = _coalesce(
            disk_ms,
            _nested_value(
                safe_evidence,
                ("disk_ms",),
                ("disk", "milliseconds"),
                ("disk", "ms"),
            ),
            "candidate_metric_conflict",
        )
        resolved_energy = _coalesce(
            energy_joules,
            _nested_value(
                safe_evidence,
                ("energy_joules",),
                ("energy", "joules"),
                ("energy", "j"),
            ),
            "candidate_metric_conflict",
        )

        fields = {
            "resident_bytes": _optional_integer(
                resident_bytes, "candidate_resident_bytes_invalid"
            ),
            "peak_bytes": _optional_integer(peak_bytes, "candidate_peak_bytes_invalid"),
            "bytes_per_token": _optional_number(
                resolved_bytes_token, "candidate_bytes_per_token_invalid"
            ),
            "kv_bytes_per_token": _optional_number(
                resolved_kv_bytes_token, "candidate_kv_bytes_per_token_invalid"
            ),
            "tokens_per_second": _optional_number(
                resolved_tok_s, "candidate_tokens_per_second_invalid"
            ),
            "ttft_ms": _optional_number(resolved_ttft, "candidate_ttft_invalid"),
            "transfer_bytes": _optional_integer(
                resolved_transfer_bytes, "candidate_transfer_bytes_invalid"
            ),
            "transfer_ms": _optional_number(
                resolved_transfer_ms, "candidate_transfer_ms_invalid"
            ),
            "disk_bytes": _optional_integer(
                resolved_disk_bytes, "candidate_disk_bytes_invalid"
            ),
            "disk_ms": _optional_number(resolved_disk_ms, "candidate_disk_ms_invalid"),
            "energy_joules": _optional_number(
                resolved_energy, "candidate_energy_invalid"
            ),
        }
        for field, value in fields.items():
            object.__setattr__(self, field, value)
        object.__setattr__(
            self, "name", _text(resolved_name, "candidate_identity_invalid")
        )
        object.__setattr__(self, "representation", parsed_representation)
        object.__setattr__(self, "quality", normalized_quality)
        object.__setattr__(self, "available", available)
        object.__setattr__(
            self,
            "hardware_fingerprint",
            _optional_text(hardware_fingerprint, "candidate_fingerprint_invalid"),
        )
        object.__setattr__(
            self,
            "context_fingerprint",
            _optional_text(context_fingerprint, "candidate_fingerprint_invalid"),
        )
        object.__setattr__(
            self,
            "workload_fingerprint",
            _optional_text(workload_fingerprint, "candidate_fingerprint_invalid"),
        )
        object.__setattr__(self, "evidence", safe_evidence)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RepresentationCandidate:
        if not isinstance(value, Mapping):
            raise ParetoPolicyError("candidate_type_invalid")
        metrics = value.get("metrics")
        if metrics is not None and not isinstance(metrics, Mapping):
            raise ParetoPolicyError("candidate_metrics_invalid")
        merged: dict[str, Any] = dict(metrics or {})
        merged.update(value)
        return cls(
            name=merged.get("name"),
            candidate_id=merged.get("candidate_id", merged.get("id")),
            representation=merged.get("representation"),
            kind=merged.get("kind", merged.get("type")),
            quality=merged.get("quality", merged.get("quality_score")),
            resident_bytes=merged.get("resident_bytes"),
            peak_bytes=merged.get("peak_bytes"),
            bytes_per_token=merged.get("bytes_per_token"),
            bytes_token=merged.get("bytes_token"),
            kv_bytes_per_token=merged.get("kv_bytes_per_token"),
            kv_bytes_token=merged.get("kv_bytes_token"),
            tokens_per_second=merged.get("tokens_per_second"),
            tok_s=merged.get("tok_s"),
            ttft_ms=merged.get("ttft_ms"),
            ttft=merged.get("ttft"),
            transfer_bytes=merged.get("transfer_bytes"),
            transfer_ms=merged.get("transfer_ms"),
            disk_bytes=merged.get("disk_bytes"),
            disk_ms=merged.get("disk_ms"),
            energy_joules=merged.get("energy_joules"),
            available=merged.get("available", True),
            hardware_fingerprint=merged.get("hardware_fingerprint"),
            context_fingerprint=merged.get("context_fingerprint"),
            workload_fingerprint=merged.get("workload_fingerprint"),
            evidence=merged.get("evidence"),
        )

    @property
    def candidate_id(self) -> str:
        return self.name

    @property
    def kind(self) -> RepresentationKind:
        return self.representation

    @property
    def bytes_token(self) -> float | None:
        return self.bytes_per_token

    @property
    def kv_bytes_token(self) -> float | None:
        return self.kv_bytes_per_token

    @property
    def tok_s(self) -> float | None:
        return self.tokens_per_second

    @property
    def ttft(self) -> float | None:
        return self.ttft_ms

    def metrics_to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "resident_bytes": self.resident_bytes,
            "peak_bytes": self.peak_bytes,
            "bytes_per_token": self.bytes_per_token,
            "kv_bytes_per_token": self.kv_bytes_per_token,
            "tokens_per_second": self.tokens_per_second,
            "ttft_ms": self.ttft_ms,
            "transfer_bytes": self.transfer_bytes,
            "transfer_ms": self.transfer_ms,
            "disk_bytes": self.disk_bytes,
            "disk_ms": self.disk_ms,
            "energy_joules": self.energy_joules,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_SCHEMA,
            "candidate_id": self.name,
            "representation": self.representation.value,
            "metrics": self.metrics_to_dict(),
            "available": self.available,
            "fingerprints": {
                "hardware": self.hardware_fingerprint,
                "context": self.context_fingerprint,
                "workload": self.workload_fingerprint,
            },
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Generation and workload identity plus hard resource budgets."""

    generation: str
    hardware_fingerprint: str = "unknown"
    context_fingerprint: str = "unknown"
    workload_fingerprint: str = "unknown"
    resident_budget_bytes: int | None = None
    peak_budget_bytes: int | None = None
    bytes_per_token_budget: float | None = None
    kv_bytes_per_token_budget: float | None = None
    quality_threshold: float | None = None

    def __post_init__(self) -> None:
        for field in (
            "generation",
            "hardware_fingerprint",
            "context_fingerprint",
            "workload_fingerprint",
        ):
            _text(getattr(self, field), "context_identity_invalid")
        for field in ("resident_budget_bytes", "peak_budget_bytes"):
            value = getattr(self, field)
            if value is not None:
                _integer(value, "context_budget_invalid")
        for field in ("bytes_per_token_budget", "kv_bytes_per_token_budget"):
            value = getattr(self, field)
            if value is not None:
                _number(value, "context_budget_invalid")
        if self.quality_threshold is not None:
            threshold = _number(self.quality_threshold, "quality_threshold_invalid")
            if threshold > 1.0:
                raise ParetoPolicyError("quality_threshold_invalid")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyContext:
        if not isinstance(value, Mapping):
            raise ParetoPolicyError("context_type_invalid")
        budgets = value.get("budgets", {})
        if not isinstance(budgets, Mapping):
            raise ParetoPolicyError("context_budget_invalid")
        return cls(
            generation=value.get("generation"),
            hardware_fingerprint=value.get(
                "hardware_fingerprint", value.get("hardware", "unknown")
            ),
            context_fingerprint=value.get(
                "context_fingerprint", value.get("context", "unknown")
            ),
            workload_fingerprint=value.get(
                "workload_fingerprint", value.get("workload", "unknown")
            ),
            resident_budget_bytes=value.get(
                "resident_budget_bytes",
                value.get("max_resident_bytes", budgets.get("resident_bytes")),
            ),
            peak_budget_bytes=value.get(
                "peak_budget_bytes",
                value.get("max_peak_bytes", budgets.get("peak_bytes")),
            ),
            bytes_per_token_budget=value.get(
                "bytes_per_token_budget",
                value.get("max_bytes_per_token", budgets.get("bytes_per_token")),
            ),
            kv_bytes_per_token_budget=value.get(
                "kv_bytes_per_token_budget",
                value.get("max_kv_bytes_per_token", budgets.get("kv_bytes_per_token")),
            ),
            quality_threshold=value.get("quality_threshold"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "hardware_fingerprint": self.hardware_fingerprint,
            "context_fingerprint": self.context_fingerprint,
            "workload_fingerprint": self.workload_fingerprint,
            "budgets": {
                "resident_bytes": self.resident_budget_bytes,
                "peak_bytes": self.peak_budget_bytes,
                "bytes_per_token": self.bytes_per_token_budget,
                "kv_bytes_per_token": self.kv_bytes_per_token_budget,
            },
            "quality_threshold": self.quality_threshold,
        }


_MAXIMIZE = frozenset({"quality", "tokens_per_second"})
_OBJECTIVES = (
    "quality",
    "tokens_per_second",
    "ttft_ms",
    "resident_bytes",
    "peak_bytes",
    "bytes_per_token",
    "kv_bytes_per_token",
    "transfer_bytes",
    "transfer_ms",
    "disk_bytes",
    "disk_ms",
    "energy_joules",
)
_PROFILE_WEIGHTS: dict[Profile, tuple[tuple[str, float], ...]] = {
    Profile.QUALITY: (
        ("quality", 0.70),
        ("tokens_per_second", 0.15),
        ("ttft_ms", 0.10),
        ("energy_joules", 0.05),
    ),
    Profile.BALANCED: (
        ("quality", 0.35),
        ("tokens_per_second", 0.20),
        ("ttft_ms", 0.15),
        ("resident_bytes", 0.08),
        ("peak_bytes", 0.08),
        ("transfer_ms", 0.04),
        ("disk_ms", 0.04),
        ("energy_joules", 0.06),
    ),
    Profile.MEMORY: (
        ("resident_bytes", 0.30),
        ("peak_bytes", 0.30),
        ("bytes_per_token", 0.12),
        ("kv_bytes_per_token", 0.12),
        ("quality", 0.10),
        ("tokens_per_second", 0.06),
    ),
    Profile.MINIMAL: (
        ("resident_bytes", 0.25),
        ("peak_bytes", 0.25),
        ("bytes_per_token", 0.15),
        ("kv_bytes_per_token", 0.15),
        ("transfer_bytes", 0.05),
        ("disk_bytes", 0.05),
        ("energy_joules", 0.05),
        ("quality", 0.05),
    ),
}


def _candidate_metric(
    candidate: RepresentationCandidate, metric: str
) -> float | int | None:
    if metric == "quality":
        return candidate.quality
    return getattr(candidate, metric)


def _dominates(first: RepresentationCandidate, second: RepresentationCandidate) -> bool:
    comparisons: list[tuple[float | int, float | int, bool]] = []
    for metric in _OBJECTIVES:
        first_value = _candidate_metric(first, metric)
        second_value = _candidate_metric(second, metric)
        if first_value is None or second_value is None:
            continue
        comparisons.append((first_value, second_value, metric in _MAXIMIZE))
    if not comparisons:
        return False
    no_worse = all(
        first_value >= second_value if maximize else first_value <= second_value
        for first_value, second_value, maximize in comparisons
    )
    strictly_better = any(
        first_value > second_value if maximize else first_value < second_value
        for first_value, second_value, maximize in comparisons
    )
    return no_worse and strictly_better


def _benefits(
    candidates: tuple[RepresentationCandidate, ...], metric: str
) -> dict[str, float]:
    observed = {
        candidate.name: _candidate_metric(candidate, metric)
        for candidate in candidates
        if _candidate_metric(candidate, metric) is not None
    }
    if not observed:
        return {}
    values = [float(value) for value in observed.values()]
    low, high = min(values), max(values)
    if low == high:
        return {name: 1.0 for name in observed}
    if metric in _MAXIMIZE:
        return {
            name: (float(value) - low) / (high - low)
            for name, value in observed.items()
        }
    return {
        name: (high - float(value)) / (high - low) for name, value in observed.items()
    }


@dataclass(frozen=True, slots=True)
class GenerationInvalidationHook:
    """A small caller-owned hook that rejects a decision after generation drift."""

    generation: str
    decision_key: str

    def __post_init__(self) -> None:
        _text(self.generation, "generation_invalid")
        _text(self.decision_key, "decision_key_invalid")

    def check(self, current_generation: str) -> dict[str, Any]:
        _text(current_generation, "generation_invalid")
        valid = current_generation == self.generation
        return {
            "schema": INVALIDATION_SCHEMA,
            "decision_key": self.decision_key,
            "generation": self.generation,
            "current_generation": current_generation,
            "valid": valid,
            "invalidated": not valid,
            "reason": "generation_match" if valid else "generation_advanced",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": INVALIDATION_SCHEMA,
            "decision_key": self.decision_key,
            "generation": self.generation,
            "rule": "generation_exact_match",
        }

    __call__ = check


@dataclass(frozen=True, slots=True)
class ParetoReceipt:
    """Bounded, deterministic evidence for one policy decision."""

    status: str
    reason: str
    selected: str | None
    profile: Profile
    quality_threshold: float
    context: PolicyContext
    candidates: tuple[Mapping[str, Any], ...]
    pareto_frontier: tuple[str, ...]
    decision_key: str
    invalidation_hook: GenerationInvalidationHook
    decision_owner: str = DECISION_OWNER
    execution_owner: str = EXECUTION_OWNER

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "policy": PARETO_POLICY_SCHEMA,
            "policy_version": POLICY_VERSION,
            "status": self.status,
            "reason": self.reason,
            "selected": self.selected,
            "profile": self.profile.value,
            "quality_threshold": self.quality_threshold,
            "context": self.context.to_dict(),
            "candidates": [dict(candidate) for candidate in self.candidates],
            "pareto_frontier": list(self.pareto_frontier),
            "decision_key": self.decision_key,
            "invalidation_hook": self.invalidation_hook.to_dict(),
            "decision_owner": self.decision_owner,
            "execution_owner": self.execution_owner,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ParetoDecision:
    """Selection result; ``selected`` is data, never an executable object."""

    selected: RepresentationCandidate | None
    status: str
    reason: str
    receipt: ParetoReceipt

    @property
    def selected_candidate(self) -> RepresentationCandidate | None:
        return self.selected

    @property
    def selected_id(self) -> str | None:
        return None if self.selected is None else self.selected.name

    def is_valid_for_generation(self, generation: str) -> bool:
        return bool(self.receipt.invalidation_hook.check(generation)["valid"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PARETO_POLICY_SCHEMA,
            "status": self.status,
            "reason": self.reason,
            "selected": None if self.selected is None else self.selected.to_dict(),
            "execution_plan": None
            if self.selected is None
            else {
                "candidate_id": self.selected.name,
                "representation": self.selected.representation.value,
                "owner": self.receipt.execution_owner,
            },
            "receipt": self.receipt.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _coerce_candidate(
    value: RepresentationCandidate | Mapping[str, Any],
) -> RepresentationCandidate:
    if isinstance(value, RepresentationCandidate):
        return value
    if isinstance(value, Mapping):
        return RepresentationCandidate.from_mapping(value)
    raise ParetoPolicyError("candidate_type_invalid")


def _hard_filters(
    candidate: RepresentationCandidate,
    context: PolicyContext,
    quality_threshold: float,
) -> tuple[dict[str, bool], str | None]:
    filters: dict[str, bool] = {
        "quality_threshold": candidate.quality >= quality_threshold,
        "available": candidate.available,
    }
    reason: str | None = None
    if not filters["quality_threshold"]:
        reason = "quality_below_threshold"
    elif not filters["available"]:
        reason = "candidate_unavailable"

    for label, candidate_value, budget in (
        ("resident_budget", candidate.resident_bytes, context.resident_budget_bytes),
        ("peak_budget", candidate.peak_bytes, context.peak_budget_bytes),
        (
            "bytes_per_token_budget",
            candidate.bytes_per_token,
            context.bytes_per_token_budget,
        ),
        (
            "kv_bytes_per_token_budget",
            candidate.kv_bytes_per_token,
            context.kv_bytes_per_token_budget,
        ),
    ):
        passes = (
            budget is None or candidate_value is not None and candidate_value <= budget
        )
        filters[label] = passes
        if not passes and reason is None:
            reason = (
                f"{label}_unknown" if candidate_value is None else f"{label}_exceeded"
            )

    for label, candidate_value, context_value in (
        (
            "hardware_fingerprint",
            candidate.hardware_fingerprint,
            context.hardware_fingerprint,
        ),
        (
            "context_fingerprint",
            candidate.context_fingerprint,
            context.context_fingerprint,
        ),
        (
            "workload_fingerprint",
            candidate.workload_fingerprint,
            context.workload_fingerprint,
        ),
    ):
        passes = (
            candidate_value is None
            or context_value == "unknown"
            or candidate_value == context_value
        )
        filters[label] = passes
        if not passes and reason is None:
            reason = f"{label}_mismatch"
    return filters, reason


class ParetoPolicy:
    """Select one eligible representation without executing it."""

    def __init__(
        self,
        profile: str | Profile = Profile.BALANCED,
        quality_threshold: float = 0.0,
    ) -> None:
        self._profile = Profile.parse(profile)
        self._quality_threshold = _number(
            quality_threshold, "quality_threshold_invalid"
        )
        if self._quality_threshold > 1.0:
            raise ParetoPolicyError("quality_threshold_invalid")

    @property
    def profile(self) -> Profile:
        return self._profile

    @property
    def quality_threshold(self) -> float:
        return self._quality_threshold

    def decide(
        self,
        candidates: Iterable[RepresentationCandidate | Mapping[str, Any]],
        context: PolicyContext | Mapping[str, Any] | None = None,
        *,
        quality_threshold: float | None = None,
        generation: str | None = None,
        hardware_fingerprint: str | None = None,
        context_fingerprint: str | None = None,
        workload_fingerprint: str | None = None,
        resident_budget_bytes: int | None = None,
        peak_budget_bytes: int | None = None,
        bytes_per_token_budget: float | None = None,
        kv_bytes_per_token_budget: float | None = None,
        memory_budget_bytes: int | None = None,
        max_resident_bytes: int | None = None,
        max_peak_bytes: int | None = None,
        max_bytes_per_token: float | None = None,
        max_kv_bytes_per_token: float | None = None,
    ) -> ParetoDecision:
        resolved_context = self._context(
            context,
            quality_threshold=quality_threshold,
            generation=generation,
            hardware_fingerprint=hardware_fingerprint,
            context_fingerprint=context_fingerprint,
            workload_fingerprint=workload_fingerprint,
            resident_budget_bytes=resident_budget_bytes,
            peak_budget_bytes=peak_budget_bytes,
            bytes_per_token_budget=bytes_per_token_budget,
            kv_bytes_per_token_budget=kv_bytes_per_token_budget,
            memory_budget_bytes=memory_budget_bytes,
            max_resident_bytes=max_resident_bytes,
            max_peak_bytes=max_peak_bytes,
            max_bytes_per_token=max_bytes_per_token,
            max_kv_bytes_per_token=max_kv_bytes_per_token,
        )
        threshold = (
            resolved_context.quality_threshold
            if resolved_context.quality_threshold is not None
            else self._quality_threshold
        )
        raw_candidates = list(candidates)
        normalized = tuple(
            sorted(
                (_coerce_candidate(item) for item in raw_candidates),
                key=lambda item: (item.name, item.representation.value),
            )
        )
        names = [candidate.name for candidate in normalized]
        if len(names) != len(set(names)):
            raise ParetoPolicyError("candidate_identity_duplicate")
        candidate_digest = _digest([candidate.to_dict() for candidate in normalized])
        decision_key = _digest(
            {
                "policy": POLICY_VERSION,
                "profile": self._profile.value,
                "quality_threshold": threshold,
                "context": resolved_context.to_dict(),
                "candidate_digest": candidate_digest,
            }
        )
        hook = GenerationInvalidationHook(resolved_context.generation, decision_key)

        facts: list[dict[str, Any]] = []
        eligible: list[RepresentationCandidate] = []
        for candidate in normalized:
            filters, rejection = _hard_filters(candidate, resolved_context, threshold)
            is_eligible = all(filters.values())
            if is_eligible:
                eligible.append(candidate)
            facts.append(
                {
                    "schema": "simplicio.fast.pareto-candidate-fact/v1",
                    "candidate_id": candidate.name,
                    "representation": candidate.representation.value,
                    "metrics": candidate.metrics_to_dict(),
                    "evidence": dict(candidate.evidence),
                    "fingerprints": {
                        "hardware": candidate.hardware_fingerprint,
                        "context": candidate.context_fingerprint,
                        "workload": candidate.workload_fingerprint,
                    },
                    "hard_filters": filters,
                    "eligible": is_eligible,
                    "selection_reason": rejection or "eligible_pending_pareto",
                    "pareto_dominated_by": [],
                }
            )

        eligible_tuple = tuple(eligible)
        frontier = tuple(
            candidate
            for candidate in eligible_tuple
            if not any(
                other is not candidate and _dominates(other, candidate)
                for other in eligible_tuple
            )
        )
        frontier = tuple(
            sorted(frontier, key=lambda item: (item.name, item.representation.value))
        )
        benefits = {
            metric: _benefits(frontier, metric)
            for metric, _ in _PROFILE_WEIGHTS[self._profile]
        }
        scores: dict[str, tuple[float, dict[str, float]]] = {}
        for candidate in frontier:
            components: dict[str, float] = {}
            weighted_total = 0.0
            available_weight = 0.0
            for metric, weight in _PROFILE_WEIGHTS[self._profile]:
                benefit = benefits[metric].get(candidate.name)
                if benefit is None:
                    continue
                components[metric] = benefit
                weighted_total += benefit * weight
                available_weight += weight
            scores[candidate.name] = (
                weighted_total / available_weight if available_weight else 0.0,
                components,
            )

        def tie_key(candidate: RepresentationCandidate) -> tuple[Any, ...]:
            return (
                -candidate.quality,
                -(candidate.tokens_per_second or 0.0),
                candidate.ttft_ms if candidate.ttft_ms is not None else math.inf,
                candidate.resident_bytes
                if candidate.resident_bytes is not None
                else math.inf,
                candidate.peak_bytes if candidate.peak_bytes is not None else math.inf,
                candidate.name,
                candidate.representation.value,
            )

        selected = (
            min(
                frontier,
                key=lambda item: (-scores[item.name][0], tie_key(item)),
            )
            if frontier
            else None
        )

        dominated_by: dict[str, list[str]] = {
            candidate.name: sorted(
                other.name
                for other in eligible_tuple
                if other is not candidate and _dominates(other, candidate)
            )
            for candidate in eligible_tuple
        }
        for fact in facts:
            candidate_name = fact["candidate_id"]
            if candidate_name in dominated_by:
                if dominated_by[candidate_name]:
                    fact["selection_reason"] = "pareto_dominated"
                    fact["pareto_dominated_by"] = dominated_by[candidate_name]
                else:
                    fact["selection_reason"] = "pareto_frontier"
                    fact["profile_score"] = scores[candidate_name][0]
                    fact["score_components"] = scores[candidate_name][1]
            if selected is not None and candidate_name == selected.name:
                fact["selection_reason"] = "selected_by_profile"

        if selected is not None:
            status = "selected"
            reason = "selected_pareto_frontier"
        else:
            status = "cannot_fit"
            if not normalized:
                reason = "no_candidates"
            elif not any(candidate.quality >= threshold for candidate in normalized):
                reason = "quality_threshold_unmet"
            elif any(
                fact["eligible"] is False
                and fact["selection_reason"] == "candidate_unavailable"
                for fact in facts
            ):
                reason = "no_available_candidate_fits"
            else:
                reason = "no_candidate_fits_constraints"

        receipt = ParetoReceipt(
            status=status,
            reason=reason,
            selected=None if selected is None else selected.name,
            profile=self._profile,
            quality_threshold=threshold,
            context=resolved_context,
            candidates=tuple(facts),
            pareto_frontier=tuple(candidate.name for candidate in frontier),
            decision_key=decision_key,
            invalidation_hook=hook,
        )
        return ParetoDecision(selected, status, reason, receipt)

    def _context(
        self,
        context: PolicyContext | Mapping[str, Any] | None,
        **overrides: Any,
    ) -> PolicyContext:
        if context is None:
            values: dict[str, Any] = {"generation": overrides.pop("generation", None)}
        elif isinstance(context, PolicyContext):
            values = context.to_dict()
            budgets = values.pop("budgets")
            values.update(
                {
                    "resident_budget_bytes": budgets["resident_bytes"],
                    "peak_budget_bytes": budgets["peak_bytes"],
                    "bytes_per_token_budget": budgets["bytes_per_token"],
                    "kv_bytes_per_token_budget": budgets["kv_bytes_per_token"],
                }
            )
        elif isinstance(context, Mapping):
            values = dict(context)
        else:
            raise ParetoPolicyError("context_type_invalid")

        memory_budget = overrides.pop("memory_budget_bytes", None)
        aliases = {
            "max_resident_bytes": "resident_budget_bytes",
            "max_peak_bytes": "peak_budget_bytes",
            "max_bytes_per_token": "bytes_per_token_budget",
            "max_kv_bytes_per_token": "kv_bytes_per_token_budget",
        }
        for alias, target in aliases.items():
            if overrides.get(target) is None and overrides.get(alias) is not None:
                overrides[target] = overrides[alias]
        if memory_budget is not None:
            if overrides.get("resident_budget_bytes") is None:
                overrides["resident_budget_bytes"] = memory_budget
            if overrides.get("peak_budget_bytes") is None:
                overrides["peak_budget_bytes"] = memory_budget
        for key, value in overrides.items():
            if key in aliases or value is None:
                continue
            values[key] = value
        if values.get("generation") is None:
            raise ParetoPolicyError("generation_required")
        return PolicyContext.from_mapping(values)

    @staticmethod
    def invalidation_hook(
        generation: str, decision_key: str
    ) -> GenerationInvalidationHook:
        return GenerationInvalidationHook(generation, decision_key)


def invalidate_on_generation_change(
    generation: str,
    current_generation: str,
    *,
    decision_key: str = "unbound",
) -> dict[str, Any]:
    """Return a truthful reuse/invalidation receipt for a generation change."""

    return GenerationInvalidationHook(generation, decision_key).check(
        current_generation
    )


def select_representation(
    candidates: Iterable[RepresentationCandidate | Mapping[str, Any]],
    *,
    profile: str | Profile = Profile.BALANCED,
    quality_threshold: float = 0.0,
    context: PolicyContext | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> ParetoDecision:
    """Convenience wrapper for the stateless policy decision."""

    return ParetoPolicy(profile, quality_threshold).decide(
        candidates,
        context,
        quality_threshold=quality_threshold,
        **kwargs,
    )


decide_pareto = select_representation


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CANDIDATE_SCHEMA",
    "DECISION_OWNER",
    "EXECUTION_OWNER",
    "INVALIDATION_SCHEMA",
    "PARETO_POLICY_SCHEMA",
    "POLICY_VERSION",
    "RECEIPT_SCHEMA",
    "GenerationInvalidationHook",
    "ParetoDecision",
    "ParetoPolicy",
    "ParetoPolicyError",
    "ParetoReceipt",
    "PolicyContext",
    "Profile",
    "Representation",
    "RepresentationCandidate",
    "RepresentationKind",
    "UserProfile",
    "decide_pareto",
    "invalidate_on_generation_change",
    "select_representation",
]
