import unittest

from benchmarks.e2e_protocol import (
    ENGINES,
    METRICS,
    SCENARIOS,
    WORKLOADS,
    ProtocolError,
    blocked_run,
    preregister,
    sha256,
    unavailable,
    validate_dataset,
    validate_run,
)

HASH = "a" * 64


def complete_run(repetition=1):
    return {
        "schema": "simplicio.fast.e2e-benchmark/v1",
        "kind": "run",
        "status": "complete",
        "scenario": "S3_FULL_STACK",
        "engine": "rust",
        "workload": "crud",
        "slots": 1,
        "repetition": repetition,
        "corpus_sha256": HASH,
        "source_commit": "deadbeef",
        "environment_sha256": "b" * 64,
        "component_versions": {"fast": {"version": "2.0.10", "commit": "deadbeef"}},
        "metrics": {name: {"value": 1, "reason": None} for name in METRICS},
    }


class E2EProtocolTest(unittest.TestCase):
    def test_preregistration_is_deterministic_and_complete(self):
        left = preregister(seed=163)
        right = preregister(seed=163)
        self.assertEqual(left, right)
        expected_runs = (
            sum(len(ENGINES[scenario]) for scenario in SCENARIOS)
            * len(WORKLOADS)
            * 3
            * 10
        )
        self.assertEqual(expected_runs, len(left["runs"]))
        self.assertEqual(64, len(left["plan_sha256"]))

    def test_minimum_ten_repetitions_is_enforced(self):
        with self.assertRaisesRegex(ProtocolError, "at_least_10"):
            preregister(seed=1, repetitions=9)

    def test_null_requires_machine_readable_reason(self):
        run = complete_run()
        run["status"] = "partial"
        run["metrics"]["ttft_ms"] = {"value": None, "reason": None}
        with self.assertRaisesRegex(ProtocolError, "metric_reason_invalid:ttft_ms"):
            validate_run(run)

    def test_null_is_never_coerced_to_zero(self):
        metric = unavailable("provider_telemetry_unavailable")
        self.assertIsNone(metric["value"])
        self.assertNotEqual(0, metric["value"])

    def test_blocked_run_preserves_blocked_state(self):
        plan_run = preregister(seed=1)["runs"][0]
        run = blocked_run(plan_run, "component_unavailable", "runtime not installed")
        run.update(
            {
                "corpus_sha256": HASH,
                "source_commit": "deadbeef",
                "environment_sha256": "b" * 64,
                "component_versions": {"fast": {"version": "2.0.10"}},
            }
        )
        validate_run(run)
        self.assertEqual("blocked", run["status"])
        self.assertTrue(
            all(metric["value"] is None for metric in run["metrics"].values())
        )

    def test_dataset_rejects_identity_drift(self):
        runs = [complete_run(i) for i in range(1, 11)]
        runs[-1]["corpus_sha256"] = "c" * 64
        with self.assertRaisesRegex(ProtocolError, "frozen_identity_drift"):
            validate_dataset(
                {"schema": runs[0]["schema"], "kind": "dataset", "runs": runs}
            )

    def test_dataset_reports_underfilled_cells_without_inventing_runs(self):
        runs = [complete_run(i) for i in range(1, 10)]
        result = validate_dataset(
            {"schema": runs[0]["schema"], "kind": "dataset", "runs": runs}
        )
        self.assertEqual(1, len(result["underfilled_cells"]))
        self.assertEqual(9, result["runs"])

    def test_dataset_with_ten_repetitions_is_valid(self):
        runs = [complete_run(i) for i in range(1, 11)]
        document = {"schema": runs[0]["schema"], "kind": "dataset", "runs": runs}
        result = validate_dataset(document)
        self.assertEqual([], result["underfilled_cells"])
        self.assertEqual(sha256(document), result["dataset_sha256"])


if __name__ == "__main__":
    unittest.main()
