"""Typed pressure inputs for the speculative-decoding policy boundary.

This module only validates and scores telemetry receipts.  It does not sample
hardware, own a cache, or execute an inference backend.  A Local profiler can
wrap its observations in :class:`PressureMetric` and hand them to Fast.

Missing metrics stay missing: scoring excludes them from the weighted average,
reports their status, and lowers telemetry coverage.  The scorer never uses a
synthetic zero for an unavailable metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Generic, TypeVar

SCHEMA = "simplicio.fast.pressure-inputs/v1"
MAX_PRESSURE = 1.0


class PressureInputError(ValueError):
    """Raised when a pressure receipt cannot be represented safely."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class MetricState(str, Enum):
    """Availability state carried by a Local telemetry receipt."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    CONTRADICTORY = "contradictory"


class Placement(str, Enum):
    """Placement choices owned by the inference executor."""

    SAME_GPU = "same_gpu"
    CPU_DRAFT = "cpu_draft"
    UNIFIED = "unified"


class Recommendation(str, Enum):
    """Safe policy boundary recommendation."""

    BASELINE = "baseline"
    SPECULATIVE = "speculative"


T = TypeVar("T")


def _finite_fraction(value: float, reason_code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PressureInputError(reason_code)
    value = float(value)
    if not isfinite(value) or not 0.0 <= value <= MAX_PRESSURE:
        raise PressureInputError(reason_code)
    return value


def _non_negative_number(value: float, reason_code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PressureInputError(reason_code)
    value = float(value)
    if not isfinite(value) or value < 0.0:
        raise PressureInputError(reason_code)
    return value


def _optional_non_negative_number(
    value: float | None, reason_code: str
) -> float | None:
    if value is None:
        return None
    return _non_negative_number(value, reason_code)


def _optional_non_negative_int(value: int | None, reason_code: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PressureInputError(reason_code)
    return value


@dataclass(frozen=True, slots=True)
class PressureMetric(Generic[T]):
    """A typed receipt value with capability and confidence semantics.

    ``capabilities=None`` on :class:`PressureInputs` trusts the receipt's own
    capability gate.  Passing a capability set applies an additional gate and
    lets a policy caller fail closed when a backend capability is not enabled.
    """

    value: T | None
    state: MetricState
    confidence: float
    capability: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, MetricState):
            raise PressureInputError("METRIC_STATE_INVALID")
        if not isinstance(self.capability, str) or not self.capability.strip():
            raise PressureInputError("METRIC_CAPABILITY_INVALID")
        object.__setattr__(
            self,
            "confidence",
            _finite_fraction(self.confidence, "METRIC_CONFIDENCE_INVALID"),
        )
        if self.state is MetricState.AVAILABLE and self.value is None:
            raise PressureInputError("METRIC_VALUE_MISSING")
        if self.state is not MetricState.AVAILABLE and self.value is not None:
            raise PressureInputError("METRIC_UNAVAILABLE_VALUE_PRESENT")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str) or not self.reason_code.strip()
        ):
            raise PressureInputError("METRIC_REASON_INVALID")
        if self.state is not MetricState.AVAILABLE and self.reason_code is None:
            object.__setattr__(self, "reason_code", "METRIC_UNAVAILABLE")

    @classmethod
    def available(
        cls,
        value: T,
        *,
        capability: str,
        confidence: float = 1.0,
    ) -> PressureMetric[T]:
        return cls(value, MetricState.AVAILABLE, confidence, capability)

    @classmethod
    def unavailable(
        cls,
        *,
        capability: str,
        reason_code: str = "METRIC_UNAVAILABLE",
    ) -> PressureMetric[T]:
        return cls(None, MetricState.UNAVAILABLE, 0.0, capability, reason_code)

    @classmethod
    def contradictory(
        cls,
        *,
        capability: str,
        reason_code: str = "TELEMETRY_CONTRADICTORY",
    ) -> PressureMetric[T]:
        return cls(None, MetricState.CONTRADICTORY, 0.0, capability, reason_code)

    def usable(self, capabilities: frozenset[str] | None) -> bool:
        return (
            self.state is MetricState.AVAILABLE
            and self.value is not None
            and self.confidence > 0.0
            and (capabilities is None or self.capability in capabilities)
        )


@dataclass(frozen=True, slots=True)
class BandwidthPressure:
    """Normalized memory-bandwidth pressure supplied by a profiler receipt."""

    pressure: float
    class_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pressure",
            _finite_fraction(self.pressure, "BANDWIDTH_PRESSURE_INVALID"),
        )
        if self.class_name is not None and not isinstance(self.class_name, str):
            raise PressureInputError("BANDWIDTH_CLASS_INVALID")


@dataclass(frozen=True, slots=True)
class CachePressure:
    """Normalized LLC/cache-miss pressure from a profiler receipt."""

    pressure: float
    miss_rate: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pressure", _finite_fraction(self.pressure, "CACHE_PRESSURE_INVALID")
        )
        object.__setattr__(
            self,
            "miss_rate",
            _optional_non_negative_number(self.miss_rate, "CACHE_MISS_RATE_INVALID"),
        )


@dataclass(frozen=True, slots=True)
class TransferPressure:
    """CPU/GPU transfer pressure and optional measured bytes/time."""

    pressure: float
    bytes: int | None = None
    milliseconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pressure",
            _finite_fraction(self.pressure, "TRANSFER_PRESSURE_INVALID"),
        )
        object.__setattr__(
            self,
            "bytes",
            _optional_non_negative_int(self.bytes, "TRANSFER_BYTES_INVALID"),
        )
        object.__setattr__(
            self,
            "milliseconds",
            _optional_non_negative_number(self.milliseconds, "TRANSFER_TIME_INVALID"),
        )


@dataclass(frozen=True, slots=True)
class Headroom:
    """Remaining RAM/VRAM/unified-memory fractions, each optional."""

    ram: float | None = None
    vram: float | None = None
    unified: float | None = None

    def __post_init__(self) -> None:
        values = {
            "ram": _optional_non_negative_number(self.ram, "RAM_HEADROOM_INVALID"),
            "vram": _optional_non_negative_number(self.vram, "VRAM_HEADROOM_INVALID"),
            "unified": _optional_non_negative_number(
                self.unified, "UNIFIED_HEADROOM_INVALID"
            ),
        }
        for name, value in values.items():
            if value is not None and value > 1.0:
                raise PressureInputError(f"{name.upper()}_HEADROOM_INVALID")
            object.__setattr__(self, name, value)
        if all(value is None for value in values.values()):
            raise PressureInputError("HEADROOM_VALUE_MISSING")

    @property
    def pressure(self) -> float:
        """Return pressure from known headroom only; unknown pools are omitted."""

        known = [
            1.0 - value
            for value in (self.ram, self.vram, self.unified)
            if value is not None
        ]
        return max(known)


@dataclass(frozen=True, slots=True)
class KVPressure:
    """KV-cache/context pressure supplied by Local, without owning the cache."""

    pressure: float
    context_tokens: int | None = None
    capacity_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pressure", _finite_fraction(self.pressure, "KV_PRESSURE_INVALID")
        )
        object.__setattr__(
            self,
            "context_tokens",
            _optional_non_negative_int(self.context_tokens, "KV_CONTEXT_INVALID"),
        )
        object.__setattr__(
            self,
            "capacity_tokens",
            _optional_non_negative_int(self.capacity_tokens, "KV_CAPACITY_INVALID"),
        )
        if (
            self.context_tokens is not None
            and self.capacity_tokens is not None
            and self.context_tokens > self.capacity_tokens
        ):
            raise PressureInputError("KV_CONTEXT_EXCEEDS_CAPACITY")


@dataclass(frozen=True, slots=True)
class ConcurrencyPressure:
    """Concurrent-session pressure from the runtime receipt."""

    pressure: float
    active_sessions: int | None = None
    capacity_sessions: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pressure",
            _finite_fraction(self.pressure, "CONCURRENCY_PRESSURE_INVALID"),
        )
        object.__setattr__(
            self,
            "active_sessions",
            _optional_non_negative_int(self.active_sessions, "ACTIVE_SESSIONS_INVALID"),
        )
        object.__setattr__(
            self,
            "capacity_sessions",
            _optional_non_negative_int(
                self.capacity_sessions, "SESSION_CAPACITY_INVALID"
            ),
        )
        if (
            self.active_sessions is not None
            and self.capacity_sessions is not None
            and self.active_sessions > self.capacity_sessions
        ):
            raise PressureInputError("ACTIVE_SESSIONS_EXCEED_CAPACITY")


@dataclass(frozen=True, slots=True)
class ThroughputCost:
    """Target/draft throughput and verification cost receipt."""

    pressure: float
    target_tokens_per_second: float | None = None
    draft_tokens_per_second: float | None = None
    verification_milliseconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pressure",
            _finite_fraction(self.pressure, "THROUGHPUT_PRESSURE_INVALID"),
        )
        object.__setattr__(
            self,
            "target_tokens_per_second",
            _optional_non_negative_number(
                self.target_tokens_per_second, "TARGET_THROUGHPUT_INVALID"
            ),
        )
        object.__setattr__(
            self,
            "draft_tokens_per_second",
            _optional_non_negative_number(
                self.draft_tokens_per_second, "DRAFT_THROUGHPUT_INVALID"
            ),
        )
        object.__setattr__(
            self,
            "verification_milliseconds",
            _optional_non_negative_number(
                self.verification_milliseconds, "VERIFICATION_COST_INVALID"
            ),
        )


@dataclass(frozen=True, slots=True)
class PlacementCandidate:
    """A placement option named by Local; Fast only scores the option."""

    name: str
    placement: Placement
    transfer_pressure: float | None = None
    headroom_pressure: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PressureInputError("PLACEMENT_NAME_INVALID")
        if not isinstance(self.placement, Placement):
            raise PressureInputError("PLACEMENT_KIND_INVALID")
        object.__setattr__(
            self,
            "transfer_pressure",
            _optional_non_negative_number(
                self.transfer_pressure, "PLACEMENT_TRANSFER_INVALID"
            ),
        )
        object.__setattr__(
            self,
            "headroom_pressure",
            _optional_non_negative_number(
                self.headroom_pressure, "PLACEMENT_HEADROOM_INVALID"
            ),
        )
        for name in ("transfer_pressure", "headroom_pressure"):
            value = getattr(self, name)
            if value is not None and value > 1.0:
                raise PressureInputError(f"PLACEMENT_{name.upper()}_INVALID")


@dataclass(frozen=True, slots=True)
class Residency:
    """Candidate target/draft residency options supplied by Local."""

    candidates: tuple[PlacementCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, (tuple, list)) or not self.candidates:
            raise PressureInputError("PLACEMENT_CANDIDATES_MISSING")
        candidates = tuple(self.candidates)
        if any(
            not isinstance(candidate, PlacementCandidate) for candidate in candidates
        ):
            raise PressureInputError("PLACEMENT_CANDIDATE_INVALID")
        if len({candidate.name for candidate in candidates}) != len(candidates):
            raise PressureInputError("PLACEMENT_NAME_DUPLICATE")
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class PressureInputs:
    """Optional, capability-gated pressure inputs for one telemetry snapshot."""

    bandwidth: PressureMetric[BandwidthPressure] | None = None
    cache: PressureMetric[CachePressure] | None = None
    transfer: PressureMetric[TransferPressure] | None = None
    residency: PressureMetric[Residency] | None = None
    headroom: PressureMetric[Headroom] | None = None
    kv: PressureMetric[KVPressure] | None = None
    concurrency: PressureMetric[ConcurrencyPressure] | None = None
    throughput: PressureMetric[ThroughputCost] | None = None
    capabilities: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.capabilities is not None:
            if not isinstance(self.capabilities, (frozenset, set, tuple, list)):
                raise PressureInputError("CAPABILITY_SET_INVALID")
            capabilities = frozenset(self.capabilities)
            if any(
                not isinstance(item, str) or not item.strip() for item in capabilities
            ):
                raise PressureInputError("CAPABILITY_SET_INVALID")
            object.__setattr__(self, "capabilities", capabilities)
        for name in _METRIC_NAMES:
            metric = getattr(self, name)
            if metric is not None and not isinstance(metric, PressureMetric):
                raise PressureInputError(f"{name.upper()}_METRIC_INVALID")

    def metric_state(self, name: str) -> MetricState:
        metric = getattr(self, name)
        return MetricState.UNAVAILABLE if metric is None else metric.state

    def metric_is_usable(self, name: str) -> bool:
        metric = getattr(self, name)
        return metric is not None and metric.usable(self.capabilities)


@dataclass(frozen=True, slots=True)
class MetricContribution:
    name: str
    pressure: float
    confidence: float
    weight: float


@dataclass(frozen=True, slots=True)
class PressureScore:
    """Deterministic pressure score and explainable policy boundary result."""

    score: float | None
    confidence: float
    recommendation: Recommendation
    reason_codes: tuple[str, ...]
    used_metrics: tuple[str, ...]
    unavailable_metrics: tuple[str, ...]
    contradictory_metrics: tuple[str, ...]
    contributions: tuple[MetricContribution, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "score": self.score,
            "confidence": self.confidence,
            "recommendation": self.recommendation.value,
            "reason_codes": list(self.reason_codes),
            "used_metrics": list(self.used_metrics),
            "unavailable_metrics": list(self.unavailable_metrics),
            "contradictory_metrics": list(self.contradictory_metrics),
            "contributions": [
                {
                    "name": contribution.name,
                    "pressure": contribution.pressure,
                    "confidence": contribution.confidence,
                    "weight": contribution.weight,
                }
                for contribution in self.contributions
            ],
        }


@dataclass(frozen=True, slots=True)
class PlacementScore:
    candidate: PlacementCandidate
    score: float
    confidence: float
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.candidate.name,
            "placement": self.candidate.placement.value,
            "score": self.score,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
        }


_METRIC_NAMES = (
    "bandwidth",
    "cache",
    "transfer",
    "headroom",
    "kv",
    "concurrency",
    "throughput",
)
_WEIGHTS = {
    "bandwidth": 0.23,
    "cache": 0.12,
    "transfer": 0.22,
    "headroom": 0.16,
    "kv": 0.13,
    "concurrency": 0.08,
    "throughput": 0.06,
}
_HIGH_PRESSURE = 0.80
_HIGH_RISK = 0.65
_MIN_CONFIDENCE = 0.60
_MIN_METRICS = 2
_PLACEMENT_BASE = {
    Placement.SAME_GPU: 0.10,
    Placement.UNIFIED: 0.22,
    Placement.CPU_DRAFT: 0.48,
}


def _pressure_for(name: str, metric: PressureMetric[object]) -> float:
    value = metric.value
    if name == "headroom":
        assert isinstance(value, Headroom)
        return value.pressure
    assert hasattr(value, "pressure")
    return float(value.pressure)


def _metric_reason(inputs: PressureInputs, name: str) -> str | None:
    metric = getattr(inputs, name)
    if metric is None:
        return "METRIC_UNAVAILABLE"
    if metric.state is MetricState.CONTRADICTORY:
        return metric.reason_code or "TELEMETRY_CONTRADICTORY"
    if metric.state is MetricState.UNAVAILABLE:
        return metric.reason_code or "METRIC_UNAVAILABLE"
    if inputs.capabilities is not None and metric.capability not in inputs.capabilities:
        return "CAPABILITY_UNAVAILABLE"
    if metric.confidence <= 0.0:
        return "METRIC_CONFIDENCE_ZERO"
    return None


def score_pressure(
    inputs: PressureInputs,
    *,
    acceptance_rate: float | None = None,
    min_metrics: int = _MIN_METRICS,
    min_confidence: float = _MIN_CONFIDENCE,
) -> PressureScore:
    """Score pressure and return a fail-closed recommendation.

    The weighted average denominator contains only usable metrics.  Missing or
    capability-gated values therefore do not become zero pressure.  A high
    acceptance rate cannot override high bandwidth/transfer pressure.
    """

    if not isinstance(inputs, PressureInputs):
        raise PressureInputError("PRESSURE_INPUTS_INVALID")
    if (
        isinstance(min_metrics, bool)
        or not isinstance(min_metrics, int)
        or min_metrics < 1
    ):
        raise PressureInputError("MIN_METRICS_INVALID")
    min_confidence = _finite_fraction(min_confidence, "MIN_CONFIDENCE_INVALID")
    acceptance_rate = _optional_non_negative_number(
        acceptance_rate, "ACCEPTANCE_RATE_INVALID"
    )
    if acceptance_rate is not None and acceptance_rate > 1.0:
        raise PressureInputError("ACCEPTANCE_RATE_INVALID")

    contributions: list[MetricContribution] = []
    unavailable: list[str] = []
    contradictory: list[str] = []
    for name in _METRIC_NAMES:
        metric = getattr(inputs, name)
        reason = _metric_reason(inputs, name)
        if reason is not None:
            if metric is not None and metric.state is MetricState.CONTRADICTORY:
                contradictory.append(name)
            else:
                unavailable.append(name)
            continue
        assert metric is not None
        pressure = _pressure_for(name, metric)
        contributions.append(
            MetricContribution(name, pressure, metric.confidence, _WEIGHTS[name])
        )

    denominator = sum(item.weight * item.confidence for item in contributions)
    numerator = sum(
        item.weight * item.confidence * item.pressure for item in contributions
    )
    score = 100.0 * numerator / denominator if denominator else None
    coverage = sum(item.weight for item in contributions) / sum(_WEIGHTS.values())
    confidence = coverage * (
        sum(item.weight * item.confidence for item in contributions)
        / sum(item.weight for item in contributions)
        if contributions
        else 0.0
    )

    reasons: list[str] = []
    if contradictory:
        reasons.append("TELEMETRY_CONTRADICTORY")
    if len(contributions) < min_metrics:
        reasons.append("TELEMETRY_INSUFFICIENT")
    if confidence < min_confidence:
        reasons.append("TELEMETRY_LOW_CONFIDENCE")
    for item in contributions:
        if item.pressure < _HIGH_PRESSURE:
            continue
        reasons.append(
            {
                "bandwidth": "BANDWIDTH_PRESSURE_HIGH",
                "cache": "CACHE_PRESSURE_HIGH",
                "transfer": "TRANSFER_PRESSURE_HIGH",
                "headroom": "HEADROOM_LOW",
                "kv": "KV_PRESSURE_HIGH",
                "concurrency": "CONCURRENCY_PRESSURE_HIGH",
                "throughput": "VERIFICATION_COST_HIGH",
            }[item.name]
        )
    if acceptance_rate is None:
        reasons.append("ACCEPTANCE_UNAVAILABLE")
    elif acceptance_rate < 0.50:
        reasons.append("ACCEPTANCE_LOW")
    if not reasons and score is not None and score >= 100.0 * _HIGH_RISK:
        reasons.append("PRESSURE_RISK_HIGH")

    recommendation = (
        Recommendation.SPECULATIVE if not reasons else Recommendation.BASELINE
    )
    return PressureScore(
        score=round(score, 6) if score is not None else None,
        confidence=round(confidence, 6),
        recommendation=recommendation,
        reason_codes=tuple(dict.fromkeys(reasons)),
        used_metrics=tuple(item.name for item in contributions),
        unavailable_metrics=tuple(unavailable),
        contradictory_metrics=tuple(contradictory),
        contributions=tuple(contributions),
    )


def score_placement(
    inputs: PressureInputs, candidate: PlacementCandidate
) -> PlacementScore:
    """Score one Local-provided placement option; lower score is preferred."""

    if not isinstance(inputs, PressureInputs) or not isinstance(
        candidate, PlacementCandidate
    ):
        raise PressureInputError("PLACEMENT_SCORE_INPUT_INVALID")
    score = _PLACEMENT_BASE[candidate.placement] * 100.0
    reasons = {
        Placement.SAME_GPU: ["PLACEMENT_SAME_GPU"],
        Placement.UNIFIED: ["PLACEMENT_UNIFIED_MEMORY"],
        Placement.CPU_DRAFT: ["PLACEMENT_CPU_DRAFT"],
    }[candidate.placement]
    known = 1
    confidence = 1.0

    transfer = candidate.transfer_pressure
    if transfer is None and inputs.metric_is_usable("transfer"):
        assert inputs.transfer is not None and inputs.transfer.value is not None
        transfer = inputs.transfer.value.pressure
    if transfer is None:
        reasons.append("PLACEMENT_TRANSFER_UNAVAILABLE")
        confidence *= 0.75
    else:
        score += transfer * 35.0
        known += 1
        if transfer >= _HIGH_PRESSURE:
            reasons.append("PLACEMENT_TRANSFER_PRESSURE_HIGH")

    headroom = candidate.headroom_pressure
    if headroom is None and inputs.metric_is_usable("headroom"):
        assert inputs.headroom is not None and inputs.headroom.value is not None
        headroom = inputs.headroom.value.pressure
    if headroom is None:
        reasons.append("PLACEMENT_HEADROOM_UNAVAILABLE")
        confidence *= 0.75
    else:
        score += headroom * 25.0
        known += 1
        if headroom >= _HIGH_PRESSURE:
            reasons.append("PLACEMENT_HEADROOM_LOW")

    if inputs.metric_is_usable("bandwidth"):
        assert inputs.bandwidth is not None and inputs.bandwidth.value is not None
        score += inputs.bandwidth.value.pressure * 10.0
        known += 1
    else:
        reasons.append("PLACEMENT_BANDWIDTH_UNAVAILABLE")
        confidence *= 0.90

    confidence *= known / 4.0
    return PlacementScore(
        candidate=candidate,
        score=round(score, 6),
        confidence=round(confidence, 6),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def rank_placements(inputs: PressureInputs) -> tuple[PlacementScore, ...]:
    """Return Local's placement candidates in deterministic score order."""

    if not isinstance(inputs, PressureInputs):
        raise PressureInputError("PLACEMENT_SCORE_INPUT_INVALID")
    if not inputs.metric_is_usable("residency"):
        return ()
    assert inputs.residency is not None and inputs.residency.value is not None
    scores = [
        score_placement(inputs, candidate)
        for candidate in inputs.residency.value.candidates
    ]
    return tuple(sorted(scores, key=lambda item: (item.score, item.candidate.name)))


__all__ = [
    "BandwidthPressure",
    "CachePressure",
    "ConcurrencyPressure",
    "Headroom",
    "KVPressure",
    "MetricContribution",
    "MetricState",
    "Placement",
    "PlacementCandidate",
    "PlacementScore",
    "PressureInputError",
    "PressureInputs",
    "PressureMetric",
    "PressureScore",
    "Recommendation",
    "Residency",
    "ThroughputCost",
    "TransferPressure",
    "rank_placements",
    "score_placement",
    "score_pressure",
]
