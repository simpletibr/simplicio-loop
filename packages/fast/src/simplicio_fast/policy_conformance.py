"""Deterministic Fast/Local policy conformance harness.

This module exercises the Fast policy boundary without importing Simplicio
Local or executing a model.  Local is represented only by the versioned
execution-plan mapping and its digest.  The harness is intentionally
side-effect free so it can run in environments where Local, CUDA, and kernel
artifacts are unavailable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contract_surface import (
    CONTRACT_SCHEMA,
    CONTRACT_VERSION,
    DRIFT_FIELDS,
    INVALIDATION_TRIGGERS,
    canonical_json,
    contract_manifest,
    digest_for,
    invalidation_triggers,
    validate_decision_receipt,
    validate_telemetry_snapshot,
)
from .decision_cache import DecisionCache, DecisionCacheKey, InvalidationReason
from .pressure_inputs import PressureInputs, PressureMetric, score_pressure
from .speculation_policy import (
    DECISION_OWNER,
    EXECUTION_OWNER,
    SpeculationCapabilities,
    SpeculationConfiguration,
    SpeculationPolicy,
    SpeculationResult,
    SpeculationStrategy,
    StrategyCapability,
)
from .speculation_profiler import (
    TuningKey,
    auto_tune,
    deterministic_synthetic_profile,
    regression_guardrail,
)

POLICY_CONFORMANCE_SCHEMA = "simplicio.fast.policy-conformance/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_GENERATION = {
    "generation_id": "generation-498",
    "source_revision": "a" * 40,
    "hardware_digest": "sha256:" + "1" * 64,
    "model_digest": "sha256:" + "2" * 64,
    "backend_digest": "sha256:" + "3" * 64,
    "context_digest": "sha256:" + "4" * 64,
    "concurrency_digest": "sha256:" + "5" * 64,
}

_CACHE_KEY = {
    "model_digest": "model-v1",
    "artifact_digest": "artifact-v1",
    "quant_digest": "q4-v1",
    "tokenizer_template_identity": "chat-template-v1",
    "backend_version": "backend-v1",
    "hardware_topology_fingerprint": "hardware-v1",
    "device_placement_class": "same-device",
    "context_kv_pressure_bucket": "medium",
    "workload_class": "interactive",
    "concurrency_bucket": "c2",
    "fast_policy_version": "policy-conformance-v1",
    "generation": "generation-498",
}

_CACHE_DRIFT_DIMENSIONS = {
    "model_digest": "model_digest",
    "backend_digest": "backend_version",
    "hardware_digest": "hardware_topology_fingerprint",
    "context_digest": "context_kv_pressure_bucket",
    "concurrency_digest": "concurrency_bucket",
}

_CACHE_DRIFT_REASONS = {
    "model_digest": InvalidationReason.MODEL_DRIFT,
    "backend_version": InvalidationReason.BACKEND_DRIFT,
    "hardware_topology_fingerprint": InvalidationReason.HARDWARE_DRIFT,
    "context_kv_pressure_bucket": InvalidationReason.CONTEXT_PRESSURE_DRIFT,
    "concurrency_bucket": InvalidationReason.CONCURRENCY_DRIFT,
}

_LOCAL_CONTRACT_FIELDS = frozenset(
    ("hardware", "capabilities", "telemetry", "execution_plan", "execution")
)
_LOCAL_EXECUTION_FIELDS = frozenset(("model", "kv_cache", "kernels", "execution"))
_FAST_POLICY_FIELDS = frozenset(
    ("policy_decisions", "decision_receipts", "invalidation_triggers")
)


class PolicyConformanceError(ValueError):
    """Stable reason code for malformed conformance inputs."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require_digest(value: object, reason_code: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise PolicyConformanceError(reason_code)
    return value


def _generation(**overrides: str) -> dict[str, str]:
    generation = dict(_GENERATION)
    generation.update(overrides)
    return generation


