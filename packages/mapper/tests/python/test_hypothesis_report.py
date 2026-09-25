import json
import unittest
from pathlib import Path

from scripts import hypothesis_report

ROOT = Path(__file__).resolve().parents[2]


class HypothesisReportTest(unittest.TestCase):
    def test_hypothesis_report_emits_h1_h2_with_honest_statuses(self) -> None:
        left = json.loads(json.dumps(hypothesis_report.build_report(), sort_keys=True))
        right = json.loads(json.dumps(hypothesis_report.build_report(), sort_keys=True))
        self.assertEqual(left["schema"], "simplicio.hypothesis-report/v1")
        self.assertEqual(left["corpus"]["case_count"], 2)
        self.assertEqual([item["id"] for item in left["hypotheses"]], ["H1", "H2"])
        self.assertTrue(all(item["verdict"] in {"pass", "refuted"} for item in left["hypotheses"]))
        self.assertEqual(left["selector_measurement_status"]["estimated_tokens_mean"], "ESTIMATED")
        self.assertEqual(left["selector_measurement_status"]["precision_at_k"], "MEASURED")
        self.assertEqual(left["selector_measurement_status"]["target_recall_at_k"], "MEASURED")
        self.assertEqual(
            [case["baseline"]["selected_paths"] for case in left["cases"]],
            [case["baseline"]["selected_paths"] for case in right["cases"]],
        )
        self.assertEqual(
            [case["indexed"]["selected_paths"] for case in left["cases"]],
            [case["indexed"]["selected_paths"] for case in right["cases"]],
        )
        self.assertEqual(
            [(item["id"], item["verdict"]) for item in left["hypotheses"]],
            [(item["id"], item["verdict"]) for item in right["hypotheses"]],
        )


if __name__ == "__main__":
    unittest.main()
