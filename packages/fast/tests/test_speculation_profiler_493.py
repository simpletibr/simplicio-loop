from __future__ import annotations

import json
import unittest

from simplicio_fast.speculation_profiler import (
    PROFILE_SCHEMA,
    TuningBounds,
    TuningKey,
    TuningRecordStore,
    adapt_telemetry,
    auto_tune,
    deterministic_synthetic_profile,
    regression_guardrail,
)


def key(**overrides: str) -> TuningKey:
    values = {
        "generation": "gen-493",
        "model": "model-a",
        "backend": "cuda",
        "hardware": "gpu-a",
        "quantization": "q4",
    }
    values.update(overrides)
    return TuningKey(**values)


class SpeculationProfiler493Test(unittest.TestCase):
    def test_synthetic_profile_is_deterministic_and_captures_receipt_metrics(
        self,
    ) -> None:
        first = deterministic_synthetic_profile(key(), seed=7)
        second = deterministic_synthetic_profile(key(), seed=7)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.classification, "SYNTHETIC")
        self.assertEqual(first.to_dict()["schema"], PROFILE_SCHEMA)
        self.assertEqual(
            set(first.to_dict()["metrics"]),
            {
                "baseline_tok_s",
                "speculative_tok_s",
                "baseline_ttft_ms",
                "speculative_ttft_ms",
                "acceptance_rate",
                "accepted_length",
                "draft_cost_ms",
                "verification_cost_ms",
                "baseline_memory_mb",
                "speculative_memory_mb",
                "memory_delta_mb",
                "fallback_reason",
                "sample_count",
                "throughput_ratio",
                "ttft_ratio",
            },
        )
        self.assertEqual(first.to_json(), second.to_json())

    def test_adapter_accepts_one_narrow_machine_mapping(self) -> None:
        profile = adapt_telemetry(
            key(),
            {
                "baseline_tok_s": 100,
                "speculative_tok_s": 120,
                "baseline_ttft_ms": 50,
                "speculative_ttft_ms": 45,
                "acceptance_rate": 0.9,
                "accepted_length": 4,
                "draft_cost_ms": 2,
                "verification_cost_ms": 3,
                "baseline_memory_mb": 1000,
                "speculative_memory_mb": 1010,
                "sample_count": 3,
            },
        )
        self.assertEqual(profile.metrics.throughput_ratio, 1.2)
        self.assertEqual(profile.metrics.memory_delta_mb, 10)
        json.dumps(profile.to_dict())

    def test_auto_tune_is_bounded_and_uses_acceptance_signal(self) -> None:
        profile = deterministic_synthetic_profile(
            key(),
            acceptance_rate=0.95,
            accepted_length=8,
            draft_tokens=8,
        )
        decision = auto_tune(
            profile,
            current_draft_tokens=8,
            current_acceptance_threshold=0.90,
            bounds=TuningBounds(
                min_draft_tokens=2,
                max_draft_tokens=8,
                min_acceptance_threshold=0.50,
                max_acceptance_threshold=0.90,
            ),
        )
        self.assertTrue(decision.enabled)
        self.assertEqual(decision.draft_tokens, 8)
        self.assertEqual(decision.acceptance_threshold, 0.90)
        self.assertEqual(decision.reason, "tuned")

    def test_regression_guardrail_disables_speculation(self) -> None:
        profile = deterministic_synthetic_profile(
            key(), baseline_tok_s=100, throughput_gain=-0.20
        )
        guardrail = regression_guardrail(profile.metrics)
        self.assertFalse(guardrail.enabled)
        self.assertEqual(guardrail.reason, "throughput_regression")
        decision = auto_tune(profile)
        self.assertFalse(decision.enabled)
        self.assertEqual(decision.reason, "throughput_regression")

    def test_fallback_reason_is_preserved_and_guardrail_is_fail_closed(self) -> None:
        profile = deterministic_synthetic_profile(
            key(), fallback_reason="draft_unavailable"
        )
        self.assertEqual(profile.metrics.fallback_reason, "draft_unavailable")
        decision = auto_tune(profile)
        self.assertFalse(decision.enabled)
        self.assertEqual(decision.reason, "fallback_observed")

    def test_tuning_records_are_isolated_by_generation_model_backend_hardware(
        self,
    ) -> None:
        store = TuningRecordStore()
        first = deterministic_synthetic_profile(key(generation="gen-1"), seed=1)
        second = deterministic_synthetic_profile(key(generation="gen-2"), seed=1)
        store.record(first)
        store.record(second)
        self.assertEqual(len(store), 2)
        self.assertEqual(store.get(first.key).key.generation, "gen-1")
        self.assertEqual(store.get(second.key).key.generation, "gen-2")
        self.assertEqual(len(store.to_dict()["records"]), 2)


if __name__ == "__main__":
    unittest.main()