def _envelope(
    message_type: str,
    generation: Mapping[str, Any],
    payload: Mapping[str, Any],
    digest_field: str,
) -> dict[str, Any]:
    unsigned = {
        "schema": CONTRACT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "message_type": message_type,
        "generation": dict(generation),
        "payload": dict(payload),
    }
    signed_payload = dict(payload)
    signed_payload[digest_field] = digest_for(unsigned)
    return {**unsigned, "payload": signed_payload}


def execution_plan_digest(execution_plan: Mapping[str, Any]) -> str:
    """Return the canonical digest of a Local plan without its digest field."""

    if not isinstance(execution_plan, Mapping):
        raise PolicyConformanceError("execution_plan_invalid")
    unsigned = dict(execution_plan)
    supplied = unsigned.pop("digest", None)
    expected = digest_for(unsigned)
    if supplied is not None and supplied != expected:
        raise PolicyConformanceError("execution_plan_digest_mismatch")
    return expected


@dataclass(frozen=True, slots=True)
class DecisionPlanDigestBinding:
    """The explicit shared binding between Fast's decision and Local's plan."""

    decision_digest: str
    execution_plan_digest: str
    binding_digest: str

    @classmethod
    def create(
        cls, decision_digest: str, execution_plan: Mapping[str, Any]
    ) -> DecisionPlanDigestBinding:
        decision_digest = _require_digest(decision_digest, "decision_digest_invalid")
        plan_digest = execution_plan_digest(execution_plan)
        unsigned = {
            "decision_digest": decision_digest,
            "execution_plan_digest": plan_digest,
        }
        return cls(decision_digest, plan_digest, digest_for(unsigned))

    def to_dict(self) -> dict[str, str]:
        return {
            "decision_digest": self.decision_digest,
            "execution_plan_digest": self.execution_plan_digest,
            "binding_digest": self.binding_digest,
        }


def _decision_digest(value: object) -> str:
    if isinstance(value, Mapping):
        if isinstance(value.get("payload"), Mapping):
            value = value["payload"].get("decision_digest")
        else:
            value = value.get("decision_digest")
    return _require_digest(value, "decision_digest_invalid")


def bind_decision_to_execution_plan(
    decision: Mapping[str, Any] | str,
    execution_plan: Mapping[str, Any],
) -> DecisionPlanDigestBinding:
    """Create a deterministic digest binding without invoking Local."""

    return DecisionPlanDigestBinding.create(_decision_digest(decision), execution_plan)


