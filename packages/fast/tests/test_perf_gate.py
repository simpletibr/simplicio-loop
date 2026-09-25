from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.perf_gate import _read, evaluate, main


def receipt(
    *,
    hot: float = 100.0,
    speedup: float = 1.5,
    tokens: float = 75.0,
    repetitions: int = 10,
) -> dict:
    return {
        "schema": "simplicio.fast.e2e-benchmark/v1",
        "environment": {
            "schema": "simplicio.fast.environment/v1",
            "python": "3.14",
            "python_implementation": "CPython",
            "platform": "test",
            "machine": "test-machine",
            "processor": None,
            "executable": "python",
            "cpu_count": 4,
        },
        "workload": {"files": 50, "functions_per_file": 20, "term": "task_7"},
        "totals": {
            "fast_python_alteration_wall_ms": hot,
            "alteration_speedup_hot": speedup,
            "estimated_token_savings_percent": tokens,
        },
        "scenarios": {
            "without_fast_alteration": {
                "repetitions": repetitions,
                "wall_ms": {
                    "median": 10.0,
                    "p95": 12.0,
                    "p99": 13.0,
                    "samples": [10.0] * repetitions,
                },
            },
            "fast_python_alteration": {
                "repetitions": repetitions,
                "wall_ms": {
                    "median": 9.0,
                    "p95": 11.0,
                    "p99": 12.0,
                    "samples": [9.0] * repetitions,
                },
            },
            "fast_python_alteration_refresh": {
                "repetitions": repetitions,
                "wall_ms": {
                    "median": 20.0,
                    "p95": 22.0,
                    "p99": 23.0,
                    "samples": [20.0] * repetitions,
                },
            },
            "full_standalone": {"status": "blocked", "reason": "runtime_missing"},
            "loop_standalone": {"status": "blocked", "reason": "runtime_missing"},
        },
    }


class PerfGateTest(unittest.TestCase):
    def test_improvement_is_reported_without_treating_blocked_cells_as_pass(
        self,
    ) -> None:
        result = evaluate(receipt(), receipt(hot=90.0, speedup=1.6, tokens=80.0))
        self.assertEqual("inconclusive", result["status"])
        self.assertEqual(2, len(result["blocked_scenarios"]))

    def test_regression_exceeding_budget_is_reported(self) -> None:
        result = evaluate(receipt(), receipt(hot=120.0, speedup=1.0, tokens=60.0))
        self.assertEqual("regressed", result["status"])
        self.assertTrue(any(check["status"] == "fail" for check in result["checks"]))

    def test_invalid_percentile_order_is_inconclusive(self) -> None:
        candidate = copy.deepcopy(receipt())
        candidate["scenarios"]["fast_python_alteration"]["wall_ms"]["p95"] = 8.0
        result = evaluate(receipt(), candidate)
        self.assertEqual("inconclusive", result["status"])
        self.assertEqual("percentile_metrics_invalid", result["reason"])

    def test_missing_or_insufficient_repetitions_is_inconclusive(self) -> None:
        candidate = receipt(repetitions=9)
        result = evaluate(receipt(), candidate)
        self.assertEqual("inconclusive", result["status"])
        self.assertEqual("minimum_repetitions_not_met", result["reason"])

    def test_missing_metric_is_not_coerced_to_zero(self) -> None:
        candidate = copy.deepcopy(receipt())
        del candidate["totals"]["alteration_speedup_hot"]
        result = evaluate(receipt(), candidate)
        self.assertEqual("inconclusive", result["status"])
        speedup = next(
            check
            for check in result["checks"]
            if check["metric"] == "alteration_speedup_hot"
        )
        self.assertEqual("inconclusive", speedup["status"])

    def test_environment_drift_is_inconclusive_before_metric_budget(self) -> None:
        candidate = copy.deepcopy(receipt())
        candidate["environment"]["platform"] = "different-host"
        result = evaluate(receipt(), candidate)
        self.assertEqual("inconclusive", result["status"])
        self.assertEqual("environment_mismatch", result["reason"])
        self.assertEqual("test", result["baseline"]["platform"])
        self.assertEqual("different-host", result["candidate"]["platform"])

    def test_invalid_environment_schema_is_inconclusive(self) -> None:
        candidate = copy.deepcopy(receipt())
        candidate["environment"]["schema"] = "wrong"
        result = evaluate(receipt(), candidate)
        self.assertEqual("inconclusive", result["status"])
        self.assertEqual("environment_invalid", result["reason"])

    def test_missing_environment_metadata_is_inconclusive(self) -> None:
        candidate = copy.deepcopy(receipt())
        del candidate["environment"]
        result = evaluate(receipt(), candidate)
        self.assertEqual("inconclusive", result["status"])
        self.assertEqual("environment_invalid", result["reason"])

    def test_workload_and_totals_mismatch_are_inconclusive(self) -> None:
        candidate = copy.deepcopy(receipt())
        candidate["workload"]["files"] = 51
        self.assertEqual("workload_mismatch", evaluate(receipt(), candidate)["reason"])

        candidate = copy.deepcopy(receipt())
        candidate["totals"] = None
        self.assertEqual("totals_missing", evaluate(receipt(), candidate)["reason"])

    def test_missing_scenarios_are_inconclusive(self) -> None:
        candidate = copy.deepcopy(receipt())
        candidate["scenarios"] = None
        self.assertEqual(
            "minimum_repetitions_not_met", evaluate(receipt(), candidate)["reason"]
        )

        candidate = copy.deepcopy(receipt())
        candidate["scenarios"]["fast_python_alteration"] = None
        self.assertEqual(
            "minimum_repetitions_not_met", evaluate(receipt(), candidate)["reason"]
        )

    def test_reader_rejects_unreadable_and_wrong_schema_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt_unreadable"):
                _read(path)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt_schema_mismatch"):
                _read(path)
            with self.assertRaisesRegex(ValueError, "receipt_unreadable"):
                _read(Path(directory) / "missing.json")

    def test_cli_emits_and_writes_gate_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            output_path = root / "gate.json"
            payload = receipt()
            baseline.write_text(json.dumps(payload), encoding="utf-8")
            candidate.write_text(json.dumps(payload), encoding="utf-8")
            output = io.StringIO()
            argv = [
                "perf_gate.py",
                "--baseline",
                str(baseline),
                "--candidate",
                str(candidate),
                "--json-out",
                str(output_path),
            ]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                self.assertEqual(2, main())
            self.assertEqual(
                json.loads(output.getvalue()),
                json.loads(output_path.read_text(encoding="utf-8")),
            )

            candidate.write_text("{}", encoding="utf-8")
            with (
                patch.object(sys, "argv", argv[:-2]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(2, main())


if __name__ == "__main__":
    unittest.main()
