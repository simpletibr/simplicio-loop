import unittest
from pathlib import Path

from scripts import evaluation_scorecard

ROOT = Path(__file__).resolve().parents[2]


class EvaluationBenchmarkTest(unittest.TestCase):
    def test_evaluation_scorecard_reports_honest_statuses(self) -> None:
        corpus = evaluation_scorecard._load_json(
            evaluation_scorecard.CORPUS_PATH.read_text(encoding="utf-8"),
            "corpus",
        )
        cases = [evaluation_scorecard._evaluate_case(case) for case in corpus["cases"]]
        aggregate = evaluation_scorecard._aggregate(cases)
        payload = {
            "schema": evaluation_scorecard.SCHEMA,
            "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
            "measurements": aggregate["measurements"],
            "measurement_status": aggregate["measurement_status"],
            "cases": cases,
        }
        self.assertEqual(payload["schema"], "simplicio.behavioral-scorecard/v1")
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["measurements"]["target_recall_at_k"], 1.0)
        self.assertEqual(payload["measurements"]["test_recall_at_k"], 1.0)
        self.assertEqual(payload["measurements"]["required_span_recall"], 1.0)
        self.assertEqual(payload["measurements"]["sufficiency"], 1.0)
        self.assertEqual(payload["measurement_status"]["estimated_tokens_mean"], "ESTIMATED")
        self.assertEqual(payload["measurements"]["determinism"], 1.0)
        self.assertEqual(len(payload["cases"]), 3)
        self.assertTrue(all(case["deterministic"] for case in payload["cases"]))
