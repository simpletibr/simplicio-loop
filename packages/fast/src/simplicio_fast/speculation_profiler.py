"""Side-effect-free profiling and bounded tuning for speculative decoding.

The profiler owns telemetry receipts and a keyed in-memory record store.  It
does not select a runtime policy or invoke a backend; callers can pass the
decision to the policy owner through the small :func:`adapt_telemetry` and
``to_dict`` interfaces.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PROFILE_SCHEMA = "simplicio.fast.speculation-profile/v1"
TUNING_SCHEMA = "simplicio.fast.speculation-tuning/v1"
HARD_MAX_DRAFT_TOKENS = 128
_CLASSIFICATIONS = frozenset({"MEASURED", "SYNTHETIC"})


class SpeculationProfilerError(ValueError):
    """Raised when telemetry or tuning inputs violate the profiler contract."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpeculationProfilerError(f"{field} must be a non-empty string")
    return value.strip()


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise SpeculationProfilerError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SpeculationProfilerError(f"{field} must be a finite number") from error
    if not math.isfinite(number):
        raise SpeculationProfilerError(f"{field} must be a finite number")
    if minimum is not None and number < minimum:
        raise SpeculationProfilerError(f"{field} must be >= {minimum}")
    return number


def _optional_number(
    value: Any, field: str, *, minimum: float | None = None
) -> float | None:
    return None if value is None else _number(value, field, minimum=minimum)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


@dataclass(frozen=True, slots=True)
class TuningKey:
    """Identity of a tuning decision's generation and execution environment."""

    generation: str
    model: str
    backend: str
    hardware: str
    quantization: str = "unknown"

    def __post_init__(self) -> None:
        for field in ("generation", "model", "backend", "hardware", "quantization"):
            _text(getattr(self, field), field)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> TuningKey:
        if not isinstance(payload, Mapping):
            raise SpeculationProfilerError("key must be an object")
        return cls(
            generation=_text(payload.get("generation"), "generation"),
            model=_text(payload.get("model"), "model"),
            backend=_text(payload.get("backend"), "backend"),
            hardware=_text(payload.get("hardware"), "hardware"),
            quantization=_text(payload.get("quantization", "unknown"), "quantization"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "generation": self.generation,
            "model": self.model,
            "quantization": self.quantization,
            "backend": self.backend,
            "hardware": self.hardware,
        }

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        return (
            self.generation,
            self.model,
            self.quantization,
            self.backend,
            self.hardware,
        )


@dataclass(frozen=True, slots=True)
class ProfilingMetrics:
    """One baseline/speculative observation, including unavailable fields."""

    baseline_tok_s: float
    speculative_tok_s: float | None
    baseline_ttft_ms: float
    speculative_ttft_ms: float | None
    acceptance_rate: float | None
    accepted_length: float | None
    draft_cost_ms: float | None
    verification_cost_ms: float | None
    baseline_memory_mb: float | None
    speculative_memory_mb: float | None
    fallback_reason: str | None = None
    sample_count: int = 1

    def __post_init__(self) -> None:
        _number(self.baseline_tok_s, "baseline_tok_s", minimum=0.000001)
        _optional_number(self.speculative_tok_s, "speculative_tok_s", minimum=0.000001)
        _number(self.baseline_ttft_ms, "baseline_ttft_ms", minimum=0.0)
        _optional_number(self.speculative_ttft_ms, "speculative_ttft_ms", minimum=0.0)
        acceptance = _optional_number(self.acceptance_rate, "acceptance_rate")
        if acceptance is not None and not 0.0 <= acceptance <= 1.0:
            raise SpeculationProfilerError("acceptance_rate must be between 0 and 1")
        _optional_number(self.accepted_length, "accepted_length", minimum=0.0)
        _optional_number(self.draft_cost_ms, "draft_cost_ms", minimum=0.0)
        _optional_number(self.verification_cost_ms, "verification_cost_ms", minimum=0.0)
        _optional_number(self.baseline_memory_mb, "baseline_memory_mb", minimum=0.0)
        _optional_number(
            self.speculative_memory_mb, "speculative_memory_mb", minimum=0.0
        )
        if self.fallback_reason is not None:
            _text(self.fallback_reason, "fallback_reason")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 1
        ):
            raise SpeculationProfilerError("sample_count must be a positive integer")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ProfilingMetrics:
        if not isinstance(payload, Mapping):
            raise SpeculationProfilerError("telemetry must be an object")
        required = ("baseline_tok_s", "baseline_ttft_ms")
        missing = [field for field in required if field not in payload]
        if missing:
            raise SpeculationProfilerError(f"missing telemetry: {', '.join(missing)}")
        return cls(
            baseline_tok_s=payload["baseline_tok_s"],
            speculative_tok_s=payload.get("speculative_tok_s"),
            baseline_ttft_ms=payload["baseline_ttft_ms"],
            speculative_ttft_ms=payload.get("speculative_ttft_ms"),
            acceptance_rate=payload.get("acceptance_rate"),
            accepted_length=payload.get("accepted_length"),
            draft_cost_ms=payload.get("draft_cost_ms"),
            verification_cost_ms=payload.get("verification_cost_ms"),
            baseline_memory_mb=payload.get("baseline_memory_mb"),
            speculative_memory_mb=payload.get("speculative_memory_mb"),
            fallback_reason=payload.get("fallback_reason"),
            sample_count=payload.get("sample_count", 1),
        )

    @property
    def throughput_ratio(self) -> float | None:
        if self.speculative_tok_s is None:
            return None
        return self.speculative_tok_s / self.baseline_tok_s

    @property
    def ttft_ratio(self) -> float | None:
        if self.speculative_ttft_ms is None or self.baseline_ttft_ms == 0:
            return None
        return self.speculative_ttft_ms / self.baseline_ttft_ms

    @property
    def memory_delta_mb(self) -> float | None:
        if self.baseline_memory_mb is None or self.speculative_memory_mb is None:
            return None
        return self.speculative_memory_mb - self.baseline_memory_mb

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_tok_s": self.baseline_tok_s,
            "speculative_tok_s": self.speculative_tok_s,
            "baseline_ttft_ms": self.baseline_ttft_ms,
            "speculative_ttft_ms": self.speculative_ttft_ms,
            "acceptance_rate": self.acceptance_rate,
            "accepted_length": self.accepted_length,
            "draft_cost_ms": self.draft_cost_ms,
            "verification_cost_ms": self.verification_cost_ms,
            "baseline_memory_mb": self.baseline_memory_mb,
            "speculative_memory_mb": self.speculative_memory_mb,
            "memory_delta_mb": self.memory_delta_mb,
            "fallback_reason": self.fallback_reason,
            "sample_count": self.sample_count,
            "throughput_ratio": self.throughput_ratio,
            "ttft_ratio": self.ttft_ratio,
        }


