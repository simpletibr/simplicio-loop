"""Tests for scripts/prototype_impact_accuracy_benchmark.py (issue #286 step 12).

Exercises a real run of `build_prototype_context()` against the committed
`tests/fixtures/impact-ground-truth/python-rename-greet` fixture and asserts
on the shape of the scoring output plus the specific, real numbers this
fixture is known to produce (see the fixture's own `ground_truth.json` and
`README.md` for why): two real callers of `greet` are structurally missed by
`prototype_context`'s impact graph today (recall 0.5), while everything it
does predict is correct (precision 1.0). If a future change to
`prototype_context`/`query.py` teaches the impact graph to walk callers, this
test's recall assertion should be revisited upward -- it is pinned to
current, real behavior, not to a permanent ceiling.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import prototype_impact_accuracy_benchmark as bench  # noqa: E402


class PrototypeImpactAccuracyBenchmarkTests(unittest.TestCase):
    def test_fixture_scores_real_recall_and_precision(self) -> None:
        report = bench.run(bench.DEFAULT_FIXTURE)
        self.assertEqual(report["schema"], bench.REPORT_SCHEMA)
        self.assertEqual(report["schema"], "simplicio.prototype-impact-accuracy-benchmark/v1")

        scoring = report["scoring"]
        self.assertEqual(scoring["recall"], 0.5)
        self.assertEqual(scoring["precision"], 1.0)
        self.assertEqual(scoring["missed_impact_rate"], 0.5)
        self.assertEqual(
            scoring["false_negatives_missed_impact"],
            ["src/caller_a.py", "src/caller_b.py"],
        )
        self.assertEqual(scoring["false_positives_labeled_noise"], [])
        self.assertEqual(
            scoring["true_positives"],
            ["tests/test_caller_a.py", "tests/test_greeter.py"],
        )
        self.assertEqual(report["proof_kind"], "estimated")
        self.assertTrue(report["known_limitation"])

    def test_ground_truth_and_predicted_never_include_the_target_file(self) -> None:
        report = bench.run(bench.DEFAULT_FIXTURE)
        target_file = report["change"]["target_file"]
        self.assertNotIn(target_file, report["scoring"]["predicted"])
        self.assertNotIn(target_file, report["ground_truth"]["impacted_files"])

    def test_main_json_mode_runs_end_to_end(self) -> None:
        exit_code = bench.main(["--json"])
        self.assertEqual(exit_code, 0)

    def test_missing_ground_truth_file_raises(self) -> None:
        with self.assertRaises(SystemExit):
            bench.run(ROOT / "tests" / "fixtures" / "impact-ground-truth" / "does-not-exist")


if __name__ == "__main__":
    unittest.main()
