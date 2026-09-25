from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from simplicio_fast.contract_surface import digest_for, validate_decision_receipt
from simplicio_fast.policy_engine import (
    POLICY_ENGINE_SCHEMA,
    PolicyEngine,
    PolicyEngineConfig,
    PolicyEngineError,
)
from simplicio_fast.pressure_inputs import (
    BandwidthPressure,
    CachePressure,
    ConcurrencyPressure,
    Headroom,
    KVPressure,
    Placement,
    PlacementCandidate,
    PressureInputs,
    PressureMetric,
    Residency,
    ThroughputCost,
    TransferPressure,
)
from simplicio_fast.speculation_policy import (
    SpeculationCapabilities,
    StrategyCapability,
)
from simplicio_fast.speculation_profiler import (
    TuningKey,
    deterministic_synthetic_profile,
)

ROOT = Path(__file__).parents[1]
EXAMPLES = json.loads(
    (ROOT / "contracts/fast-local/v1/examples.json").read_text(encoding="utf-8")
)


def metric(value, capability: str, confidence: float = 1.0):
    return PressureMetric.available(
        value,
        capability=capability,
        confidence=confidence,
    )


def low_pressure_inputs(*, residency: Residency | None = None) -> PressureInputs:
    return PressureInputs(
        bandwidth=metric(BandwidthPressure(0.20), "memory.bandwidth"),
        cache=metric(CachePressure(0.20), "cache.llc"),
        transfer=metric(TransferPressure(0.10), "transfer.cost"),
        headroom=metric(Headroom(ram=0.80, vram=0.80), "memory.headroom"),
        kv=metric(KVPressure(0.20), "kv.pressure"),
        concurrency=metric(ConcurrencyPressure(0.20), "runtime.concurrency"),
        throughput=metric(ThroughputCost(0.10), "throughput.cost"),
        residency=(
            metric(residency, "placement.residency") if residency is not None else None
        ),
    )


def profile(*, generation: str = "local-generation-001", throughput_gain: float = 0.12):
    return deterministic_synthetic_profile(
        TuningKey(
            generation=generation,
            model="model-a",
            backend="cuda",
            hardware="gpu-a",
            quantization="q4",
        ),
        seed=494,
        throughput_gain=throughput_gain,
    )


def capabilities() -> SpeculationCapabilities:
    return SpeculationCapabilities(draft=StrategyCapability(True, 1.20))


def resign_telemetry(snapshot: dict, **generation_updates: str) -> dict:
    updated = deepcopy(snapshot)
    updated["generation"].update(generation_updates)
    unsigned = deepcopy(updated)
    unsigned["payload"].pop("telemetry_digest")
    updated["payload"]["telemetry_digest"] = digest_for(unsigned)
    return updated