@dataclass(frozen=True, slots=True)
class ProfilingReceipt:
    """Machine-readable profile output for Local/Runtime report adapters."""

    key: TuningKey
    metrics: ProfilingMetrics
    classification: str = "MEASURED"
    source: str = "adapter"
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.classification not in _CLASSIFICATIONS:
            raise SpeculationProfilerError(
                f"classification must be one of {sorted(_CLASSIFICATIONS)}"
            )
        _text(self.source, "source")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise SpeculationProfilerError("seed must be an integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROFILE_SCHEMA,
            "classification": self.classification,
            "source": self.source,
            "seed": self.seed,
            "key": self.key.to_dict(),
            "metrics": self.metrics.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class TuningBounds:
    """Explicit limits for the small tuning surface owned by this module."""

    min_draft_tokens: int = 1
    max_draft_tokens: int = 8
    min_acceptance_threshold: float = 0.50
    max_acceptance_threshold: float = 0.95
    draft_step: int = 1
    threshold_step: float = 0.05

    def __post_init__(self) -> None:
        for field in ("min_draft_tokens", "max_draft_tokens", "draft_step"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SpeculationProfilerError(f"{field} must be a positive integer")
        if self.min_draft_tokens > self.max_draft_tokens:
            raise SpeculationProfilerError("min_draft_tokens must not exceed maximum")
        if self.max_draft_tokens > HARD_MAX_DRAFT_TOKENS:
            raise SpeculationProfilerError(
                f"max_draft_tokens must be <= {HARD_MAX_DRAFT_TOKENS}"
            )
        minimum = _number(
            self.min_acceptance_threshold,
            "min_acceptance_threshold",
        )
        maximum = _number(
            self.max_acceptance_threshold,
            "max_acceptance_threshold",
        )
        if not 0.0 <= minimum <= maximum <= 1.0:
            raise SpeculationProfilerError(
                "acceptance thresholds must be between 0 and 1"
            )
        _number(self.threshold_step, "threshold_step", minimum=0.000001)
        if self.threshold_step > maximum - minimum and maximum != minimum:
            raise SpeculationProfilerError("threshold_step exceeds threshold range")

    def clamp_draft_tokens(self, value: int) -> int:
        return int(_clamp(value, self.min_draft_tokens, self.max_draft_tokens))

    def clamp_threshold(self, value: float) -> float:
        return _clamp(
            value,
            self.min_acceptance_threshold,
            self.max_acceptance_threshold,
        )


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    enabled: bool
    reason: str
    throughput_ratio: float | None
    memory_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "reason": self.reason,
            "throughput_ratio": self.throughput_ratio,
            "memory_ratio": self.memory_ratio,
        }


def regression_guardrail(
    metrics: ProfilingMetrics,
    *,
    max_throughput_regression: float = 0.05,
    max_memory_increase: float = 0.20,
) -> GuardrailResult:
    """Disable speculation when measured throughput or memory regresses."""
    regression = _number(
        max_throughput_regression, "max_throughput_regression", minimum=0.0
    )
    memory_budget = _number(max_memory_increase, "max_memory_increase", minimum=0.0)
    if regression >= 1.0:
        raise SpeculationProfilerError("max_throughput_regression must be < 1")
    ratio = metrics.throughput_ratio
    memory_ratio = None
    if (
        metrics.baseline_memory_mb not in (None, 0.0)
        and metrics.speculative_memory_mb is not None
    ):
        memory_ratio = metrics.speculative_memory_mb / metrics.baseline_memory_mb
    if metrics.fallback_reason:
        return GuardrailResult(False, "fallback_observed", ratio, memory_ratio)
    if ratio is None:
        return GuardrailResult(
            False, "speculative_tok_s_unavailable", ratio, memory_ratio
        )
    if ratio < 1.0 - regression:
        return GuardrailResult(False, "throughput_regression", ratio, memory_ratio)
    if memory_ratio is not None and memory_ratio > 1.0 + memory_budget:
        return GuardrailResult(False, "memory_regression", ratio, memory_ratio)
    return GuardrailResult(True, "within_guardrail", ratio, memory_ratio)


@dataclass(frozen=True, slots=True)
class TuningDecision:
    key: TuningKey
    draft_tokens: int
    acceptance_threshold: float
    enabled: bool
    reason: str
    guardrail: GuardrailResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.to_dict(),
            "draft_tokens": self.draft_tokens,
            "acceptance_threshold": self.acceptance_threshold,
            "speculation_enabled": self.enabled,
            "reason": self.reason,
            "guardrail": self.guardrail.to_dict(),
        }


