from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.structural_benchmark import BenchmarkCase, measure_case, run_corpus, summarize


class StructuralBenchmarkTests(unittest.TestCase):
    def test_measurement_keeps_provider_tokens_unavailable(self) -> None:
        case = BenchmarkCase("q1", "who calls main", "sha1", "a" * 400, "main", "main is called", "main is called", ("main",))
        result = measure_case(case)
        self.assertIsNone(result.mapper.provider_input_tokens)
        self.assertGreater(result.context_saving, 0)
        self.assertTrue(result.quality_gate)

    def test_quality_gate_blocks_unsupported_economy_claim(self) -> None:
        case = BenchmarkCase("q1", "question", "sha1", "baseline evidence", "tiny", "fact is present", "wrong", ("fact",))
        result = summarize((case,), (measure_case(case),))
        self.assertFalse(result["quality_gate"]["passed"])
        self.assertFalse(result["claim_99_percent_enabled"])

    def test_jsonl_corpus_is_reproducible_and_reports_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            rows = [
                {"case_id": "q1", "question": "q", "repo_sha": "sha", "baseline_context": "long evidence " * 10, "mapper_context": "evidence", "baseline_answer": "fact", "mapper_answer": "fact", "expected_facts": ["fact"]},
                {"case_id": "q2", "question": "q", "repo_sha": "sha", "baseline_context": "long evidence " * 10, "mapper_context": "evidence", "baseline_answer": "fact", "mapper_answer": "fact", "expected_facts": ["fact"]},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            report = run_corpus(path)
            self.assertEqual(report["case_count"], 2)
            self.assertEqual(report["metrics"]["context_saving"]["measured_cases"], 2)
            self.assertIn("p95", report["metrics"]["context_saving"])


if __name__ == "__main__":
    unittest.main()
