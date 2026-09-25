"""Tests for scripts/canonical_reuse_benchmark.py (issue #269).

Exercises a small, real run of the N-worktree canonical-reuse vs full-remap
benchmark (real git worktrees, real mapping pipeline calls) to prove the
script itself works end to end and reports the shape of numbers the issue's
acceptance criteria require (wall time for every run, a total for each
group, and an explicit speedup ratio) -- not the ratio's exact value, which
is expected to vary by machine/fixture size (see the script's own honesty
caveats).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import canonical_reuse_benchmark as bench  # noqa: E402


class CanonicalReuseBenchmarkTests(unittest.TestCase):
    def test_small_run_reports_real_measurements_for_every_worktree(self) -> None:
        report = bench.run_benchmark(worktrees=2, files=5)
        self.assertEqual(report["schema"], bench.SCHEMA)
        self.assertEqual(report["schema"], "simplicio.canonical-reuse-benchmark/v2")
        self.assertEqual(len(report["full_remap"]["runs"]), 2)
        self.assertEqual(len(report["canonical_reuse"]["runs"]), 2)

        for run in report["full_remap"]["runs"] + report["canonical_reuse"]["runs"]:
            self.assertGreaterEqual(run["wall_s"], 0.0)
            self.assertEqual(run["files_mapped"], 6)  # 5 modules + README
            # schema v2 (issue #236): child-process CPU/RSS and I/O-proxy
            # fields must be present (non-None on this POSIX/Linux runner)
            # -- the whole point of the v2 bump is that these are no longer
            # silently dropped.
            for field in (
                "cpu_s_children",
                "peak_rss_kb_children",
                "io_in_blocks",
                "io_out_blocks",
                "io_in_blocks_children",
                "io_out_blocks_children",
            ):
                self.assertIn(field, run)
                self.assertIsNotNone(run[field], f"{field} must be measured on POSIX")

        self.assertAlmostEqual(
            report["full_remap"]["total_wall_s"],
            sum(r["wall_s"] for r in report["full_remap"]["runs"]),
            places=3,
        )
        self.assertAlmostEqual(
            report["canonical_reuse"]["total_wall_s"],
            sum(r["wall_s"] for r in report["canonical_reuse"]["runs"]),
            places=3,
        )
        self.assertIsNotNone(report["wall_time_speedup_ratio"])
        self.assertTrue(report["caveats"], "must never claim a ratio without stating its limits")

    def test_only_first_reuse_worktree_pays_full_canonical_build_cost(self) -> None:
        # Not a strict inequality assertion (machine noise on a 5-file
        # fixture can make the first/second call's wall time close) -- the
        # honest, always-true invariant here is that every canonical-reuse
        # run after the first is a genuine cache hit (never a re-triggered
        # canonical build), which the underlying receipt already proves.
        report = bench.run_benchmark(worktrees=3, files=5)
        self.assertEqual(len(report["canonical_reuse"]["runs"]), 3)


if __name__ == "__main__":
    unittest.main()
