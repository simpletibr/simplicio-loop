"""Tests for scripts/prototype_remap_cost_benchmark.py (issue #286 step 12).

Exercises a small, real run (real git fixture, real canonical build, real
overlay/compose calls, real `build_artifacts` full remap) to prove the
script works end to end and reports the shape of numbers the metric needs
(a real wall-clock number for each side, a speedup ratio, and the documented
limitation note) -- not a specific ratio value, which is expected to vary by
machine/fixture size (see the script's own honesty caveats).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import prototype_remap_cost_benchmark as bench  # noqa: E402


class PrototypeRemapCostBenchmarkTests(unittest.TestCase):
    def test_small_run_reports_real_measurements(self) -> None:
        report = bench.run_benchmark(files=5)
        self.assertEqual(report["schema"], bench.REPORT_SCHEMA)
        self.assertEqual(report["schema"], "simplicio.prototype-remap-cost-benchmark/v1")

        self.assertGreaterEqual(report["canonical_build_seconds_amortized"], 0.0)
        self.assertGreaterEqual(report["full_remap"]["seconds"], 0.0)
        self.assertEqual(report["full_remap"]["files_mapped"], 6)  # 5 modules + README

        self.assertGreaterEqual(report["incremental_overlay"]["seconds"], 0.0)
        self.assertGreaterEqual(report["incremental_overlay"]["overlay_compute_seconds"], 0.0)
        self.assertGreaterEqual(report["incremental_overlay"]["effective_view_compose_seconds"], 0.0)
        # Exactly one file was touched by the benchmark itself.
        self.assertEqual(report["incremental_overlay"]["changed_files_in_overlay"], 1)

        self.assertEqual(report["proof_kind"], "estimated")
        self.assertTrue(report["known_limitation"])

    def test_incremental_overlay_is_cheaper_than_full_remap_on_this_fixture(self) -> None:
        # The whole point of the canonical/overlay path: a one-file change
        # against an already-built manifest should cost less wall time than
        # re-running the entire mapping pipeline from scratch. Real
        # assertion on real numbers from this run, not a hardcoded ratio.
        report = bench.run_benchmark(files=20)
        self.assertLess(
            report["incremental_overlay"]["seconds"],
            report["full_remap"]["seconds"],
        )
        self.assertIsNotNone(report["wall_time_speedup_ratio"])
        self.assertGreater(report["wall_time_speedup_ratio"], 1.0)
        self.assertIsNotNone(report["pct_cheaper"])
        self.assertGreater(report["pct_cheaper"], 0.0)

    def test_main_json_mode_runs_end_to_end(self) -> None:
        exit_code = bench.main(["--files", "5", "--json"])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
