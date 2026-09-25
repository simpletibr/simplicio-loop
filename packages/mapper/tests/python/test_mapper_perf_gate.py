from __future__ import annotations

import unittest

from scripts.mapper_perf_gate import MIN_SAMPLES, build_evidence, compare


class MapperPerfGateTest(unittest.TestCase):
    def _evidence(self, values: list[float]) -> dict:
        return build_evidence(
            root=".",
            corpus={"schema": "simplicio.mapper-perf-corpus/v1", "size": "tiny"},
            profile="sync",
            phase="inventory",
            samples=[{"wall_ms": value} for value in values],
            fingerprint={"commit": "same", "machine": "test"},
        )

    def test_gate_fails_when_samples_are_missing(self) -> None:
        evidence = self._evidence([1.0] * (MIN_SAMPLES - 1))
        report = compare(evidence, evidence)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(all(check["status"] == "fail" for check in report["checks"]))

    def test_gate_fails_when_candidate_exceeds_p95_limit(self) -> None:
        baseline = self._evidence([100.0] * MIN_SAMPLES)
        candidate = self._evidence([111.0] * MIN_SAMPLES)
        report = compare(baseline, candidate)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any(check["metric"] == "wall_ms.p95" and check["status"] == "fail" for check in report["checks"]))


if __name__ == "__main__":
    unittest.main()
