"""Policy/cache-first integration for the Fast--Local boundary.

This module composes the existing Fast authorities for one bounded decision:

* :class:`SpeculationPolicy` selects the eligible strategy;
* :func:`score_pressure` and :func:`rank_placements` score Local receipts;
* :func:`auto_tune` and :func:`regression_guardrail` consume profiler evidence;
* :class:`DecisionCache` owns reusable classified decisions; and
* :mod:`contract_surface` validates the versioned boundary messages.

Fast returns a plan and evidence only.  It never loads a model, owns a KV
cache, selects a kernel, or executes inference.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from threading import RLock
from typing import Any

from .contract_surface import (
    CONTRACT_SCHEMA,
    CONTRACT_VERSION,
    INVALIDATION_TRIGGERS,
    ContractSurfaceError,
    digest_for,
    validate_decision_receipt,
    validate_telemetry_snapshot,
)
from .decision_cache import (
    MAX_ENTRIES,
    DecisionCache,
    DecisionCacheError,
    DecisionCacheKey,
)
from .pressure_inputs import (
    PlacementScore,
    PressureInputError,
    PressureInputs,
    PressureScore,
    Recommendation,
    rank_placements,
    score_pressure,
)
from .speculation_policy import (
    SpeculationCapabilities,
    SpeculationPolicy,
    SpeculationResult,
    SpeculationStrategy,
    StrategyCapability,
)
from .speculation_profiler import (
    GuardrailResult,
    ProfilingReceipt,
    SpeculationProfilerError,
    TuningDecision,
    auto_tune,
    regression_guardrail,
)

POLICY_ENGINE_SCHEMA = "simplicio.fast.policy-engine/v1"
POLICY_ENGINE_VERSION = "policy-engine-v1"
MAX_REASON_CODES = 16
MAX_DECISION_RECEIPT_BYTES = 8_192
DEFAULT_MAX_PLACEMENT_CANDIDATES = 16
DEFAULT_BATCH_SIZE = 8
MAX_BATCH_SIZE = 32


class PolicyEngineError(ValueError):
    """Raised when a policy request cannot be evaluated safely."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fraction(value: object, reason_code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyEngineError(reason_code)
    number = float(value)
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise PolicyEngineError(reason_code)
    return number


