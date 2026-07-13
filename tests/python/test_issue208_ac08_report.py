from __future__ import annotations

import unittest
from pathlib import Path

from simplicio_mapper.issue208_ac08_report import (
    REPORT_SCHEMA,
    build_issue208_ac08_report,
    render_issue208_ac08_markdown,
)


ROOT = Path(__file__).resolve().parents[2]


class Issue208Ac08ReportTest(unittest.TestCase):
    def test_current_committed_corpus_yields_unverified_hypotheses(self) -> None:
        report = build_issue208_ac08_report(ROOT)
        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertEqual(report["overall_verdict"], "UNVERIFIED")
        self.assertEqual(report["measured"]["corpus_case_count"], 3)
        self.assertEqual(report["measured"]["abstention_case_count"], 1)
        self.assertEqual(report["measured"]["expected_target_labels"], 2)
        self.assertEqual(report["measured"]["expected_test_labels"], 2)
        self.assertEqual(report["measured"]["expected_ac_labels"], 6)
        self.assertEqual(report["measured"]["fixtures_with_task_file"], 3)
        self.assertEqual(report["measured"]["existing_expected_target_files"], 2)
        self.assertEqual(report["measured"]["existing_expected_test_files"], 2)
        verdicts = {item["id"]: item for item in report["hypotheses"]}
        self.assertEqual(verdicts["H1"]["verdict"], "UNVERIFIED")
        self.assertEqual(verdicts["H2"]["verdict"], "UNVERIFIED")
        self.assertIn("baseline_full_snapshot_tokens", verdicts["H1"]["missing_metrics"])
        self.assertIn("candidate_incremental_p95_ms", verdicts["H2"]["missing_metrics"])

    def test_markdown_makes_negative_findings_explicit(self) -> None:
        report = build_issue208_ac08_report(ROOT)
        markdown = render_issue208_ac08_markdown(report)
        self.assertIn("Overall verdict: **UNVERIFIED**", markdown)
        self.assertIn("No committed paired baseline/candidate token measurements exist", markdown)
        self.assertIn("H1", markdown)
        self.assertIn("H2", markdown)


if __name__ == "__main__":
    unittest.main()
