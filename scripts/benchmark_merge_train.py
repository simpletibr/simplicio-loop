"""Benchmark script for merge_train LoRA merging strategy.

Measures performance of merging multiple LoRA adapters:
- Time to merge
- Memory usage
- Output quality (loss)
"""

import json
import os
import sys
import time
import tempfile
import psutil
from pathlib import Path
from typing import Dict, List, Any

import numpy as np


class BenchmarkMergeTrain:
    """Benchmark runner for merge_train strategy."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize benchmark with configuration."""
        self.config = config
        self.results = {}

    def run(self) -> Dict[str, Any]:
        """Run the benchmark."""
        return run_benchmark(self.config)


def load_adapters(
    adapter_dir: str,
    count: int,
    size_mb: int,
) -> List[Dict[str, np.ndarray]]:
    """Load or generate adapter weights.
    
    Args:
        adapter_dir: Directory containing adapters
        count: Number of adapters to load/generate
        size_mb: Size of each adapter in MB (for generation)
    
    Returns:
        List of adapter dictionaries with weights
    """
    adapters = []
    
    # Calculate array size from MB
    bytes_per_element = 8  # float64
    total_bytes = size_mb * 1024 * 1024
    num_elements = total_bytes // bytes_per_element
    dim = int(np.sqrt(num_elements))
    
    for i in range(count):
        adapter_path = Path(adapter_dir) / f"adapter_{i}.npy"
        
        if adapter_path.exists():
            weights = np.load(adapter_path)
        else:
            # Generate synthetic adapter
            weights = np.random.randn(dim, dim).astype(np.float32)
            # Save for reproducibility
            os.makedirs(adapter_dir, exist_ok=True)
            np.save(adapter_path, weights)
        
        adapters.append({"weights": weights})
    
    return adapters


def merge_adapters(adapters: List[Dict[str, np.ndarray]]) -> Dict[str, Any]:
    """Merge multiple adapters using weighted average.
    
    Args:
        adapters: List of adapter dictionaries
    
    Returns:
        Dictionary with merged weights and timing info
    """
    start_time = time.time()
    start_memory = psutil.Process().memory_info().rss / 1024 / 1024
    
    # Simple weighted merge: average all adapters
    weights_list = [a["weights"] for a in adapters]
    merged = np.mean(weights_list, axis=0)
    
    elapsed = time.time() - start_time
    end_memory = psutil.Process().memory_info().rss / 1024 / 1024
    memory_used = max(0, end_memory - start_memory)
    
    return {
        "merged_weights": merged,
        "elapsed_seconds": elapsed,
        "memory_mb": memory_used,
        "adapter_count": len(adapters),
    }


def evaluate_merged_model(merged_weights: np.ndarray) -> Dict[str, float]:
    """Evaluate merged model on validation set.
    
    Args:
        merged_weights: Merged weight matrix
    
    Returns:
        Dictionary with loss and perplexity metrics
    """
    # Simulate validation by computing statistics on weights
    # In real scenario, would run on actual validation data
    
    # Loss: mean squared error of weights (proxy metric)
    loss = float(np.mean(merged_weights ** 2))
    
    # Perplexity: exponential of loss
    perplexity = float(np.exp(min(loss, 10)))  # Cap to avoid overflow
    
    return {
        "loss": loss,
        "perplexity": perplexity,
    }


def run_benchmark(config: Dict[str, Any]) -> Dict[str, Any]:
    """Run full benchmark suite.
    
    Args:
        config: Configuration dictionary with:
            - base_model: Base model name
            - adapter_counts: List of adapter counts to test
            - adapter_size_mb: Size of each adapter
            - output_dir: Directory for output
            - num_runs: Number of runs per configuration
    
    Returns:
        Dictionary with benchmark results
    """
    output_dir = Path(config.get("output_dir", "/tmp/benchmark"))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    adapter_counts = config.get("adapter_counts", [1, 2, 4, 8])
    adapter_size_mb = config.get("adapter_size_mb", 5)
    num_runs = config.get("num_runs", 3)
    
    measurements = []
    
    for adapter_count in adapter_counts:
        for run_num in range(num_runs):
            with tempfile.TemporaryDirectory() as tmpdir:
                # Load adapters
                adapters = load_adapters(
                    adapter_dir=tmpdir,
                    count=adapter_count,
                    size_mb=adapter_size_mb,
                )
                
                # Merge adapters
                merge_result = merge_adapters(adapters)
                
                # Evaluate merged model
                metrics = evaluate_merged_model(merge_result["merged_weights"])
                
                # Collect measurement
                measurement = {
                    "adapter_count": adapter_count,
                    "run": run_num + 1,
                    "elapsed_seconds": merge_result["elapsed_seconds"],
                    "memory_mb": merge_result["memory_mb"],
                    "loss": metrics["loss"],
                    "perplexity": metrics["perplexity"],
                }
                measurements.append(measurement)
    
    results = {
        "base_model": config.get("base_model", "unknown"),
        "adapter_size_mb": adapter_size_mb,
        "num_runs": num_runs,
        "measurements": measurements,
    }
    
    # Save results to JSON
    output_file = output_dir / "benchmark_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    return results


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Benchmark merge_train LoRA merging strategy"
    )
    parser.add_argument(
        "--adapter-counts",
        type=int,
        nargs="+",
        default=[1, 2, 4, 8],
        help="Numbers of adapters to test",
    )
    parser.add_argument(
        "--adapter-size-mb",
        type=int,
        default=5,
        help="Size of each adapter in MB",
    )
    parser.add_argument(
        "--num-runs",
        type=int,
        default=3,
        help="Number of runs per configuration",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/tmp/merge_train_benchmark",
        help="Output directory for results",
    )
    parser.add_argument(
        "--base-model",
        type=str,
        default="gpt2",
        help="Base model name",
    )
    
    args = parser.parse_args()
    
    config = {
        "base_model": args.base_model,
        "adapter_counts": args.adapter_counts,
        "adapter_size_mb": args.adapter_size_mb,
        "num_runs": args.num_runs,
        "output_dir": args.output_dir,
    }
    
    results = run_benchmark(config)
    
    # Print summary
    print("\n" + "=" * 60)
    print("MERGE_TRAIN BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Base Model: {results['base_model']}")
    print(f"Adapter Size: {results['adapter_size_mb']} MB")
    print(f"Runs per Config: {results['num_runs']}")
    print("\n" + "-" * 60)
    print(f"{'Adapters':<12} {'Time (s)':<12} {'Memory (MB)':<12} {'Loss':<12}")
    print("-" * 60)
    
    # Group by adapter count
    by_count = {}
    for m in results["measurements"]:
        count = m["adapter_count"]
        if count not in by_count:
            by_count[count] = []
        by_count[count].append(m)
    
    # Print stats
    for count in sorted(by_count.keys()):
        measurements = by_count[count]
        times = [m["elapsed_seconds"] for m in measurements]
        memories = [m["memory_mb"] for m in measurements]
        losses = [m["loss"] for m in measurements]
        
        avg_time = np.mean(times)
        avg_memory = np.mean(memories)
        avg_loss = np.mean(losses)
        
        print(f"{count:<12} {avg_time:<12.4f} {avg_memory:<12.2f} {avg_loss:<12.6f}")
    
    print("-" * 60)
    print(f"\nResults saved to: {config['output_dir']}/benchmark_results.json")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
