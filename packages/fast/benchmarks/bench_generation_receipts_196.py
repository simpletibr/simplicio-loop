"""Reproducible cold/warm receipt benchmark; stdlib only, no LLM/network."""

import json
import resource
import statistics
import time
from simplicio_fast.generation_receipts import seal_receipt, verify_receipt


def sample(iterations=1000):
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    cold0 = time.perf_counter_ns()
    receipt = seal_receipt(
        kind="context",
        repo="org/repo",
        commit="a" * 40,
        snapshot_digest="b" * 64,
        generation="g1",
        source_hashes={"src/a.py": "c" * 64},
        backend="python",
        fallback_reason="RUST_UNAVAILABLE",
    )
    verify_receipt(receipt)
    cold_us = (time.perf_counter_ns() - cold0) / 1000
    timings = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        verify_receipt(receipt)
        timings.append((time.perf_counter_ns() - start) / 1000)
    return {
        "schema": "simplicio.fast-benchmark/v1",
        "issue": 196,
        "iterations": iterations,
        "cold_us": cold_us,
        "warm_mean_us": statistics.mean(timings),
        "warm_p95_us": sorted(timings)[int(iterations * 0.95) - 1],
        "rss_kib_delta": max(
            0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss0
        ),
        "io_bytes": None,
        "io_bytes_null_reason": "IN_MEMORY_RECEIPT",
        "tokens": None,
        "tokens_null_reason": "NO_LLM_USED",
        "raw_warm_us": timings,
    }


if __name__ == "__main__":
    print(json.dumps(sample(), sort_keys=True, separators=(",", ":")))
