from __future__ import annotations

import json
import sys
import unittest

from simplicio_fast.policy_conformance import (
    POLICY_CONFORMANCE_SCHEMA,
    PolicyConformanceError,
    assert_conformance,
    bind_decision_to_execution_plan,
    build_conformance_matrix,
    execution_plan_digest,
    ownership_boundaries,
    run_conformance,
    verify_decision_execution_plan_binding,
)


class PolicyConformance498Test(unittest.TestCase):
    def test_matrix_covers_the_five_policy_strategies(self) -> None:
        matrix = build_conformance_matrix()
        self.assertEqual(
            [case.name for case in matrix],
            ["baseline", "ngram", "draft", "dflash", "mtp"],
        )
        self.assertEqual(
            [case.expected_strategy.value for case in matrix],
            ["baseline", "ngram", "draft", "dflash", "mtp"],
        )

    def test_harness_is_deterministic_and_passes_without_local(self) -> None:
        first = run_conformance()
        second = run_conformance()

        self.assertTrue(first.passed)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict()["schema"], POLICY_CONFORMANCE_SCHEMA)
        self.assertEqual(first.to_json(), second.to_json())
        self.assertNotIn("simplicio_local", sys.modules)
        json.loads(first.to_json())

    def test_report_contains_each_requested_conformance_check(self) -> None:
        report = run_conformance()
        self.assertEqual(
            [check.name for check in report.checks],
            [
                "strategy_matrix",
                "decision_execution_plan_digest_binding",
                "drift_invalidation",
                "acceptance_throughput_regression_disable",
                "unavailable_telemetry_confidence",
                "ownership_boundaries",
            ],
        )
        self.assertTrue(all(check.passed for check in report.checks))

    def test_decision_and_execution_plan_digests_are_bound(self) -> None:
        report = run_conformance()
        row = report.rows[2]
        plan = {
            "plan_id": "plan-test",
            "reason_codes": ["execution_owner:simplicio-local"],
        }
        plan["digest"] = execution_plan_digest(plan)
        binding = bind_decision_to_execution_plan(
            row.fast_decision_digest,
            plan,
        )
        self.assertTrue(
            verify_decision_execution_plan_binding(
                binding, row.fast_decision_digest, plan
            )
        )
        tampered = {**plan, "reason_codes": ["tampered"]}
        self.assertFalse(
            verify_decision_execution_plan_binding(
                binding, row.fast_decision_digest, tampered
            )
        )

    def test_plan_digest_rejects_tampering(self) -> None:
        with self.assertRaisesRegex(
            PolicyConformanceError, "execution_plan_digest_mismatch"
        ):
            execution_plan_digest(
                {
                    "plan_id": "plan-test",
                    "reason_codes": ["execution_owner:simplicio-local"],
                    "digest": "sha256:" + "0" * 64,
                }
            )

    def test_ownership_map_keeps_model_kv_kernels_and_execution_local(self) -> None:
        ownership = ownership_boundaries()
        self.assertIn("policy_decisions", ownership["simplicio-fast"])
        self.assertIn("decision_receipts", ownership["simplicio-fast"])
        for field in ("model", "kv_cache", "kernels", "execution"):
            self.assertIn(field, ownership["simplicio-local"])
            self.assertNotIn(field, ownership["simplicio-fast"])

    def test_assert_conformance_returns_the_verified_report(self) -> None:
        report = assert_conformance()
        self.assertTrue(report.passed)
        self.assertEqual(report.report_digest, report.to_dict()["report_digest"])


if __name__ == "__main__":
    unittest.main()
