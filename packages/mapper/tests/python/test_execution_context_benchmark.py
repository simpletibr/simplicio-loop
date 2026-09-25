from __future__ import annotations

import os
import platform
import unittest
from pathlib import Path

from scripts.execution_context_benchmark import ROOT, benchmark_callable, benchmark_fixture_subprocess


class ExecutionContextBenchmarkTests(unittest.TestCase):
    def test_cold_warm_receipt_reports_required_metrics(self) -> None:
        receipt = benchmark_callable(lambda: {"schema": "fixture", "value": "x" * 100}, runs=2)
        self.assertEqual(receipt["schema"], "simplicio.execution-context-benchmark/v1")
        self.assertEqual(set(receipt["measurements"]), {"cold", "warm"})
        self.assertEqual(receipt["environment"]["python_version"], platform.python_version())
        self.assertIn("tokenizer_policy", receipt["environment"])
        self.assertIn("process high-water mark", receipt["rss_semantics"])
        for phase in ("cold", "warm"):
            metrics = receipt["measurements"][phase]
            for name in ("bytes_read", "files_opened", "latency_ms", "peak_rss_bytes", "serialized_tokens"):
                self.assertIn(name, metrics)
                self.assertIn("value", metrics[name])
                self.assertIn("unavailable_reason", metrics[name])
                if metrics[name]["value"] is None:
                    self.assertTrue(metrics[name]["unavailable_reason"])

    def test_fixture_benchmark_runs_cold_measurement_in_fresh_subprocess(self) -> None:
        fixture = ROOT / "simplicio_mapper/contracts/mapper-artifacts/v1/fixtures/python-minimal"
        receipt = benchmark_fixture_subprocess(Path(fixture), runs=2)
        self.assertEqual(receipt["cold_semantics"], "first builder call in a fresh subprocess")
        self.assertEqual(receipt["environment"]["process_model"], "fresh-subprocess")
        self.assertNotEqual(receipt["environment"]["process_id"], os.getpid())