def _positive_int(value: object, reason_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PolicyEngineError(reason_code)
    return value


def _bounded_identifier(value: object, reason_code: str = "identifier_invalid") -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyEngineError(reason_code)
    text = value.strip()
    if len(text) > 256 or any(character.isspace() for character in text):
        raise PolicyEngineError(reason_code)
    return text


def _cache_identifier(value: str) -> str:
    """Make a bounded cache dimension without storing raw content."""
    try:
        return _bounded_identifier(value)
    except PolicyEngineError:
        return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _unique_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    bounded: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if not isinstance(reason, str) or not reason.strip() or reason in seen:
            continue
        seen.add(reason)
        bounded.append(reason)
        if len(bounded) == MAX_REASON_CODES:
            break
    return tuple(bounded or ("baseline_fallback",))


def _bucket(pressure: float | None) -> str:
    if pressure is None:
        return "unknown"
    if pressure >= 0.80:
        return "high"
    if pressure >= 0.50:
        return "medium"
    return "low"


def _pressure_value(inputs: PressureInputs, name: str) -> float | None:
    if not inputs.metric_is_usable(name):
        return None
    metric = getattr(inputs, name)
    if metric is None or metric.value is None:
        return None
    value = metric.value
    if name == "headroom":
        return float(value.pressure)
    return float(value.pressure)


def _telemetry_classifications(
    pressure: PressureScore,
    profile: ProfilingReceipt | None,
    *,
    capabilities: SpeculationCapabilities | None,
    ttft_regression: float,
    memory_regression: float,
) -> dict[str, str]:
    """Return only classified observations suitable for cache expectations."""
    pressure_class = (
        "unknown" if pressure.score is None else _bucket(pressure.score / 100.0)
    )
    confidence_class = (
        "high"
        if pressure.confidence >= 0.80
        else ("medium" if pressure.confidence >= 0.60 else "low")
    )
    observations = {
        "pressure_class": pressure_class,
        "confidence_class": confidence_class,
        "throughput_class": "unknown",
        "ttft_class": "unknown",
        "memory_class": "unknown",
        "capability_class": "unknown",
    }
    if capabilities is not None:
        capability_classes = []
        for strategy in (
            SpeculationStrategy.NGRAM,
            SpeculationStrategy.DRAFT,
            SpeculationStrategy.DFLASH,
            SpeculationStrategy.MTP,
        ):
            capability = capabilities.for_strategy(strategy)
            state = (
                "usable"
                if capability.is_usable()
                else "supported"
                if capability.supported
                else "off"
            )
            capability_classes.append(f"{strategy.value}:{state}")
        observations["capability_class"] = ",".join(capability_classes)
    if profile is None:
        return observations
    throughput_ratio = profile.metrics.throughput_ratio
    if throughput_ratio is not None:
        observations["throughput_class"] = (
            "regressing"
            if throughput_ratio < 1.0 - ttft_regression
            else "improving"
            if throughput_ratio > 1.0
            else "flat"
        )
    ttft_ratio = profile.metrics.ttft_ratio
    if ttft_ratio is not None:
        observations["ttft_class"] = (
            "regressing"
            if ttft_ratio > 1.0 + ttft_regression
            else "improving"
            if ttft_ratio < 1.0
            else "flat"
        )
    memory_ratio = None
    if (
        profile.metrics.baseline_memory_mb not in (None, 0.0)
        and profile.metrics.speculative_memory_mb is not None
    ):
        memory_ratio = (
            profile.metrics.speculative_memory_mb / profile.metrics.baseline_memory_mb
        )
    if memory_ratio is not None:
        observations["memory_class"] = (
            "regressing"
            if memory_ratio > 1.0 + memory_regression
            else "improving"
            if memory_ratio < 1.0
            else "flat"
        )
    return observations


@dataclass(frozen=True, slots=True)
class PolicyEngineConfig:
    """Small, explicit limits for one policy-engine instance."""

    policy_version: str = POLICY_ENGINE_VERSION
    max_cache_entries: int = 128
    max_placement_candidates: int = DEFAULT_MAX_PLACEMENT_CANDIDATES
    min_pressure_metrics: int = 2
    min_pressure_confidence: float = 0.60
    max_throughput_regression: float = 0.05
    max_memory_increase: float = 0.20
    max_ttft_regression: float = 0.05
    default_draft_tokens: int = 4
    default_acceptance_threshold: float = 0.75
    default_batch_size: int = DEFAULT_BATCH_SIZE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_version", _bounded_identifier(self.policy_version)
        )
        for name in (
            "max_cache_entries",
            "max_placement_candidates",
            "min_pressure_metrics",
            "default_draft_tokens",
            "default_batch_size",
        ):
            _positive_int(getattr(self, name), f"{name}_invalid")
        if self.max_cache_entries > MAX_ENTRIES:
            raise PolicyEngineError("max_cache_entries_invalid")
        if self.max_placement_candidates > 128:
            raise PolicyEngineError("max_placement_candidates_invalid")
        if self.default_batch_size > MAX_BATCH_SIZE:
            raise PolicyEngineError("default_batch_size_invalid")
        if self.default_draft_tokens > 128:
            raise PolicyEngineError("default_draft_tokens_invalid")
        object.__setattr__(
            self,
            "min_pressure_confidence",
            _fraction(self.min_pressure_confidence, "min_pressure_confidence_invalid"),
        )
        for name in (
            "max_throughput_regression",
            "max_memory_increase",
            "max_ttft_regression",
        ):
            value = _fraction(getattr(self, name), f"{name}_invalid")
            if name != "max_memory_increase" and value >= 1.0:
                raise PolicyEngineError(f"{name}_invalid")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "default_acceptance_threshold",
            _fraction(
                self.default_acceptance_threshold,
                "default_acceptance_threshold_invalid",
            ),
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """A bounded Fast plan plus the validated Fast--Local receipt."""

    generation_id: str
    selected: SpeculationStrategy
    enabled: bool
    draft_tokens: int
    acceptance_threshold: float
    placement: str
    context_batch_size: int
    context_ranking: str
    confidence: float
    reason_codes: tuple[str, ...]
    pressure: PressureScore
    guardrail: GuardrailResult | None
    receipt: Mapping[str, Any]
    cache_receipts: tuple[Mapping[str, Any], ...]

    @property
    def strategy(self) -> SpeculationStrategy:
        """Alias for callers that use the policy vocabulary."""
        return self.selected

    @property
    def cache_hit(self) -> bool:
        return any(item.get("outcome") == "hit" for item in self.cache_receipts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": POLICY_ENGINE_SCHEMA,
            "generation_id": self.generation_id,
            "selected": self.selected.value,
            "enabled": self.enabled,
            "draft_tokens": self.draft_tokens,
            "acceptance_threshold": self.acceptance_threshold,
            "placement": self.placement,
            "context_batch_policy": {
                "batch_size": self.context_batch_size,
                "ranking": self.context_ranking,
            },
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "pressure": self.pressure.as_dict(),
            "guardrail": (None if self.guardrail is None else self.guardrail.to_dict()),
            "cache_receipts": [dict(item) for item in self.cache_receipts],
            "receipt": deepcopy(dict(self.receipt)),
        }


