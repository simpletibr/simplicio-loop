"""Tests for scripts/measure_verbs.py (issue #174, "measure first").

Loaded via importlib.util, same convention as tests/python/test_dogfood.py
and tests/python/test_token_budget.py. Uses a low repeat count so the suite
stays fast -- the committed `scripts/measure_verbs_report.json` is the real
evidence artifact (generated with more repeats), this test only proves the
script still runs and produces a well-shaped report.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "measure_verbs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("measure_verbs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MeasureVerbsTest(unittest.TestCase):
    def test_run_produces_well_shaped_report_and_does_not_touch_the_committed_fixture(self) -> None:
        module = _load_module()
        fixture_source = Path(module.FIXTURE_SOURCE)
        before = {p for p in fixture_source.rglob("*")}

        report = module.run(repeats=2)

        after = {p for p in fixture_source.rglob("*")}
        self.assertEqual(before, after, "measuring must not leave artifacts in the committed fixture source")

        self.assertEqual(report["schema"], "simplicio.measure-verbs-report/v1")
        self.assertIn("measurements", report)
        self.assertIn("index.build_artifacts", report["measurements"])
        self.assertIn("ask.impact (isolated)", report["measurements"])
        self.assertIn("ask.tests-for (isolated)", report["measurements"])
        conclusion = report["conclusion"]
        self.assertEqual(set(conclusion["selected_verbs_for_native_delegation"]), {"impact", "tests-for"})
        self.assertEqual(len(conclusion["ranked_isolated_ask_verbs_by_cost"]), 5)

    def test_committed_report_is_valid_json_matching_the_schema(self) -> None:
        report_path = ROOT / "scripts" / "measure_verbs_report.json"
        self.assertTrue(report_path.exists(), "scripts/measure_verbs_report.json must be committed as evidence")
        with open(report_path, encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["schema"], "simplicio.measure-verbs-report/v1")
        self.assertIn("impact", report["conclusion"]["selected_verbs_for_native_delegation"])
        self.assertIn("tests-for", report["conclusion"]["selected_verbs_for_native_delegation"])


if __name__ == "__main__":
    unittest.main()
