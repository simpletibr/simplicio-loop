from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import runtime_scale_benchmark as rsb


class RuntimeScaleBenchmarkTest(unittest.TestCase):
    def test_fixture_manifest_generates_reference_scale_tree(self) -> None:
        spec = rsb.load_fixture_spec().with_overrides(total_files=64, measured_runs=2, warmup_runs=1)
        with tempfile.TemporaryDirectory() as tmp:
            payload = rsb.generate_runtime_scale_corpus(Path(tmp), spec)
            self.assertEqual(payload["file_count"], 64)
            self.assertEqual(
                json.loads((Path(tmp) / ".simplicio-loop" / "project-map.json").read_text(encoding="utf-8"))["schema"],
                "simplicio.project-map/v1",
            )
            retrieval_path = Path(payload["retrieval_index_path"])
            self.assertTrue(retrieval_path.is_file())
            self.assertTrue((Path(tmp) / "src/runtime_scale/indexed_dispatch.py").is_file())

    def test_calibration_marks_unverified_when_absolute_budget_is_missed(self) -> None:
        indexed = {
            "duration_ms": {"p95": 50.0},
            "files_opened": {"p95": 3.0},
            "bytes_read": {"p95": 1000.0},
            "result_tokens": {"p95": 200.0},
        }
        legacy = {
            "duration_ms": {"p95": 70.0},
            "files_opened": {"p95": 5.0},
            "bytes_read": {"p95": 2000.0},
            "result_tokens": {"p95": 300.0},
        }
        calibration = rsb._calibrated_status(indexed, legacy, rsb.BenchmarkTargets(35.0, 1.15))
        self.assertEqual(calibration["status"], "UNVERIFIED")
        self.assertGreater(calibration["normalized_budget"]["indexed_p95_vs_target"], 1.0)
        self.assertTrue(calibration["reasons"])

    def test_write_json_persists_receipt(self) -> None:
        spec = rsb.load_fixture_spec().with_overrides(total_files=64, measured_runs=2, warmup_runs=1)
        with tempfile.TemporaryDirectory() as tmp:
            payload = rsb.run_runtime_scale_benchmark(spec, root=Path(tmp))
            target = Path(tmp) / "runtime-scale-benchmark.json"
            target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            persisted = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema"], "simplicio.runtime-scale-benchmark/v1")
        self.assertIn("calibration", persisted)

    def test_benchmark_payload_reports_indexed_and_legacy_sections(self) -> None:
        spec = rsb.load_fixture_spec().with_overrides(
            total_files=96,
            measured_runs=3,
            warmup_runs=1,
            targets={"indexed_p95_ms": 0.0001, "indexed_vs_legacy_speedup_ratio": 999.0},
        )
        with tempfile.TemporaryDirectory() as tmp:
            payload = rsb.run_runtime_scale_benchmark(spec, root=Path(tmp))
        self.assertEqual(payload["schema"], rsb.SCHEMA)
        self.assertEqual(payload["fixture"]["file_count"], 96)
        self.assertEqual(payload["calibration"]["status"], "UNVERIFIED")
        self.assertIn("aggregate", payload["indexed"])
        self.assertIn("aggregate", payload["legacy_metadata"])
        self.assertEqual(len(payload["indexed"]["per_query"]), len(spec.queries))
        self.assertGreaterEqual(payload["indexed"]["aggregate"]["duration_ms"]["p95"], 0.0)
        self.assertGreaterEqual(payload["legacy_metadata"]["aggregate"]["bytes_read"]["p95"], 0.0)


if __name__ == "__main__":
    unittest.main()
