"""Lightweight timeit-based performance benchmark for the mapper's hottest
path: `build_artifacts()` (project-map + symbol-index + call-graph parse and
emit, `simplicio_mapper/mapper.py`) -- the single call every CLI command
(`map`, `index`, `scan`, `ask`, `orient`, ...) pays.

This is deliberately a stdlib-only `timeit`-style budget check (no
`pytest-benchmark` dependency added), matching the rest of this repo's
scripts/*_benchmark.py convention of producing one real measured number per
run instead of an unverifiable claim. It asserts a generous wall-clock
ceiling (not a strict SLA) so it stays green on slower CI runners while
still catching an actual multi-x regression.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from simplicio_mapper.mapper import build_artifacts

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "mapper-artifacts"
    / "v1"
    / "fixtures"
    / "mixed-workspace"
    / "source"
)

# Generous ceiling for a small fixture on a slow/shared CI runner. This is a
# regression tripwire (catches an accidental O(n^2) or repeated-I/O
# regression), not a tight performance SLA.
BUDGET_SECONDS_PER_RUN = 2.0
WARMUP_RUNS = 1
MEASURED_RUNS = 5


class MapperParseBenchmarkTest(unittest.TestCase):
    def test_build_artifacts_stays_within_time_budget(self) -> None:
        self.assertTrue(FIXTURE_ROOT.is_dir(), f"missing fixture: {FIXTURE_ROOT}")

        for _ in range(WARMUP_RUNS):
            build_artifacts(str(FIXTURE_ROOT))

        durations = []
        for _ in range(MEASURED_RUNS):
            start = time.perf_counter()
            artifacts = build_artifacts(str(FIXTURE_ROOT))
            durations.append(time.perf_counter() - start)

        mean_seconds = sum(durations) / len(durations)
        max_seconds = max(durations)

        # A real measured number, not a claim: printed so `pytest -s` (or any
        # CI log) surfaces it, and asserted against the budget above.
        print(
            f"[benchmark] build_artifacts({FIXTURE_ROOT.name}): "
            f"mean={mean_seconds * 1000:.3f}ms max={max_seconds * 1000:.3f}ms "
            f"over {MEASURED_RUNS} runs (+{WARMUP_RUNS} warmup)"
        )

        self.assertLess(
            mean_seconds,
            BUDGET_SECONDS_PER_RUN,
            f"build_artifacts mean duration {mean_seconds:.3f}s exceeded "
            f"the {BUDGET_SECONDS_PER_RUN}s/run budget over {MEASURED_RUNS} runs",
        )
        # Sanity check that the parse actually did real work, so a future
        # short-circuit bug can't "pass" this benchmark by doing nothing.
        self.assertGreater(len(artifacts["project_map"]["files"]), 0)


if __name__ == "__main__":
    unittest.main()