class PolicyEngine494Test(unittest.TestCase):
    def test_policy_decision_composes_all_pressure_inputs_and_contract_receipt(self):
        inputs = low_pressure_inputs(
            residency=Residency(
                (
                    PlacementCandidate("gpu0", Placement.SAME_GPU),
                    PlacementCandidate("cpu", Placement.CPU_DRAFT),
                )
            )
        )
        decision = PolicyEngine().decide(
            EXAMPLES["telemetry_snapshot"],
            inputs,
            capabilities=capabilities(),
            profile=profile(),
        )

        self.assertEqual(decision.selected.value, "draft")
        self.assertTrue(decision.enabled)
        self.assertEqual(decision.placement, "gpu0")
        self.assertEqual(
            decision.pressure.used_metrics,
            (
                "bandwidth",
                "cache",
                "transfer",
                "headroom",
                "kv",
                "concurrency",
                "throughput",
            ),
        )
        self.assertEqual(decision.confidence, 1.0)
        self.assertEqual(decision.to_dict()["schema"], POLICY_ENGINE_SCHEMA)
        self.assertEqual(validate_decision_receipt(decision.receipt), decision.receipt)

    def test_high_bandwidth_and_transfer_pressure_override_acceptance(self):
        inputs = PressureInputs(
            bandwidth=metric(BandwidthPressure(0.95), "memory.bandwidth"),
            cache=metric(CachePressure(0.20), "cache.llc"),
            transfer=metric(TransferPressure(0.90), "transfer.cost"),
            headroom=metric(Headroom(ram=0.80, vram=0.80), "memory.headroom"),
            kv=metric(KVPressure(0.20), "kv.pressure"),
            concurrency=metric(ConcurrencyPressure(0.20), "runtime.concurrency"),
        )
        decision = PolicyEngine().decide(
            EXAMPLES["telemetry_snapshot"],
            inputs,
            capabilities=capabilities(),
            profile=profile(),
        )

        self.assertFalse(decision.enabled)
        self.assertEqual(decision.selected.value, "baseline")
        self.assertIn("BANDWIDTH_PRESSURE_HIGH", decision.reason_codes)
        self.assertIn("TRANSFER_PRESSURE_HIGH", decision.reason_codes)

    def test_cache_reuses_same_generation_and_invalidates_on_generation_change(self):
        engine = PolicyEngine()
        inputs = low_pressure_inputs()
        first = engine.decide(
            EXAMPLES["telemetry_snapshot"],
            inputs,
            capabilities=capabilities(),
            profile=profile(),
        )
        second = engine.decide(
            EXAMPLES["telemetry_snapshot"],
            inputs,
            capabilities=capabilities(),
            profile=profile(),
        )
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.cache_receipts[-1]["reason"], "cache_hit")

        next_snapshot = resign_telemetry(
            EXAMPLES["telemetry_snapshot"],
            generation_id="local-generation-002",
            source_revision="b" * 40,
        )
        next_decision = engine.decide(
            next_snapshot,
            inputs,
            capabilities=capabilities(),
            profile=profile(generation="local-generation-002"),
        )
        activation = next_decision.cache_receipts[0]
        self.assertEqual(activation["operation"], "activate_generation")
        self.assertEqual(activation["reason"], "generation_advanced")
        self.assertTrue(activation["invalidated_key_digests"])
        self.assertFalse(next_decision.cache_hit)

    def test_regression_guardrail_disables_cached_speculation(self):
        engine = PolicyEngine()
        inputs = low_pressure_inputs()
        engine.decide(
            EXAMPLES["telemetry_snapshot"],
            inputs,
            capabilities=capabilities(),
            profile=profile(),
        )
        decision = engine.decide(
            EXAMPLES["telemetry_snapshot"],
            inputs,
            capabilities=capabilities(),
            profile=profile(throughput_gain=-0.20),
        )

        self.assertEqual(decision.selected.value, "baseline")
        self.assertFalse(decision.enabled)
        self.assertIn("throughput_regression", decision.reason_codes)
        self.assertTrue(
            any(
                receipt.get("operation") == "disable"
                for receipt in decision.cache_receipts
            )
        )

    def test_low_confidence_telemetry_falls_back_without_synthetic_zeroes(self):
        decision = PolicyEngine().decide(
            EXAMPLES["telemetry_snapshot"],
            PressureInputs(
                bandwidth=metric(BandwidthPressure(0.10), "memory.bandwidth", 0.50),
                cache=metric(CachePressure(0.10), "cache.llc", 0.50),
            ),
            capabilities=capabilities(),
        )

        self.assertFalse(decision.enabled)
        self.assertEqual(decision.pressure.score, 10.0)
        self.assertIn("TELEMETRY_LOW_CONFIDENCE", decision.reason_codes)
        self.assertIn("transfer", decision.pressure.unavailable_metrics)

    def test_placement_work_is_bounded(self):
        candidates = tuple(
            PlacementCandidate(f"gpu-{index}", Placement.SAME_GPU)
            for index in range(17)
        )
        with self.assertRaisesRegex(
            PolicyEngineError, "placement_candidates_exceed_bound"
        ):
            PolicyEngine(config=PolicyEngineConfig(max_placement_candidates=16)).decide(
                EXAMPLES["telemetry_snapshot"],
                low_pressure_inputs(residency=Residency(candidates)),
            )


if __name__ == "__main__":
    unittest.main()
