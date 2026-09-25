"""Reproducible PRISM arena matrix for issue #213; stdlib only."""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio_fast.prism_arena import BENCHMARK_SCHEMA, PrismArena, PrismWorkDelta

MATRIX = ((1, 10), (4, 10), (20, 10))


def _percentiles(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "median": statistics.median(ordered),
        "p95": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "p99": ordered[max(0, int(len(ordered) * 0.99) - 1)],
        "raw": samples,
    }


def _rss_kib() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _run_case(
    storage: Path,
    generation: str,
    slots: int,
    tasks_per_slot: int,
    repetitions: int,
) -> dict[str, Any]:
    wall: list[float] = []
    cpu: list[float] = []
    rss: list[int] = []
    read_blocks: list[int] = []
    write_blocks: list[int] = []
    metric_samples: list[dict[str, Any]] = []
    for repetition in range(repetitions):
        before_usage = resource.getrusage(resource.RUSAGE_SELF)
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        arena = PrismArena(storage, "benchmark/repo", generation)
        for slot_index in range(slots):
            slot = arena.open_slot(
                f"slot-{slot_index}",
                "prism",
                fence=f"f-{repetition}-{slot_index}",
                max_overlay_bytes=4096,
                max_overlay_files=10,
            )
            for task_index in range(tasks_per_slot):
                overlay = arena.create_overlay(
                    slot,
                    f"task-{task_index}",
                    1,
                    f"wt-{task_index}",
                    fence=slot.fence,
                )
                arena.base_read(slot, "src/base.py")
                arena.apply_delta(
                    slot,
                    overlay,
                    PrismWorkDelta(
                        writes={
                            f"generated/{task_index}.txt": (
                                f"{repetition}:{slot_index}:{task_index}".encode()
                            )
                        }
                    ),
                )
                arena.read(slot, overlay, f"generated/{task_index}.txt")
        metric_samples.append(arena.metrics())
        arena.close()
        after_usage = resource.getrusage(resource.RUSAGE_SELF)
        wall.append((time.perf_counter() - wall_started) * 1000)
        cpu.append((time.process_time() - cpu_started) * 1000)
        rss.append(_rss_kib())
        read_blocks.append(int(after_usage.ru_inblock - before_usage.ru_inblock))
        write_blocks.append(int(after_usage.ru_oublock - before_usage.ru_oublock))
    return {
        "slots": slots,
        "tasks_per_slot": tasks_per_slot,
        "logical_tasks": slots * tasks_per_slot,
        "repetitions": repetitions,
        "wall_ms": _percentiles(wall),
        "cpu_ms": _percentiles(cpu),
        "rss_kib": {"peak": max(rss), "raw": rss},
        "io_blocks": {"read_raw": read_blocks, "write_raw": write_blocks},
        "pages_read_raw": [sample["pages"]["read"] for sample in metric_samples],
        "cache_raw": [sample["cache"] for sample in metric_samples],
        "base_handle_ids": sorted(
            {sample["base_handle_id"] for sample in metric_samples}
        ),
        "active_overlays_raw": [sample["active_overlays"] for sample in metric_samples],
    }


def run(repetitions: int = 10) -> dict[str, Any]:
    if repetitions < 10:
        raise ValueError("repetitions must be at least 10")
    with tempfile.TemporaryDirectory() as directory:
        storage = Path(directory) / "arena"
        seed = PrismArena.publish(
            storage,
            "benchmark/repo",
            "benchmark-source",
            {
                "src/base.py": b"def base(value):\n    return value\n",
                "src/other.py": b"VALUE = 1\n",
            },
        )
        generation = seed.generation
        base_handle_id = seed.base_handle_id
        seed.close()
        cases = [
            _run_case(storage, generation, slots, tasks, repetitions)
            for slots, tasks in MATRIX
        ]
    return {
        "schema": BENCHMARK_SCHEMA,
        "issue": 213,
        "status": "measured",
        "matrix": [
            {"slots": slots, "tasks_per_slot": tasks} for slots, tasks in MATRIX
        ],
        "repetitions": repetitions,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "generation": generation,
        "base_handle_id": base_handle_id,
        "cases": cases,
        "claims": {
            "tokens": None,
            "tokens_reason": "NO_LLM_OR_PROVIDER_USED",
            "rust": None,
            "rust_reason": "PYTHON_REFERENCE_BENCHMARK_ONLY",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args()
    receipt = run(args.repetitions)
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
