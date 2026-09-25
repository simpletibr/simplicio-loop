from __future__ import annotations

import unittest

from simplicio_fast.pareto_policy import (
    DECISION_OWNER,
    EXECUTION_OWNER,
    INVALIDATION_SCHEMA,
    PARETO_POLICY_SCHEMA,
    RECEIPT_SCHEMA,
    GenerationInvalidationHook,
    ParetoPolicy,
    ParetoPolicyError,
    PolicyContext,
    Profile,
    RepresentationCandidate,
    RepresentationKind,
    invalidate_on_generation_change,
    select_representation,
)


def candidate(
    name: str,
    representation: str,
    quality: float,
    resident: int,
    peak: int,
    *,
    tok_s: float = 80.0,
    ttft: float = 40.0,
    **evidence: object,
) -> RepresentationCandidate:
    return RepresentationCandidate(
        name,
        representation,
        quality,
        resident,
        peak,
        resident / 40,
        resident / 80,
        tok_s,
        ttft,
        evidence=evidence,
    )


class ParetoPolicy499Test(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = (
            candidate(
                "dense-v1",
                "dense quant",
                0.97,
                160,
                200,
                tok_s=80,
                ttft=40,
                transfer_bytes=120,
                transfer_ms=4,
                disk_bytes=900,
                disk_ms=8,
                energy_joules=3.0,
            ),
            candidate(
                "sqtn-v1",
                "SQTN",
                0.93,
                80,
                100,
                tok_s=70,
                ttft=45,
                transfer_bytes=80,
                transfer_ms=3,
                disk_bytes=500,
                disk_ms=5,
                energy_joules=1.5,
            ),
            candidate(
                "mixed-v1",
                "mixed",
                0.96,
                120,
                140,
                tok_s=90,
                ttft=30,
                transfer_bytes=100,
                transfer_ms=2,
                disk_bytes=700,
                disk_ms=6,
                energy_joules=2.0,
            ),
        )

    def test_profiles_select_from_thresholded_pareto_frontier(self) -> None:
        quality = ParetoPolicy("quality", quality_threshold=0.95).decide(
            self.candidates, generation="generation-1"
        )
        memory = ParetoPolicy("memory", quality_threshold=0.95).decide(
            self.candidates, generation="generation-1"
        )
        balanced = ParetoPolicy("balanced", quality_threshold=0.90).decide(
            self.candidates, generation="generation-1"
        )
        minimal = ParetoPolicy("minimal", quality_threshold=0.90).decide(
            self.candidates, generation="generation-1"
        )

        self.assertEqual(quality.status, "selected")
        self.assertEqual(quality.selected_id, "dense-v1")
        self.assertEqual(memory.selected_id, "mixed-v1")
        self.assertEqual(balanced.selected_id, "mixed-v1")
        self.assertEqual(minimal.selected_id, "sqtn-v1")
        self.assertNotIn("sqtn-v1", quality.receipt.pareto_frontier)
        self.assertEqual(quality.receipt.to_dict()["decision_owner"], DECISION_OWNER)
        self.assertEqual(quality.receipt.to_dict()["execution_owner"], EXECUTION_OWNER)

    def test_quality_threshold_is_a_hard_gate(self) -> None:
        result = ParetoPolicy("balanced", quality_threshold=0.965).decide(
            self.candidates, generation="generation-2"
        )

        self.assertEqual(result.selected_id, "dense-v1")
        facts = {fact["candidate_id"]: fact for fact in result.receipt.candidates}
        self.assertFalse(facts["mixed-v1"]["hard_filters"]["quality_threshold"])
        self.assertEqual(
            facts["mixed-v1"]["selection_reason"], "quality_below_threshold"
        )
        self.assertFalse(facts["sqtn-v1"]["hard_filters"]["quality_threshold"])

    def test_threshold_failure_and_budget_failure_are_honest_cannot_fit(self) -> None:
        threshold_failure = ParetoPolicy("balanced", quality_threshold=0.99).decide(
            self.candidates, generation="generation-3"
        )
        budget_failure = ParetoPolicy("balanced", quality_threshold=0.90).decide(
            self.candidates,
            generation="generation-4",
            resident_budget_bytes=70,
            peak_budget_bytes=90,
        )

        self.assertEqual(threshold_failure.status, "cannot_fit")
        self.assertIsNone(threshold_failure.selected)
        self.assertEqual(threshold_failure.reason, "quality_threshold_unmet")
        self.assertEqual(budget_failure.status, "cannot_fit")
        self.assertIsNone(budget_failure.selected)
        self.assertEqual(budget_failure.reason, "no_candidate_fits_constraints")

    def test_unknown_metrics_do_not_become_zero_when_budget_is_declared(self) -> None:
        result = ParetoPolicy(quality_threshold=0.8).decide(
            [RepresentationCandidate("unknown", "mixed", 0.9)],
            generation="generation-5",
            peak_budget_bytes=100,
        )

        self.assertEqual(result.status, "cannot_fit")
        fact = result.receipt.candidates[0]
        self.assertFalse(fact["hard_filters"]["peak_budget"])
        self.assertEqual(fact["selection_reason"], "peak_budget_unknown")

    def test_evidence_aliases_are_preserved_in_receipts(self) -> None:
        measured = RepresentationCandidate.from_mapping(
            {
                "candidate_id": "evidence-v1",
                "kind": "dense-quant",
                "quality": 0.9,
                "resident_bytes": 40,
                "peak_bytes": 50,
                "bytes_per_token": 2,
                "kv_bytes_per_token": 1,
                "tok_s": 100,
                "ttft": 12,
                "evidence": {
                    "transfer": {"bytes": 10, "ms": 2},
                    "disk": {"bytes": 20, "milliseconds": 3},
                    "energy": {"joules": 0.5},
                },
            }
        )
        # The mapping constructor is the wire-facing form; the explicit
        # constructor remains strict and typed.
        mapped = RepresentationCandidate.from_mapping(measured.to_dict())
        result = ParetoPolicy().decide(
            [mapped],
            PolicyContext(
                "generation-6",
                hardware_fingerprint="gpu-a",
                context_fingerprint="ctx-a",
                workload_fingerprint="interactive",
            ),
        )

        metrics = result.receipt.candidates[0]["metrics"]
        self.assertEqual(mapped.representation, RepresentationKind.DENSE_QUANT)
        self.assertEqual(metrics["transfer_bytes"], 10)
        self.assertEqual(metrics["transfer_ms"], 2.0)
        self.assertEqual(metrics["disk_bytes"], 20)
        self.assertEqual(metrics["disk_ms"], 3.0)
        self.assertEqual(metrics["energy_joules"], 0.5)

    def test_fingerprints_are_hard_identity_gates(self) -> None:
        mismatched = RepresentationCandidate(
            "gpu-specific",
            "mixed",
            0.95,
            50,
            60,
            hardware_fingerprint="gpu-b",
        )
        result = ParetoPolicy(quality_threshold=0.9).decide(
            [mismatched],
            generation="generation-7",
            hardware_fingerprint="gpu-a",
            context_fingerprint="ctx-a",
            workload_fingerprint="batch",
        )

        self.assertEqual(result.status, "cannot_fit")
        self.assertEqual(result.reason, "no_candidate_fits_constraints")
        self.assertFalse(
            result.receipt.candidates[0]["hard_filters"]["hardware_fingerprint"]
        )

    def test_decision_and_receipt_are_deterministic_and_generation_bound(self) -> None:
        first = select_representation(
            reversed(self.candidates),
            profile=Profile.BALANCED,
            quality_threshold=0.9,
            generation="generation-8",
            hardware_fingerprint="gpu-a",
            context_fingerprint="ctx-a",
            workload_fingerprint="interactive",
        )
        second = select_representation(
            self.candidates,
            profile="balanced",
            quality_threshold=0.9,
            generation="generation-8",
            hardware_fingerprint="gpu-a",
            context_fingerprint="ctx-a",
            workload_fingerprint="interactive",
        )

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.receipt.to_dict()["schema"], RECEIPT_SCHEMA)
        self.assertEqual(first.to_dict()["schema"], PARETO_POLICY_SCHEMA)
        self.assertTrue(first.is_valid_for_generation("generation-8"))
        self.assertFalse(first.is_valid_for_generation("generation-9"))
        self.assertEqual(
            first.receipt.invalidation_hook.check("generation-9")["schema"],
            INVALIDATION_SCHEMA,
        )

    def test_standalone_invalidation_hook_reports_match_and_drift(self) -> None:
        hook = GenerationInvalidationHook("generation-a", "sha256:key")

        self.assertFalse(hook.check("generation-b")["valid"])
        self.assertTrue(hook.check("generation-a")["valid"])
        self.assertTrue(
            invalidate_on_generation_change(
                "generation-a", "generation-b", decision_key="sha256:key"
            )["invalidated"]
        )

    def test_invalid_profiles_and_quality_values_fail_closed(self) -> None:
        with self.assertRaisesRegex(ParetoPolicyError, "profile_invalid"):
            ParetoPolicy("fast")
        with self.assertRaisesRegex(ParetoPolicyError, "quality_threshold_invalid"):
            ParetoPolicy(quality_threshold=1.1)
        with self.assertRaisesRegex(ParetoPolicyError, "candidate_quality_invalid"):
            RepresentationCandidate("bad", "mixed", 1.1)
        with self.assertRaisesRegex(ParetoPolicyError, "generation_required"):
            ParetoPolicy().decide(self.candidates)


if __name__ == "__main__":
    unittest.main()
