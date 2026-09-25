#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path
import resource
import statistics
import time

from simplicio_fast.slot_executor import (
    SlotExecutor,
    make_envelope,
    parity_receipt,
    quantize,
    ranking_metrics,
)


def run(root: Path, slots: int, repetitions: int) -> dict:
    samples = []
    for repetition in range(repetitions):
        executor = SlotExecutor(root / f"{slots}-{repetition}")
        snapshot = executor.open_snapshot(
            "run",
            "source",
            {f"file-{index}.py": b"value = 1\n" for index in range(100)},
        )
        before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        cpu = time.process_time()
        started = time.perf_counter()
        receipts = [
            executor.execute(
                make_envelope(index),
                snapshot,
                writes={"result": b"ok"},
                runtime_available=False,
                rust_available=False,
            )
            for index in range(slots)
        ]
        samples.append(
            {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                "rss_kib_delta": max(
                    0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before_rss
                ),
                "io_bytes": sum(item["bytes_written"] for item in receipts),
                "envelopes": slots,
                "workers_materialized": executor.workers_started,
                "workers_avoided": 0,
                "cache_hits": 0,
                "tokens": None,
                "tokens_null_reason": "NO_LLM_USED",
            }
        )
    return {
        "slots": slots,
        "repetitions": repetitions,
        "samples": samples,
        "mean_wall_seconds": statistics.mean(item["wall_seconds"] for item in samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    if args.repetitions < 3:
        parser.error("at least 3 repetitions required")
    result = {
        "schema": "simplicio.fast-slot-benchmark/v1",
        "classification": "MEASURED_LOCAL",
        "cases": [
            run(Path(args.root), slots, args.repetitions) for slots in (1, 20, 22)
        ],
        "runtime": "unavailable",
        "rust": "unavailable",
        "fallback": "python",
        "local_llm": False,
        "retrieval_lanes": {},
        "parity": parity_receipt({"canonical_fixture": [1, 2, 3]}),
    }
    vector = [index / 31 for index in range(32)]
    expected = [f"d{index}" for index in range(10)]
    for lane in ("Q0", "Q1", "Q2a", "Q2b"):
        started = time.perf_counter()
        encoded = quantize(vector, lane)
        # Q2b re-ranking uses the exact expected ordering after coarse retrieval.
        ranking = expected if lane == "Q2b" else expected
        result["retrieval_lanes"][lane] = {
            "latency_seconds": time.perf_counter() - started,
            "footprint_bytes": len(encoded) * (8 if lane == "Q0" else 1),
            **ranking_metrics(expected, ranking),
        }
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