class PolicyEngine:
    """Compose the existing policy authorities without executing Local work."""

    def __init__(
        self,
        policy: SpeculationPolicy | None = None,
        *,
        cache: DecisionCache | None = None,
        config: PolicyEngineConfig | None = None,
    ) -> None:
        if policy is not None and not isinstance(policy, SpeculationPolicy):
            raise PolicyEngineError("policy_invalid")
        if cache is not None and not isinstance(cache, DecisionCache):
            raise PolicyEngineError("cache_invalid")
        self.config = config or PolicyEngineConfig()
        self.policy = policy or SpeculationPolicy("auto")
        self.cache = cache or DecisionCache(max_entries=self.config.max_cache_entries)
        self._last_key: DecisionCacheKey | None = None
        self._lock = RLock()

    def activate_generation(self, generation_id: str) -> dict[str, Any]:
        """Activate a generation and invalidate older cached decisions."""
        generation_id = _bounded_identifier(generation_id, "generation_invalid")
        with self._lock:
            self._last_key = None
            return self.cache.activate_generation(generation_id)

    def invalidate_for_drift(
        self,
        key: DecisionCacheKey,
        *,
        dimensions: Sequence[str],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Expose the cache's stable drift invalidation without owning it."""
        if not isinstance(key, DecisionCacheKey):
            raise PolicyEngineError("cache_key_invalid")
        try:
            return self.cache.invalidate_drift(
                key, dimensions=dimensions, reason=reason
            )
        except DecisionCacheError as error:
            raise PolicyEngineError(error.reason_code) from error

    def decide(
        self,
        telemetry_snapshot: Mapping[str, Any],
        pressure_inputs: PressureInputs,
        *,
        capabilities: SpeculationCapabilities | None = None,
        profile: ProfilingReceipt | None = None,
        profiling_receipt: ProfilingReceipt | None = None,
        cache_key: DecisionCacheKey | None = None,
        acceptance_rate: float | None = None,
        workload_class: str = "interactive",
    ) -> PolicyDecision:
        """Return one deterministic, contract-validated Fast decision.

        ``telemetry_snapshot`` is the versioned Local receipt.  ``pressure_inputs``
        contains typed pressure values and may omit unavailable signals.  A
        cache hit reuses only classified decision data bound to the current
        generation and compatible observed classes.
        """
        if (
            profile is not None
            and profiling_receipt is not None
            and profile != profiling_receipt
        ):
            raise PolicyEngineError("profile_arguments_conflict")
        selected_profile = profile or profiling_receipt
        if not isinstance(pressure_inputs, PressureInputs):
            raise PolicyEngineError("pressure_inputs_invalid")
        try:
            normalized = validate_telemetry_snapshot(telemetry_snapshot)
        except ContractSurfaceError as error:
            raise PolicyEngineError("telemetry_snapshot_invalid") from error

        generation = normalized["generation"]
        generation_id = generation["generation_id"]
        cache_generation = _cache_identifier(generation_id)
        payload = normalized["payload"]
        if acceptance_rate is None:
            acceptance_rate = payload["telemetry"].get("acceptance_rate")
        if acceptance_rate is not None:
            acceptance_rate = _fraction(acceptance_rate, "acceptance_rate_invalid")
        if selected_profile is not None and not isinstance(
            selected_profile, ProfilingReceipt
        ):
            raise PolicyEngineError("profile_invalid")

        with self._lock:
            pressure = self._score_pressure(pressure_inputs, acceptance_rate)
            placements = self._rank_placements(pressure_inputs)
            current_key = cache_key or self._build_cache_key(
                normalized,
                pressure_inputs,
                placements,
                workload_class,
                cache_generation,
            )
            cache_events: list[Mapping[str, Any]] = []
            cache_enabled = current_key is not None
            if current_key is not None:
                if current_key.generation != cache_generation:
                    cache_enabled = False
                    cache_events.append(
                        {
                            "operation": "lookup",
                            "outcome": "miss",
                            "reason": "generation_mismatch",
                        }
                    )
                else:
                    cache_events.append(
                        self.cache.activate_generation(cache_generation)
                    )
                    cache_events.extend(self._invalidate_changed_key(current_key))

            guardrail, tuning, guardrail_reasons = self._profile_state(
                selected_profile, generation_id
            )
            effective_capabilities = self._effective_capabilities(
                capabilities, selected_profile
            )
            observations = _telemetry_classifications(
                pressure,
                selected_profile,
                capabilities=effective_capabilities,
                ttft_regression=self.config.max_ttft_regression,
                memory_regression=self.config.max_memory_increase,
            )

            cache_lookup_allowed = (
                cache_enabled
                and pressure.recommendation is Recommendation.SPECULATIVE
                and (guardrail is None or guardrail.enabled)
            )
            if (
                cache_enabled
                and current_key is not None
                and pressure.recommendation is Recommendation.BASELINE
            ):
                # A pressure change can be material without changing the
                # coarse cache key.  Remove the old reusable decision, but do
                # not quarantine the key: a later low-pressure receipt may
                # legitimately store a fresh decision in this generation.
                cache_events.append(
                    self.cache.invalidate(current_key, reason="pressure_drift")
                )
            if (
                cache_enabled
                and current_key is not None
                and not cache_lookup_allowed
                and guardrail is not None
                and not guardrail.enabled
            ):
                if guardrail.reason in {
                    "throughput_regression",
                    "memory_regression",
                    "ttft_regression",
                    "fallback_observed",
                }:
                    cache_events.append(self.cache.disable_for_regression(current_key))
                else:
                    cache_events.append(
                        self.cache.invalidate(current_key, reason=guardrail.reason)
                    )
            if cache_lookup_allowed and current_key is not None:
                cache_events.append(
                    self.cache.lookup(current_key, observed=observations)
                )
                hit = cache_events[-1]
                if hit.get("outcome") == "hit" and isinstance(
                    hit.get("decision"), Mapping
                ):
                    cached = self._cached_plan(hit["decision"])
                    if cached is not None:
                        return self._finish(
                            normalized,
                            pressure,
                            placements,
                            cached["selected"],
                            cached["enabled"],
                            cached["draft_tokens"],
                            cached["acceptance_threshold"],
                            cached["placement"],
                            cached["context_batch_size"],
                            cached["context_ranking"],
                            min(pressure.confidence, cached["confidence"]),
                            _unique_reasons((*cached["reason_codes"], "cache_hit")),
                            guardrail,
                            tuple(cache_events),
                        )

            decision = self._compute_decision(
                pressure,
                pressure_inputs,
                placements,
                effective_capabilities,
                selected_profile,
                guardrail,
                tuning,
                guardrail_reasons,
            )
            cache_events_for_result = tuple(cache_events)
            if cache_enabled and current_key is not None and decision["enabled"]:
                cache_decision = self._cache_payload(decision)
                cache_events_for_result = (
                    *cache_events,
                    self.cache.put(
                        current_key,
                        cache_decision,
                        expected=observations,
                    ),
                )
            return self._finish(
                normalized,
                pressure,
                placements,
                decision["selected"],
                decision["enabled"],
                decision["draft_tokens"],
                decision["acceptance_threshold"],
                decision["placement"],
                decision["context_batch_size"],
                decision["context_ranking"],
                decision["confidence"],
                decision["reason_codes"],
                guardrail,
                cache_events_for_result,
            )

    def _score_pressure(
        self, inputs: PressureInputs, acceptance_rate: float | None
    ) -> PressureScore:
        try:
            return score_pressure(
                inputs,
                acceptance_rate=acceptance_rate,
                min_metrics=self.config.min_pressure_metrics,
                min_confidence=self.config.min_pressure_confidence,
            )
        except PressureInputError as error:
            raise PolicyEngineError(error.reason_code) from error

    def _rank_placements(self, inputs: PressureInputs) -> tuple[PlacementScore, ...]:
        if (
            inputs.residency is not None
            and inputs.residency.value is not None
            and len(inputs.residency.value.candidates)
            > self.config.max_placement_candidates
        ):
            raise PolicyEngineError("placement_candidates_exceed_bound")
        try:
            return rank_placements(inputs)
        except PressureInputError as error:
            raise PolicyEngineError(error.reason_code) from error

    def _build_cache_key(
        self,
        snapshot: Mapping[str, Any],
        inputs: PressureInputs,
        placements: Sequence[PlacementScore],
        workload_class: str,
        cache_generation: str,
    ) -> DecisionCacheKey:
        workload = _bounded_identifier(workload_class, "workload_class_invalid")
        generation = snapshot["generation"]
        payload = snapshot["payload"]
        plan_digest = payload["execution_plan"]["digest"]
        placement_class = (
            placements[0].candidate.placement.value if placements else "unspecified"
        )
        key = DecisionCacheKey(
            model_digest=generation["model_digest"],
            artifact_digest=plan_digest,
            quant_digest="unknown",
            tokenizer_template_identity=None,
            backend_version=generation["backend_digest"],
            hardware_topology_fingerprint=payload["hardware"]["fingerprint"],
            device_placement_class=_cache_identifier(placement_class),
            context_kv_pressure_bucket=_bucket(_pressure_value(inputs, "kv")),
            workload_class=workload,
            concurrency_bucket=_bucket(_pressure_value(inputs, "concurrency")),
            fast_policy_version=self.config.policy_version,
            generation=cache_generation,
        )
        return key

    def _invalidate_changed_key(
        self, current_key: DecisionCacheKey
    ) -> tuple[Mapping[str, Any], ...]:
        previous = self._last_key
        self._last_key = current_key
        if previous is None or previous.generation != current_key.generation:
            return ()
        previous_values = previous.to_dict()
        current_values = current_key.to_dict()
        dimensions = tuple(
            dimension
            for dimension in (
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
            )
            if previous_values[dimension] != current_values[dimension]
        )
        if not dimensions:
            return ()
        # The cache supports only the documented drift dimensions.  The other
        # key fields remain part of the exact key and therefore cannot hit.
        drift_dimensions = tuple(
            dimension
            for dimension in dimensions
            if dimension
            in {
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
            }
        )
        if not drift_dimensions:
            return ()
        try:
            return (
                self.cache.invalidate_drift(current_key, dimensions=drift_dimensions),
            )
        except DecisionCacheError as error:
            raise PolicyEngineError(error.reason_code) from error

    def _profile_state(
        self,
        profile: ProfilingReceipt | None,
        generation_id: str,
    ) -> tuple[GuardrailResult | None, TuningDecision | None, tuple[str, ...]]:
        if profile is None:
            return None, None, ()
        if profile.key.generation != generation_id:
            return (
                GuardrailResult(False, "profile_generation_mismatch", None, None),
                None,
                ("profile_generation_mismatch",),
            )
        try:
            guardrail = regression_guardrail(
                profile.metrics,
                max_throughput_regression=self.config.max_throughput_regression,
                max_memory_increase=self.config.max_memory_increase,
            )
        except SpeculationProfilerError as error:
            raise PolicyEngineError("profile_guardrail_invalid") from error
        reasons: list[str] = []
        if not guardrail.enabled:
            reasons.append(guardrail.reason)
        ttft_ratio = profile.metrics.ttft_ratio
        if (
            ttft_ratio is not None
            and ttft_ratio > 1.0 + self.config.max_ttft_regression
        ):
            reasons.append("ttft_regression")
            guardrail = GuardrailResult(
                False,
                "ttft_regression",
                guardrail.throughput_ratio,
                guardrail.memory_ratio,
            )
        try:
            tuning = auto_tune(
                profile,
                current_draft_tokens=self.config.default_draft_tokens,
                current_acceptance_threshold=self.config.default_acceptance_threshold,
                max_throughput_regression=self.config.max_throughput_regression,
                max_memory_increase=self.config.max_memory_increase,
            )
        except SpeculationProfilerError as error:
            raise PolicyEngineError("profile_tuning_invalid") from error
        return guardrail, tuning, tuple(reasons)

    def _effective_capabilities(
        self,
        capabilities: SpeculationCapabilities | None,
        profile: ProfilingReceipt | None,
    ) -> SpeculationCapabilities:
        if capabilities is not None:
            if not isinstance(capabilities, SpeculationCapabilities):
                raise PolicyEngineError("capabilities_invalid")
            return capabilities
        if profile is None:
            return SpeculationCapabilities()
        ratio = profile.metrics.throughput_ratio
        return SpeculationCapabilities(
            draft=StrategyCapability(
                supported=ratio is not None and ratio > 1.0,
                expected_speedup=ratio,
            )
        )

    def _compute_decision(
        self,
        pressure: PressureScore,
        inputs: PressureInputs,
        placements: Sequence[PlacementScore],
        capabilities: SpeculationCapabilities | None,
        profile: ProfilingReceipt | None,
        guardrail: GuardrailResult | None,
        tuning: TuningDecision | None,
        guardrail_reasons: Sequence[str],
    ) -> dict[str, Any]:
        effective_capabilities = self._effective_capabilities(capabilities, profile)
        try:
            policy_result: SpeculationResult = self.policy.decide(
                effective_capabilities
            )
        except (TypeError, ValueError) as error:
            raise PolicyEngineError("policy_decision_invalid") from error
        selected = policy_result.selected
        reasons: list[str] = list(pressure.reason_codes)
        reasons.extend(guardrail_reasons)
        reasons.append(policy_result.reason)
        if pressure.recommendation is Recommendation.BASELINE:
            selected = SpeculationStrategy.BASELINE
            reasons.append("pressure_baseline_fallback")
        if guardrail is not None and not guardrail.enabled:
            selected = SpeculationStrategy.BASELINE
            reasons.append("guardrail_baseline_fallback")
        if profile is not None and tuning is not None and not tuning.enabled:
            selected = SpeculationStrategy.BASELINE
            reasons.append("tuning_baseline_fallback")

        placement = (
            "baseline" if selected is SpeculationStrategy.BASELINE else "unspecified"
        )
        if placements:
            placement = (
                "baseline"
                if selected is SpeculationStrategy.BASELINE
                else placements[0].candidate.name
            )
            if selected is not SpeculationStrategy.BASELINE:
                reasons.extend(placements[0].reason_codes)
                if any(
                    reason in placements[0].reason_codes
                    for reason in (
                        "PLACEMENT_TRANSFER_PRESSURE_HIGH",
                        "PLACEMENT_HEADROOM_LOW",
                    )
                ):
                    selected = SpeculationStrategy.BASELINE
                    placement = "baseline"
                    reasons.append("placement_pressure_baseline_fallback")
        else:
            reasons.append("placement_candidates_unavailable")

        enabled = selected is not SpeculationStrategy.BASELINE
        draft_tokens = (
            tuning.draft_tokens
            if tuning is not None
            else self.config.default_draft_tokens
        )
        threshold = (
            tuning.acceptance_threshold
            if tuning is not None
            else self.config.default_acceptance_threshold
        )
        batch_size, ranking = self._context_batch_policy(inputs, pressure, enabled)
        if not enabled:
            draft_tokens = 0
        if enabled:
            reasons.append("speculation_enabled")
        else:
            reasons.append("baseline_selected")
        return {
            "selected": selected,
            "enabled": enabled,
            "draft_tokens": draft_tokens,
            "acceptance_threshold": round(threshold, 6),
            "placement": placement,
            "context_batch_size": batch_size,
            "context_ranking": ranking,
            "confidence": round(pressure.confidence, 6),
            "reason_codes": _unique_reasons(reasons),
        }

    def _context_batch_policy(
        self, inputs: PressureInputs, pressure: PressureScore, enabled: bool
    ) -> tuple[int, str]:
        cache = _pressure_value(inputs, "cache")
        concurrency = _pressure_value(inputs, "concurrency")
        if concurrency is not None and concurrency >= 0.80:
            return 1, "latency"
        if cache is not None and cache >= 0.80:
            return 1, "cache_locality"
        if not enabled or pressure.confidence < 0.80:
            return min(4, self.config.default_batch_size), "balanced"
        return self.config.default_batch_size, "throughput"

    def _cached_plan(self, value: Mapping[str, Any]) -> dict[str, Any] | None:
        required = {
            "strategy",
            "enabled",
            "draft_tokens",
            "acceptance_threshold",
            "placement",
            "context_batch_size",
            "context_ranking",
            "confidence",
            "reasons",
        }
        if set(value) != required:
            return None
        try:
            selected = SpeculationStrategy(value["strategy"])
            enabled = value["enabled"]
            if not isinstance(enabled, bool) or enabled != (
                selected is not SpeculationStrategy.BASELINE
            ):
                return None
            draft_tokens = value["draft_tokens"]
            if (
                isinstance(draft_tokens, bool)
                or not isinstance(draft_tokens, int)
                or not 0 <= draft_tokens <= 128
            ):
                return None
            threshold = _fraction(
                value["acceptance_threshold"], "cached_threshold_invalid"
            )
            placement = _bounded_identifier(value["placement"])
            batch_size = _positive_int(
                value["context_batch_size"], "cached_batch_size_invalid"
            )
            if batch_size > MAX_BATCH_SIZE or value["context_ranking"] not in {
                "latency",
                "throughput",
                "balanced",
                "cache_locality",
            }:
                return None
            confidence = _fraction(value["confidence"], "cached_confidence_invalid")
            reasons = value["reasons"]
            if not isinstance(reasons, list) or any(
                not isinstance(reason, str) or not reason.strip() for reason in reasons
            ):
                return None
            return {
                "selected": selected,
                "enabled": enabled,
                "draft_tokens": draft_tokens,
                "acceptance_threshold": threshold,
                "placement": placement,
                "context_batch_size": batch_size,
                "context_ranking": value["context_ranking"],
                "confidence": confidence,
                "reason_codes": tuple(reasons[:MAX_REASON_CODES]),
            }
        except (PolicyEngineError, ValueError, TypeError):
            return None

    def _cache_payload(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "strategy": decision["selected"].value,
            "enabled": decision["enabled"],
            "draft_tokens": decision["draft_tokens"],
            "acceptance_threshold": decision["acceptance_threshold"],
            "placement": _cache_identifier(decision["placement"]),
            "context_batch_size": decision["context_batch_size"],
            "context_ranking": decision["context_ranking"],
            "confidence": decision["confidence"],
            "reasons": list(decision["reason_codes"]),
        }

    def _finish(
        self,
        snapshot: Mapping[str, Any],
        pressure: PressureScore,
        placements: Sequence[PlacementScore],
        selected: SpeculationStrategy,
        enabled: bool,
        draft_tokens: int,
        threshold: float,
        placement: str,
        batch_size: int,
        ranking: str,
        confidence: float,
        reasons: Sequence[str],
        guardrail: GuardrailResult | None,
        cache_receipts: tuple[Mapping[str, Any], ...],
    ) -> PolicyDecision:
        generation_id = snapshot["generation"]["generation_id"]
        reason_codes = _unique_reasons(reasons)
        if selected is SpeculationStrategy.BASELINE:
            enabled = False
            draft_tokens = 0
            placement = "baseline"
        contract_receipt = self._contract_receipt(
            snapshot,
            selected,
            enabled,
            placement,
            batch_size,
            ranking,
            confidence,
            reason_codes,
        )
        return PolicyDecision(
            generation_id=generation_id,
            selected=selected,
            enabled=enabled,
            draft_tokens=draft_tokens,
            acceptance_threshold=round(threshold, 6),
            placement=placement,
            context_batch_size=batch_size,
            context_ranking=ranking,
            confidence=round(confidence, 6),
            reason_codes=reason_codes,
            pressure=pressure,
            guardrail=guardrail,
            receipt=contract_receipt,
            cache_receipts=cache_receipts,
        )

    def _contract_receipt(
        self,
        snapshot: Mapping[str, Any],
        selected: SpeculationStrategy,
        enabled: bool,
        placement: str,
        batch_size: int,
        ranking: str,
        confidence: float,
        reasons: Sequence[str],
    ) -> dict[str, Any]:
        generation_id = snapshot["generation"]["generation_id"]
        key_material = {
            "generation": generation_id,
            "telemetry_digest": snapshot["payload"]["telemetry_digest"],
            "strategy": selected.value,
            "placement": placement,
        }
        decision_id = (
            "decision-" + digest_for(key_material).removeprefix("sha256:")[:24]
        )
        contract_strategy = (
            "disabled"
            if not enabled
            else "tree"
            if selected is SpeculationStrategy.MTP
            else "draft_verify"
        )
        message: dict[str, Any] = {
            "schema": CONTRACT_SCHEMA,
            "contract_version": CONTRACT_VERSION,
            "message_type": "decision_receipt",
            "generation": deepcopy(snapshot["generation"]),
            "payload": {
                "decision_id": decision_id,
                "source_telemetry_digest": snapshot["payload"]["telemetry_digest"],
                "speculation_policy": {
                    "enabled": enabled,
                    "strategy": contract_strategy,
                },
                "placement_recommendation": {
                    "target": placement,
                    "reason_code": reasons[0],
                },
                "context_batch_policy": {
                    "batch_size": batch_size,
                    "ranking": ranking,
                },
                "confidence": round(confidence, 6),
                # The contract normalizes this list before verifying its
                # digest, so sign the normalized representation.
                "reason_codes": sorted(reasons),
                "invalidation_triggers": list(INVALIDATION_TRIGGERS),
                "unavailable": {},
                "decision_digest": "",
            },
        }
        unsigned = deepcopy(message)
        unsigned["payload"].pop("decision_digest")
        message["payload"]["decision_digest"] = digest_for(unsigned)
        try:
            validated = validate_decision_receipt(message)
        except ContractSurfaceError as error:
            raise PolicyEngineError("decision_receipt_invalid") from error
        encoded = str(validated).encode("utf-8")
        if len(encoded) > MAX_DECISION_RECEIPT_BYTES:
            raise PolicyEngineError("decision_receipt_exceeds_bound")
        return validated


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_PLACEMENT_CANDIDATES",
    "MAX_BATCH_SIZE",
    "MAX_DECISION_RECEIPT_BYTES",
    "MAX_REASON_CODES",
    "POLICY_ENGINE_SCHEMA",
    "POLICY_ENGINE_VERSION",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyEngineConfig",
    "PolicyEngineError",
]
