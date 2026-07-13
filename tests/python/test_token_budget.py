"""Tests for scripts/token_budget.py (issue #174, token/context budget guard).

Loaded via importlib.util (hyphen-free but still a standalone CLI script,
same loading convention as tests/python/test_dogfood.py and
tests/python/test_generate_ecosystem_doc.py).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "token_budget.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("token_budget", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EstimatorTest(unittest.TestCase):
    def test_heuristic_estimator_is_chars_div_4(self) -> None:
        module = _load_module()
        self.assertEqual(module._heuristic_estimator("abcd" * 10), 10)
        self.assertEqual(module._heuristic_estimator(""), 0)
        self.assertEqual(module._heuristic_estimator("a"), 1)

    def test_get_estimator_falls_back_to_heuristic_without_tiktoken(self) -> None:
        module = _load_module()
        module._try_tiktoken_estimator = lambda: None
        _fn, estimator_id = module.get_estimator()
        self.assertEqual(estimator_id, "heuristic:chars-div-4")


class MeasureTest(unittest.TestCase):
    """Exercises the real, committed artifacts this guard tracks -- not a
    synthetic stand-in -- so a passing test here proves the guard actually
    finds AGENTS.md/CLAUDE.md and the real mapper-artifacts contract fixture
    output on disk in this repo."""

    def test_measure_finds_tracked_docs_and_real_fixture_artifacts(self) -> None:
        module = _load_module()
        measurements = module.measure(module._heuristic_estimator)
        self.assertIn("AGENTS.md", measurements)
        self.assertIn("CLAUDE.md", measurements)
        self.assertGreater(measurements["AGENTS.md"]["tokens"], 0)

        fixture_rel = (
            "contracts/mapper-artifacts/v1/fixtures/python-minimal/artifacts/project-map.json"
        )
        normalized = {path.replace("\\", "/"): payload for path, payload in measurements.items()}
        self.assertIn(fixture_rel, normalized)
        self.assertGreater(normalized[fixture_rel]["tokens"], 0)

    def test_measure_skips_missing_artifacts_without_failing(self) -> None:
        module = _load_module()
        measurements = module.measure(
            module._heuristic_estimator,
            extra_artifacts=[("does-not-exist", "no/such/file.md")],
        )
        self.assertNotIn("no/such/file.md", measurements)


class ReportRegressionGateTest(unittest.TestCase):
    """The negative-path proof (issue #174 AC): the guard must actually FAIL
    a real size regression, not just always print PASS."""

    def setUp(self) -> None:
        self.module = _load_module()
        self.baseline = {
            "estimator": "heuristic:chars-div-4",
            "artifacts": {
                "some/doc.md": {"label": "some/doc.md", "tokens": 1000, "words": 500},
            },
        }

    def test_regression_past_threshold_fails(self) -> None:
        measurements = {
            "some/doc.md": {"label": "some/doc.md", "tokens": 1300, "words": 650, "chars": 5200},
        }
        ok = self.module.report(measurements, self.baseline, "heuristic:chars-div-4", quiet=True)
        self.assertFalse(ok)

    def test_growth_within_threshold_passes(self) -> None:
        measurements = {
            "some/doc.md": {"label": "some/doc.md", "tokens": 1100, "words": 550, "chars": 4400},
        }
        ok = self.module.report(measurements, self.baseline, "heuristic:chars-div-4", quiet=True)
        self.assertTrue(ok)

    def test_new_artifact_without_baseline_does_not_fail(self) -> None:
        measurements = {
            "some/doc.md": {"label": "some/doc.md", "tokens": 1000, "words": 500, "chars": 4000},
            "brand/new.md": {"label": "brand/new.md", "tokens": 99999, "words": 1, "chars": 4},
        }
        ok = self.module.report(measurements, self.baseline, "heuristic:chars-div-4", quiet=True)
        self.assertTrue(ok)


class SelfTestCommandTest(unittest.TestCase):
    """`--self-test` (issue #174 AC: "teste negativo demonstrado") must exit 0
    only when it has proven the guard's fail path actually fires."""

    def test_self_test_function_passes(self) -> None:
        module = _load_module()
        self.assertEqual(module.self_test(), 0)

    def test_main_dash_dash_self_test_returns_zero(self) -> None:
        import sys

        module = _load_module()
        old_argv = sys.argv
        try:
            sys.argv = ["token_budget.py", "--self-test"]
            rc = module.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
