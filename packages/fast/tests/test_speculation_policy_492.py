from __future__ import annotations

import unittest

from simplicio_fast.speculation_policy import (
    DECISION_OWNER,
    EXECUTION_OWNER,
    SPECULATION_POLICY_SCHEMA,
    SpeculationCapabilities,
    SpeculationConfiguration,
    SpeculationPolicy,
    SpeculationStrategy,
    StrategyCapability,
)


class SpeculationPolicy492Test(unittest.TestCase):
    def test_configuration_accepts_only_the_issue_492_values(self) -> None:
        self.assertEqual(
            [configuration.value for configuration in SpeculationConfiguration],
            ["off", "auto", "ngram", "draft", "dflash", "mtp"],
        )
        self.assertEqual(
            SpeculationConfiguration.parse(" DFLASH "),
            SpeculationConfiguration.DFLASH,
        )
        with self.assertRaises(ValueError):
            SpeculationPolicy("beam")

    def test_off_always_returns_baseline(self) -> None:
        result = SpeculationPolicy("off").decide(
            SpeculationCapabilities(
                ngram=True,
                draft=StrategyCapability(True, 2.0),
                dflash=True,
                mtp=True,
            )
        )
        self.assertEqual(result.selected, SpeculationStrategy.BASELINE)
        self.assertEqual(result.reason, "disabled_by_configuration")
        self.assertFalse(result.receipt.fallback)

    def test_explicit_supported_strategy_is_selected(self) -> None:
        result = SpeculationPolicy("draft").decide(
            SpeculationCapabilities(draft=StrategyCapability(True, 1.2))
        )
        self.assertEqual(result.selected, SpeculationStrategy.DRAFT)
        self.assertEqual(result.reason, "explicit_strategy_selected")
        self.assertFalse(result.receipt.fallback)

    def test_explicit_unsupported_strategy_falls_back_to_baseline(self) -> None:
        result = SpeculationPolicy("mtp").decide(SpeculationCapabilities(ngram=True))
        self.assertEqual(result.selected, SpeculationStrategy.BASELINE)
        self.assertEqual(result.reason, "requested_strategy_unsupported")
        self.assertTrue(result.receipt.fallback)

    def test_explicit_slower_strategy_falls_back_to_baseline(self) -> None:
        result = SpeculationPolicy("dflash").decide(
            SpeculationCapabilities(dflash=StrategyCapability(True, 0.8))
        )
        self.assertEqual(result.selected, SpeculationStrategy.BASELINE)
        self.assertEqual(
            result.reason,
            "requested_strategy_not_faster_than_baseline",
        )
        self.assertTrue(result.receipt.fallback)

    def test_auto_ignores_unsupported_and_slower_candidates(self) -> None:
        result = SpeculationPolicy("auto").decide(
            SpeculationCapabilities(
                ngram=StrategyCapability(True, 1.1),
                draft=StrategyCapability(True, 1.4),
                dflash=StrategyCapability(True, 0.8),
                mtp=False,
            )
        )
        self.assertEqual(result.selected, SpeculationStrategy.DRAFT)
        self.assertEqual(result.reason, "auto_strategy_selected")

    def test_auto_uses_speedup_then_fixed_preference_for_ties(self) -> None:
        result = SpeculationPolicy("auto").decide(
            SpeculationCapabilities(
                ngram=StrategyCapability(True, 1.5),
                draft=StrategyCapability(True, 1.5),
                dflash=StrategyCapability(True, 1.8),
                mtp=StrategyCapability(True, 1.8),
            )
        )
        self.assertEqual(result.selected, SpeculationStrategy.MTP)

    def test_auto_uses_fixed_preference_when_speed_is_unmeasured(self) -> None:
        result = SpeculationPolicy("auto").decide(
            SpeculationCapabilities(ngram=True, dflash=True, mtp=True)
        )
        self.assertEqual(result.selected, SpeculationStrategy.MTP)

    def test_auto_falls_back_when_no_candidate_is_faster(self) -> None:
        result = SpeculationPolicy("auto").decide(
            SpeculationCapabilities(
                ngram=StrategyCapability(True, 1.0),
                draft=StrategyCapability(True, 0.9),
                dflash=False,
                mtp=False,
            )
        )
        self.assertEqual(result.selected, SpeculationStrategy.BASELINE)
        self.assertEqual(result.reason, "no_faster_supported_strategy")
        self.assertTrue(result.receipt.fallback)

    def test_result_and_receipt_are_typed_serializable_and_owned_correctly(
        self,
    ) -> None:
        capabilities = SpeculationCapabilities(
            ngram=True,
            draft=StrategyCapability(True, 1.3),
        )
        first = SpeculationPolicy("auto").decide(capabilities)
        second = SpeculationPolicy("auto").decide(capabilities)

        self.assertEqual(first, second)
        self.assertEqual(first.receipt.selected, first.selected)
        self.assertEqual(first.receipt.decision_owner, DECISION_OWNER)
        self.assertEqual(first.receipt.execution_owner, EXECUTION_OWNER)
        payload = first.to_dict()
        self.assertEqual(payload["schema"], SPECULATION_POLICY_SCHEMA)
        self.assertEqual(
            payload["execution_plan"],
            {"strategy": "draft", "owner": EXECUTION_OWNER},
        )
        self.assertEqual(payload["receipt"]["capabilities"]["ngram"]["supported"], True)

    def test_baseline_capability_is_always_present_in_receipt(self) -> None:
        result = SpeculationPolicy("auto").decide()
        baseline = result.receipt.to_dict()["capabilities"]["baseline"]
        self.assertEqual(baseline, {"supported": True, "expected_speedup": 1.0})


if __name__ == "__main__":
    unittest.main()
