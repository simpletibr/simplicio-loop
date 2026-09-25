import unittest

from simplicio_fast.pressure_inputs import (
    BandwidthPressure,
    CachePressure,
    Headroom,
    MetricState,
    Placement,
    PlacementCandidate,
    PressureInputError,
    PressureInputs,
    PressureMetric,
    Recommendation,
    Residency,
    TransferPressure,
    rank_placements,
    score_pressure,
)


def metric(value, capability, confidence=1.0):
    return PressureMetric.available(
        value,
        capability=capability,
        confidence=confidence,
    )


class PressureInputTests(unittest.TestCase):
    def test_missing_metrics_are_not_zeroed_and_reduce_coverage(self):
        result = score_pressure(
            PressureInputs(
                bandwidth=metric(BandwidthPressure(0.2), "memory.bandwidth"),
            ),
            acceptance_rate=0.95,
        )

        self.assertEqual(("bandwidth",), result.used_metrics)
        self.assertEqual(20.0, result.score)
        self.assertIn("transfer", result.unavailable_metrics)
        self.assertIn("TELEMETRY_INSUFFICIENT", result.reason_codes)
        self.assertEqual(Recommendation.BASELINE, result.recommendation)

    def test_all_unavailable_metrics_have_no_numeric_pressure_score(self):
        result = score_pressure(
            PressureInputs(
                transfer=PressureMetric.unavailable(capability="transfer.cost"),
            ),
            acceptance_rate=0.95,
        )

        self.assertIsNone(result.score)
        self.assertEqual((), result.used_metrics)
        self.assertIn("TELEMETRY_INSUFFICIENT", result.reason_codes)

    def test_capability_gate_marks_receipt_unavailable(self):
        result = score_pressure(
            PressureInputs(
                bandwidth=metric(BandwidthPressure(0.1), "memory.bandwidth"),
                cache=metric(CachePressure(0.1), "cache.llc"),
                capabilities=frozenset({"cache.llc"}),
            ),
            acceptance_rate=0.9,
        )

        self.assertEqual(("cache",), result.used_metrics)
        self.assertIn("bandwidth", result.unavailable_metrics)
        self.assertNotIn("bandwidth", result.contradictory_metrics)

    def test_high_acceptance_still_falls_back_for_bandwidth_and_transfer(self):
        result = score_pressure(
            PressureInputs(
                bandwidth=metric(BandwidthPressure(0.95), "memory.bandwidth"),
                transfer=metric(
                    TransferPressure(0.90, bytes=10_000_000, milliseconds=12),
                    "transfer.cost",
                ),
                cache=metric(CachePressure(0.20), "cache.llc"),
            ),
            acceptance_rate=0.99,
        )

        self.assertEqual(Recommendation.BASELINE, result.recommendation)
        self.assertIn("BANDWIDTH_PRESSURE_HIGH", result.reason_codes)
        self.assertIn("TRANSFER_PRESSURE_HIGH", result.reason_codes)

    def test_contradictory_receipt_fails_closed(self):
        result = score_pressure(
            PressureInputs(
                bandwidth=PressureMetric.contradictory(
                    capability="memory.bandwidth",
                    reason_code="BANDWIDTH_RECEIPT_CONTRADICTORY",
                ),
                cache=metric(CachePressure(0.1), "cache.llc"),
            ),
            acceptance_rate=0.95,
        )

        self.assertEqual(
            MetricState.CONTRADICTORY,
            result.contradictory_metrics and MetricState.CONTRADICTORY,
        )
        self.assertEqual(("cache",), result.used_metrics)
        self.assertEqual(Recommendation.BASELINE, result.recommendation)
        self.assertIn("TELEMETRY_CONTRADICTORY", result.reason_codes)

    def test_placement_scores_are_deterministic_and_differentiated(self):
        candidates = Residency(
            (
                PlacementCandidate("cpu", Placement.CPU_DRAFT),
                PlacementCandidate("unified", Placement.UNIFIED),
                PlacementCandidate("same", Placement.SAME_GPU),
            )
        )
        inputs = PressureInputs(
            bandwidth=metric(BandwidthPressure(0.2), "memory.bandwidth"),
            transfer=metric(TransferPressure(0.4), "transfer.cost"),
            headroom=metric(Headroom(ram=0.7, vram=0.6), "memory.headroom"),
            residency=metric(candidates, "placement.residency"),
        )

        first = rank_placements(inputs)
        second = rank_placements(inputs)
        self.assertEqual(
            [item.candidate.name for item in first], ["same", "unified", "cpu"]
        )
        self.assertEqual(
            [item.score for item in first], [item.score for item in second]
        )
        self.assertLess(first[0].score, first[-1].score)

    def test_invalid_input_is_rejected_with_reason_code(self):
        with self.assertRaises(PressureInputError) as caught:
            BandwidthPressure(1.1)
        self.assertEqual("BANDWIDTH_PRESSURE_INVALID", caught.exception.reason_code)
        with self.assertRaises(PressureInputError) as caught:
            Headroom()
        self.assertEqual("HEADROOM_VALUE_MISSING", caught.exception.reason_code)


if __name__ == "__main__":
    unittest.main()