def verify_decision_execution_plan_binding(
    binding: DecisionPlanDigestBinding,
    decision: Mapping[str, Any] | str,
    execution_plan: Mapping[str, Any],
) -> bool:
    """Verify both digests and the binding digest against current payloads."""

    if not isinstance(binding, DecisionPlanDigestBinding):
        return False
    try:
        expected = bind_decision_to_execution_plan(decision, execution_plan)
    except PolicyConformanceError:
        return False
    return expected == binding


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One deterministic policy selection vector."""

    name: str
    configuration: SpeculationConfiguration
    capabilities: SpeculationCapabilities
    expected_strategy: SpeculationStrategy
    expected_fallback: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configuration": self.configuration.value,
            "capabilities": self.capabilities.to_dict(),
            "expected_strategy": self.expected_strategy.value,
            "expected_fallback": self.expected_fallback,
        }


@dataclass(frozen=True, slots=True)
class ConformanceRow:
    """Bounded evidence for one policy matrix case."""

    case: str
    expected_strategy: str
    expected_fallback: bool
    selected_strategy: str
    policy_reason: str
    fallback: bool
    contract_validated: bool
    binding_validated: bool
    fast_decision_digest: str
    local_execution_plan_digest: str
    binding_digest: str

    @property
    def passed(self) -> bool:
        return (
            self.expected_strategy == self.selected_strategy
            and self.fallback == self.expected_fallback
            and self.contract_validated
            and self.binding_validated
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "expected_strategy": self.expected_strategy,
            "expected_fallback": self.expected_fallback,
            "selected_strategy": self.selected_strategy,
            "policy_reason": self.policy_reason,
            "fallback": self.fallback,
            "contract_validated": self.contract_validated,
            "binding_validated": self.binding_validated,
            "passed": self.passed,
            "fast_decision_digest": self.fast_decision_digest,
            "local_execution_plan_digest": self.local_execution_plan_digest,
            "binding_digest": self.binding_digest,
        }


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    """One named conformance assertion in the report."""

    name: str
    passed: bool
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": json.loads(canonical_json(self.details)),
        }


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """Deterministic, JSON-safe result of :func:`run_conformance`."""

    rows: tuple[ConformanceRow, ...]
    checks: tuple[ConformanceCheck, ...]
    passed: bool

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": POLICY_CONFORMANCE_SCHEMA,
            "passed": self.passed,
            "matrix": [row.to_dict() for row in self.rows],
            "checks": [check.to_dict() for check in self.checks],
        }

    @property
    def report_digest(self) -> str:
        return digest_for(self._unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "report_digest": self.report_digest}

    def to_json(self) -> str:
        return canonical_json(self.to_dict()).decode("utf-8")

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def build_conformance_matrix() -> tuple[ConformanceCase, ...]:
    """Return the fixed baseline/ngram/draft/DFlash/MTP matrix."""

    return (
        ConformanceCase(
            "baseline",
            SpeculationConfiguration.OFF,
            SpeculationCapabilities(),
            SpeculationStrategy.BASELINE,
            False,
        ),
        ConformanceCase(
            "ngram",
            SpeculationConfiguration.NGRAM,
            SpeculationCapabilities(ngram=StrategyCapability(True, 1.10)),
            SpeculationStrategy.NGRAM,
            False,
        ),
        ConformanceCase(
            "draft",
            SpeculationConfiguration.DRAFT,
            SpeculationCapabilities(draft=StrategyCapability(True, 1.20)),
            SpeculationStrategy.DRAFT,
            False,
        ),
        ConformanceCase(
            "dflash",
            SpeculationConfiguration.DFLASH,
            SpeculationCapabilities(dflash=StrategyCapability(True, 1.30)),
            SpeculationStrategy.DFLASH,
            False,
        ),
        ConformanceCase(
            "mtp",
            SpeculationConfiguration.MTP,
            SpeculationCapabilities(mtp=StrategyCapability(True, 1.40)),
            SpeculationStrategy.MTP,
            False,
        ),
    )


def _local_execution_plan(
    case: ConformanceCase, result: SpeculationResult
) -> dict[str, Any]:
    unsigned = {
        "plan_id": f"plan-498-{case.name}",
        "reason_codes": sorted(
            (
                f"execution_owner:{result.receipt.execution_owner}",
                f"policy_reason:{result.reason}",
                f"strategy_selected:{result.selected.value}",
            )
        ),
    }
    return {**unsigned, "digest": execution_plan_digest(unsigned)}


def _telemetry_snapshot(
    execution_plan: Mapping[str, Any],
    *,
    level: str = "standard",
    sample_id: str = "sample-498",
) -> dict[str, Any]:
    required_metrics = {
        "tokens_per_second": 42.5,
        "memory_used_bytes": 4_294_967_296,
    }
    optional_metrics = {
        "ttft_ms": 18.2,
        "acceptance_rate": 0.91,
        "bandwidth_bytes_per_second": 1_200_000_000,
        "transfer_bytes": 8192,
        "cache_pressure_ratio": 0.20,
        "stage_timings_ms": {"verify": 4.0},
    }
    unavailable: dict[str, str] = {}
    telemetry = dict(required_metrics)
    for field, value in optional_metrics.items():
        if level == "minimal":
            unavailable[field] = "not_exposed"
        elif level == "standard" and field in {
            "cache_pressure_ratio",
            "stage_timings_ms",
        }:
            unavailable[field] = "not_collected"
        else:
            telemetry[field] = value
    payload = {
        "sample_id": sample_id,
        "observed_at": "2026-08-23T15:00:00Z",
        "level": level,
        "hardware": {
            "fingerprint": _GENERATION["hardware_digest"],
            "device_count": 1,
            "devices": ["device:0"],
            "memory_total_bytes": 17_179_869_184,
        },
        "capabilities": {
            "speculation": {"status": "supported", "details": ["policy"]},
            "placement": {"status": "supported", "details": ["local"]},
            "kernels": {"status": "supported", "details": ["opaque"]},
        },
        "execution_plan": dict(execution_plan),
        "telemetry": telemetry,
        "unavailable": unavailable,
    }
    return _envelope("telemetry_snapshot", _GENERATION, payload, "telemetry_digest")


def _decision_receipt(
    case: ConformanceCase,
    result: SpeculationResult,
    telemetry: Mapping[str, Any],
    *,
    confidence: float = 1.0,
) -> dict[str, Any]:
    selected = result.selected.value
    enabled = result.selected is not SpeculationStrategy.BASELINE
    payload = {
        "decision_id": f"decision-498-{case.name}",
        "source_telemetry_digest": telemetry["payload"]["telemetry_digest"],
        "speculation_policy": {
            "enabled": enabled,
            "strategy": "draft_verify" if enabled else "disabled",
        },
        "placement_recommendation": {
            "target": "local",
            "reason_code": "capability_supported",
        },
        "context_batch_policy": {"batch_size": 1, "ranking": "balanced"},
        "confidence": confidence,
        "reason_codes": sorted(
            (f"policy_strategy:{selected}", "execution_plan_digest_bound")
        ),
        "invalidation_triggers": list(INVALIDATION_TRIGGERS),
        "unavailable": {},
    }
    return _envelope("decision_receipt", _GENERATION, payload, "decision_digest")


def _cache_key(**overrides: str) -> DecisionCacheKey:
    values = dict(_CACHE_KEY)
    values.update(overrides)
    return DecisionCacheKey(**values)


def _matrix_rows() -> tuple[ConformanceRow, ...]:
    rows: list[ConformanceRow] = []
    for case in build_conformance_matrix():
        result = SpeculationPolicy(case.configuration).decide(case.capabilities)
        local_plan = _local_execution_plan(case, result)
        telemetry = validate_telemetry_snapshot(_telemetry_snapshot(local_plan))
        decision = validate_decision_receipt(_decision_receipt(case, result, telemetry))
        binding = bind_decision_to_execution_plan(
            decision, telemetry["payload"]["execution_plan"]
        )
        rows.append(
            ConformanceRow(
                case=case.name,
                expected_strategy=case.expected_strategy.value,
                expected_fallback=case.expected_fallback,
                selected_strategy=result.selected.value,
                policy_reason=result.reason,
                fallback=result.receipt.fallback,
                contract_validated=True,
                binding_validated=verify_decision_execution_plan_binding(
                    binding,
                    decision,
                    telemetry["payload"]["execution_plan"],
                ),
                fast_decision_digest=decision["payload"]["decision_digest"],
                local_execution_plan_digest=telemetry["payload"]["execution_plan"][
                    "digest"
                ],
                binding_digest=binding.binding_digest,
            )
        )
    return tuple(rows)


def _drift_check() -> ConformanceCheck:
    rows: list[dict[str, Any]] = []
    for field, trigger in DRIFT_FIELDS:
        changed_generation = _generation(
            **{field: "sha256:" + ("a" if field != "model_digest" else "b") * 64}
        )
        observed_triggers = invalidation_triggers(_GENERATION, changed_generation)
        dimension = _CACHE_DRIFT_DIMENSIONS[field]
        base_key = _cache_key()
        changed_key = _cache_key(**{dimension: f"{_CACHE_KEY[dimension]}-drift"})
        cache = DecisionCache(generation=base_key.generation)
        cache.put(base_key, {"strategy": "baseline"})
        invalidated = cache.invalidate_drift(changed_key, dimensions=(dimension,))
        lookup = cache.lookup(base_key)
        expected_reason = _CACHE_DRIFT_REASONS[dimension]
        passed = (
            observed_triggers == (trigger,)
            and invalidated["outcome"] == "invalidated"
            and invalidated["reason"] == expected_reason
            and lookup["outcome"] == "invalidated"
            and lookup["reason"] == expected_reason
        )
        rows.append(
            {
                "contract_field": field,
                "contract_trigger": trigger,
                "cache_dimension": dimension,
                "cache_reason": invalidated["reason"],
                "passed": passed,
            }
        )
    return ConformanceCheck(
        "drift_invalidation",
        all(row["passed"] for row in rows),
        {"rows": rows},
    )


def _regression_check() -> ConformanceCheck:
    key = TuningKey(
        generation="generation-498",
        model="model-v1",
        backend="backend-v1",
        hardware="hardware-v1",
        quantization="q4-v1",
    )
    profile = deterministic_synthetic_profile(
        key,
        seed=498,
        acceptance_rate=0.98,
        accepted_length=8,
        draft_tokens=8,
        throughput_gain=-0.20,
    )
    guardrail = regression_guardrail(profile.metrics)
    tuning = auto_tune(profile, current_draft_tokens=8)
    cache_key = _cache_key()
    cache = DecisionCache(generation=cache_key.generation)
    cache.put(cache_key, {"strategy": "speculative", "draft_tokens": 8})
    disabled = cache.disable_for_regression(cache_key)
    lookup = cache.lookup(cache_key)
    passed = (
        profile.metrics.acceptance_rate == 0.98
        and guardrail.enabled is False
        and guardrail.reason == "throughput_regression"
        and tuning.enabled is False
        and tuning.reason == "throughput_regression"
        and disabled["outcome"] == "disabled"
        and disabled["reason"] == InvalidationReason.REGRESSION_DETECTED
        and lookup["outcome"] == "disabled"
    )
    return ConformanceCheck(
        "acceptance_throughput_regression_disable",
        passed,
        {
            "acceptance_rate": profile.metrics.acceptance_rate,
            "throughput_ratio": profile.metrics.throughput_ratio,
            "guardrail": guardrail.to_dict(),
            "tuning": tuning.to_dict(),
            "cache_outcome": lookup["outcome"],
            "cache_reason": lookup["reason"],
        },
    )


def _unavailable_telemetry_check() -> ConformanceCheck:
    pressure = score_pressure(
        PressureInputs(transfer=PressureMetric.unavailable(capability="transfer.cost")),
        acceptance_rate=0.99,
    )
    baseline_case = build_conformance_matrix()[0]
    baseline_result = SpeculationPolicy(baseline_case.configuration).decide(
        baseline_case.capabilities
    )
    plan = _local_execution_plan(baseline_case, baseline_result)
    telemetry = validate_telemetry_snapshot(
        _telemetry_snapshot(plan, level="minimal", sample_id="sample-498-minimal")
    )
    decision = validate_decision_receipt(
        _decision_receipt(
            baseline_case,
            baseline_result,
            telemetry,
            confidence=pressure.confidence,
        )
    )
    unavailable = telemetry["payload"]["unavailable"]
    expected_unavailable = {
        "ttft_ms",
        "acceptance_rate",
        "bandwidth_bytes_per_second",
        "transfer_bytes",
        "cache_pressure_ratio",
        "stage_timings_ms",
    }
    passed = (
        pressure.score is None
        and pressure.confidence == 0.0
        and pressure.recommendation.value == "baseline"
        and "TELEMETRY_INSUFFICIENT" in pressure.reason_codes
        and "TELEMETRY_LOW_CONFIDENCE" in pressure.reason_codes
        and set(unavailable) == expected_unavailable
        and decision["payload"]["confidence"] == pressure.confidence
    )
    return ConformanceCheck(
        "unavailable_telemetry_confidence",
        passed,
        {
            "pressure_score": pressure.score,
            "pressure_confidence": pressure.confidence,
            "pressure_recommendation": pressure.recommendation.value,
            "pressure_reason_codes": list(pressure.reason_codes),
            "unavailable_fields": sorted(unavailable),
            "decision_confidence": decision["payload"]["confidence"],
        },
    )


def _ownership_check() -> ConformanceCheck:
    declared = contract_manifest()["ownership"]
    fast = frozenset(declared["simplicio-fast"])
    local = frozenset(declared["simplicio-local"])
    shared = frozenset(declared["shared"])
    passed = (
        fast == _FAST_POLICY_FIELDS
        and local == _LOCAL_CONTRACT_FIELDS
        and not fast.intersection(local)
        and not fast.intersection(shared)
        and _LOCAL_EXECUTION_FIELDS.difference(fast) == _LOCAL_EXECUTION_FIELDS
        and DECISION_OWNER == "simplicio-fast"
        and EXECUTION_OWNER == "simplicio-local"
    )
    return ConformanceCheck(
        "ownership_boundaries",
        passed,
        {
            "fast": sorted(fast),
            "local": sorted(local | _LOCAL_EXECUTION_FIELDS),
            "shared": sorted(shared),
            "decision_owner": DECISION_OWNER,
            "execution_owner": EXECUTION_OWNER,
        },
    )


def ownership_boundaries() -> dict[str, tuple[str, ...]]:
    """Return the public ownership map used by the conformance harness."""

    return {
        "simplicio-fast": tuple(sorted(_FAST_POLICY_FIELDS)),
        "simplicio-local": tuple(
            sorted(_LOCAL_CONTRACT_FIELDS | _LOCAL_EXECUTION_FIELDS)
        ),
        "shared": tuple(sorted(contract_manifest()["ownership"]["shared"])),
    }


def run_conformance() -> ConformanceReport:
    """Run all issue #498 checks and return a deterministic report."""

    rows = _matrix_rows()
    checks = (
        ConformanceCheck(
            "strategy_matrix",
            all(row.passed for row in rows),
            {"cases": [row.to_dict() for row in rows]},
        ),
        ConformanceCheck(
            "decision_execution_plan_digest_binding",
            all(row.binding_validated for row in rows),
            {
                "bindings": [
                    {
                        "case": row.case,
                        "decision_digest": row.fast_decision_digest,
                        "execution_plan_digest": row.local_execution_plan_digest,
                        "binding_digest": row.binding_digest,
                    }
                    for row in rows
                ]
            },
        ),
        _drift_check(),
        _regression_check(),
        _unavailable_telemetry_check(),
        _ownership_check(),
    )
    return ConformanceReport(
        rows=rows,
        checks=checks,
        passed=all(check.passed for check in checks),
    )


def run_policy_conformance() -> ConformanceReport:
    """Named alias for callers that treat the harness as a policy check."""

    return run_conformance()


def assert_conformance() -> ConformanceReport:
    """Run the harness and raise with the stable report if it does not pass."""

    report = run_conformance()
    if not report.passed:
        failed = [check.name for check in report.checks if not check.passed]
        raise PolicyConformanceError("conformance_failed:" + ",".join(failed))
    return report


__all__ = [
    "POLICY_CONFORMANCE_SCHEMA",
    "ConformanceCase",
    "ConformanceCheck",
    "ConformanceReport",
    "ConformanceRow",
    "DecisionPlanDigestBinding",
    "PolicyConformanceError",
    "assert_conformance",
    "bind_decision_to_execution_plan",
    "build_conformance_matrix",
    "execution_plan_digest",
    "ownership_boundaries",
    "run_conformance",
    "run_policy_conformance",
    "verify_decision_execution_plan_binding",
]