def auto_tune(
    profile: ProfilingReceipt,
    *,
    current_draft_tokens: int = 4,
    current_acceptance_threshold: float = 0.75,
    bounds: TuningBounds | None = None,
    max_throughput_regression: float = 0.05,
    max_memory_increase: float = 0.20,
) -> TuningDecision:
    """Suggest one bounded setting update without invoking a policy owner."""
    selected_bounds = bounds or TuningBounds()
    if (
        isinstance(current_draft_tokens, bool)
        or not isinstance(current_draft_tokens, int)
        or current_draft_tokens < 1
    ):
        raise SpeculationProfilerError(
            "current_draft_tokens must be a positive integer"
        )
    threshold = _number(
        current_acceptance_threshold,
        "current_acceptance_threshold",
    )
    guardrail = regression_guardrail(
        profile.metrics,
        max_throughput_regression=max_throughput_regression,
        max_memory_increase=max_memory_increase,
    )
    draft_tokens = selected_bounds.clamp_draft_tokens(current_draft_tokens)
    threshold = selected_bounds.clamp_threshold(threshold)
    if not guardrail.enabled:
        return TuningDecision(
            profile.key,
            draft_tokens,
            threshold,
            False,
            guardrail.reason,
            guardrail,
        )

    acceptance = profile.metrics.acceptance_rate
    accepted_length = profile.metrics.accepted_length
    if acceptance is None:
        return TuningDecision(
            profile.key,
            draft_tokens,
            threshold,
            True,
            "acceptance_telemetry_unavailable",
            guardrail,
        )
    if acceptance >= 0.85 and (
        accepted_length is None or accepted_length >= draft_tokens * 0.75
    ):
        draft_tokens += selected_bounds.draft_step
    elif acceptance <= 0.60 or (
        accepted_length is not None and accepted_length < max(1.0, draft_tokens * 0.50)
    ):
        draft_tokens -= selected_bounds.draft_step
    if acceptance >= 0.85:
        threshold += selected_bounds.threshold_step
    elif acceptance <= 0.60:
        threshold -= selected_bounds.threshold_step
    return TuningDecision(
        profile.key,
        selected_bounds.clamp_draft_tokens(draft_tokens),
        selected_bounds.clamp_threshold(threshold),
        True,
        "tuned",
        guardrail,
    )


@dataclass(frozen=True, slots=True)
class TuningRecord:
    key: TuningKey
    profile: ProfilingReceipt
    decision: TuningDecision

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TUNING_SCHEMA,
            "key": self.key.to_dict(),
            "profile": self.profile.to_dict(),
            "decision": self.decision.to_dict(),
        }


