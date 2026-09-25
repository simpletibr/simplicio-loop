from __future__ import annotations

import unittest

from benchmarks.bench_optional_model_517 import run


class OptionalModel517Tests(unittest.TestCase):
    def test_issue_517_keeps_model_fixture_out_of_the_product_path(self) -> None:
        receipt = run(repetitions=10)

        self.assertEqual("not_promoted", receipt["status"])
        self.assertEqual(
            "keep_deterministic_default_fixture_only", receipt["decision"]
        )
        self.assertEqual(
            {"train": 4, "dev": 3, "evaluation": 12},
            receipt["dataset"]["split_counts"],
        )
        self.assertTrue(receipt["dataset"]["evaluation_is_held_out"])
        self.assertFalse(receipt["model"]["production"])
        self.assertFalse(receipt["model"]["learned"])
        self.assertTrue(receipt["promotion_gate"]["canonical_provenance"])
        self.assertTrue(receipt["promotion_gate"]["exact_symbol_non_regression"])
        self.assertTrue(receipt["promotion_gate"]["held_out_metric_improved"])
        self.assertFalse(receipt["promotion_gate"]["authorized_production_model"])
        self.assertTrue(
            receipt["summary"]["deterministic-baseline"]["budget_compliance"]
        )
        self.assertTrue(
            receipt["summary"]["optional-contract-fixture"]["budget_compliance"]
        )
