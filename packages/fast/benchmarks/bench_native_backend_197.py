"""Reproducible Python baseline and call-dispatch overhead; no LLM/network."""

import json
import statistics
import time
from simplicio_fast.native_backend import PythonBackend, execute_with_fallback


def run(iterations=10000):
    payload = {"hex": (b"portable-golden" * 64).hex()}
    backend = PythonBackend()
    direct, dispatch = [], []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        backend.sha256(bytes.fromhex(payload["hex"]))
        direct.append((time.perf_counter_ns() - start) / 1000)
        start = time.perf_counter_ns()
        execute_with_fallback(backend, "sha256", payload)
        dispatch.append((time.perf_counter_ns() - start) / 1000)
    return {
        "schema": "simplicio.fast-native-benchmark/v1",
        "issue": 197,
        "iterations": iterations,
        "python_direct_mean_us": statistics.mean(direct),
        "dispatch_mean_us": statistics.mean(dispatch),
        "dispatch_p95_us": sorted(dispatch)[int(iterations * 0.95) - 1],
        "rust_latency_us": None,
        "rust_latency_null_reason": "RUST_TOOLCHAIN_UNAVAILABLE",
        "tokens": None,
        "tokens_null_reason": "NO_LLM_USED",
        "raw_python_direct_us": direct,
        "raw_dispatch_us": dispatch,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