class TuningRecordStore:
    """Latest decision per generation/model/backend/hardware key."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str, str], TuningRecord] = {}

    def record(
        self,
        profile: ProfilingReceipt,
        decision: TuningDecision | None = None,
    ) -> TuningRecord:
        selected = decision or auto_tune(profile)
        if selected.key != profile.key:
            raise SpeculationProfilerError("profile and decision keys must match")
        item = TuningRecord(profile.key, profile, selected)
        self._records[profile.key.as_tuple()] = item
        return item

    def get(self, key: TuningKey) -> TuningRecord | None:
        return self._records.get(key.as_tuple())

    def __len__(self) -> int:
        return len(self._records)

    def to_dict(self) -> dict[str, Any]:
        records = [self._records[key].to_dict() for key in sorted(self._records)]
        return {"schema": TUNING_SCHEMA, "records": records}


def adapt_telemetry(
    key: TuningKey,
    telemetry: Mapping[str, Any],
    *,
    classification: str = "MEASURED",
) -> ProfilingReceipt:
    """Convert one runtime telemetry mapping into a profiler receipt."""
    if not isinstance(key, TuningKey):
        raise SpeculationProfilerError("key must be a TuningKey")
    return ProfilingReceipt(
        key,
        ProfilingMetrics.from_mapping(telemetry),
        classification=classification,
        source="adapter",
    )


def _stable_fraction(key: TuningKey, seed: int) -> float:
    material = json.dumps(
        {"key": key.to_dict(), "seed": seed},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    value = int(hashlib.sha256(material).hexdigest()[:8], 16)
    return (value % 1001 - 500) / 100_000.0


def deterministic_synthetic_profile(
    key: TuningKey,
    *,
    seed: int = 493,
    baseline_tok_s: float = 100.0,
    baseline_ttft_ms: float = 100.0,
    baseline_memory_mb: float = 1024.0,
    draft_tokens: int = 4,
    acceptance_rate: float = 0.80,
    accepted_length: float | None = None,
    draft_cost_ms: float = 2.0,
    verification_cost_ms: float = 4.0,
    throughput_gain: float = 0.12,
    fallback_reason: str | None = None,
) -> ProfilingReceipt:
    """Create repeatable synthetic telemetry without wall-clock or RNG state."""
    if not isinstance(key, TuningKey):
        raise SpeculationProfilerError("key must be a TuningKey")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SpeculationProfilerError("seed must be an integer")
    if isinstance(draft_tokens, bool) or not isinstance(draft_tokens, int):
        raise SpeculationProfilerError("draft_tokens must be an integer")
    if not 1 <= draft_tokens <= HARD_MAX_DRAFT_TOKENS:
        raise SpeculationProfilerError(
            f"draft_tokens must be between 1 and {HARD_MAX_DRAFT_TOKENS}"
        )
    baseline = _number(baseline_tok_s, "baseline_tok_s", minimum=0.000001)
    ttft = _number(baseline_ttft_ms, "baseline_ttft_ms", minimum=0.0)
    memory = _number(baseline_memory_mb, "baseline_memory_mb", minimum=0.0)
    acceptance = _number(acceptance_rate, "acceptance_rate")
    if not 0.0 <= acceptance <= 1.0:
        raise SpeculationProfilerError("acceptance_rate must be between 0 and 1")
    if fallback_reason is not None:
        metrics = ProfilingMetrics(
            baseline,
            None,
            ttft,
            None,
            None,
            None,
            None,
            None,
            memory,
            None,
            fallback_reason,
        )
    else:
        gain = _number(throughput_gain, "throughput_gain", minimum=-0.99)
        accepted = (
            min(float(draft_tokens), max(0.0, draft_tokens * acceptance))
            if accepted_length is None
            else _number(accepted_length, "accepted_length", minimum=0.0)
        )
        jitter = _stable_fraction(key, seed)
        speculative = baseline * (1.0 + gain + jitter)
        speculative_ttft = ttft * (0.95 + jitter)
        speculative_memory = memory + draft_tokens * 2.5
        metrics = ProfilingMetrics(
            baseline,
            speculative,
            ttft,
            max(0.0, speculative_ttft),
            acceptance,
            accepted,
            _number(draft_cost_ms, "draft_cost_ms", minimum=0.0),
            _number(verification_cost_ms, "verification_cost_ms", minimum=0.0),
            memory,
            speculative_memory,
        )
    return ProfilingReceipt(
        key,
        metrics,
        classification="SYNTHETIC",
        source="deterministic-synthetic",
        seed=seed,
    )


__all__ = [
    "HARD_MAX_DRAFT_TOKENS",
    "PROFILE_SCHEMA",
    "TUNING_SCHEMA",
    "GuardrailResult",
    "ProfilingMetrics",
    "ProfilingReceipt",
    "SpeculationProfilerError",
    "TuningBounds",
    "TuningDecision",
    "TuningKey",
    "TuningRecord",
    "TuningRecordStore",
    "adapt_telemetry",
    "auto_tune",
    "deterministic_synthetic_profile",
    "regression_guardrail",
]
