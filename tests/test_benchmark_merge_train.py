"""Benchmarks for merge_train LoRA merging strategy.

Measures:
- Time to merge N LoRA adapters
- Memory usage during merge
- Output quality (loss on validation set)
"""

import os
import sys
import tempfile
import time
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import numpy as np

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.benchmark_merge_train import (
    BenchmarkMergeTrain,
    load_adapters,
    merge_adapters,
    evaluate_merged_model,
    run_benchmark,
)


class TestMergeTrainBenchmark:
    """Test suite for merge_train benchmark."""

    def test_benchmark_class_initialization(self):
        """Test that BenchmarkMergeTrain initializes correctly."""
        config = {
            "base_model": "gpt2",
            "adapter_count": 3,
            "adapter_size_mb": 5,
            "output_dir": "/tmp/benchmark_output",
        }
        bench = BenchmarkMergeTrain(config)
        assert bench.config == config
        assert bench.results == {}

    def test_load_adapters_returns_correct_count(self):
        """Test that load_adapters returns requested number of adapters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapters = load_adapters(
                adapter_dir=tmpdir,
                count=3,
                size_mb=1,
            )
            assert len(adapters) == 3
            for adapter in adapters:
                assert isinstance(adapter, dict)
                assert "weights" in adapter

    def test_merge_adapters_timing(self):
        """Test that merge_adapters returns timing metrics."""
        adapters = [
            {"weights": np.random.randn(100, 100)},
            {"weights": np.random.randn(100, 100)},
            {"weights": np.random.randn(100, 100)},
        ]
        result = merge_adapters(adapters)
        assert "merged_weights" in result
        assert "elapsed_seconds" in result
        assert result["elapsed_seconds"] > 0
        assert result["adapter_count"] == 3

    def test_evaluate_merged_model_returns_metrics(self):
        """Test that evaluate_merged_model returns quality metrics."""
        merged_weights = np.random.randn(100, 100)
        metrics = evaluate_merged_model(merged_weights)
        assert "loss" in metrics
        assert "perplexity" in metrics
        assert metrics["loss"] >= 0
        assert metrics["perplexity"] >= 1

    def test_run_benchmark_integration(self):
        """Test full benchmark run with integration test."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "base_model": "gpt2",
                "adapter_counts": [1, 2, 3],
                "adapter_size_mb": 1,
                "output_dir": tmpdir,
                "num_runs": 1,
            }
            results = run_benchmark(config)
            assert "measurements" in results
            assert len(results["measurements"]) == 3
            for measurement in results["measurements"]:
                assert "adapter_count" in measurement
                assert "elapsed_seconds" in measurement
                assert "memory_mb" in measurement
                assert "loss" in measurement


class TestBenchmarkMetrics:
    """Test metric collection and reporting."""

    def test_metrics_are_numeric(self):
        """Test that all metrics are numeric and not None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "base_model": "gpt2",
                "adapter_counts": [1, 2],
                "adapter_size_mb": 1,
                "output_dir": tmpdir,
                "num_runs": 1,
            }
            results = run_benchmark(config)
            for measurement in results["measurements"]:
                assert isinstance(measurement["elapsed_seconds"], (int, float))
                assert isinstance(measurement["memory_mb"], (int, float))
                assert isinstance(measurement["loss"], (int, float))

    def test_results_save_to_json(self):
        """Test that results are saved to JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "base_model": "gpt2",
                "adapter_counts": [1],
                "adapter_size_mb": 1,
                "output_dir": tmpdir,
                "num_runs": 1,
            }
            results = run_benchmark(config)
            
            json_file = Path(tmpdir) / "benchmark_results.json"
            assert json_file.exists()
            
            with open(json_file) as f:
                saved_results = json.load(f)
            assert saved_results == results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
