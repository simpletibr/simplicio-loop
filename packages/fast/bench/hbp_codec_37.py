from __future__ import annotations
import json
import statistics
import time
from simplicio_fast.hbp_codec import seal_receipt, verify_chain

samples = []
for _ in range(10):
    rows, previous = [], "0" * 64
    started = time.perf_counter_ns()
    for index in range(1000):
        value = seal_receipt(f"EVENT|seq={index}|json=0", previous)
        rows.append(value)
        previous = value[-64:]
    verify_chain(rows)
    samples.append((time.perf_counter_ns() - started) / 1e6)
print(
    json.dumps(
        {
            "schema": "simplicio.fast-benchmark/v1",
            "measured": True,
            "operations_per_repetition": 1000,
            "repetitions": 10,
            "mean_ms": statistics.mean(samples),
            "p95_ms": sorted(samples)[-1],
            "raw_ms": samples,
            "provider_metrics": None,
            "provider_metrics_reason": "deterministic codec benchmark; no LLM invoked",
        },
        sort_keys=True,
    )
)
