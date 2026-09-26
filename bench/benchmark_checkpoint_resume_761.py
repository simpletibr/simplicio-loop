from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from simplicio_loop.checkpoint_lifecycle import CheckpointLifecycle


def measure(repetitions: int, work_units: int) -> dict:
    cold, resumed, peaks = [], [], []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        base = root / "base"
        base.mkdir()
        run = CheckpointLifecycle(
            root / ".simplicio-loop" / "loop-runs",
            task_id="benchmark",
            attempt_id="attempt-1",
            source_commit="frozen",
            fast_generation="generation-1",
            base_path=base,
        )
        run.checkpoint("candidate", "orientation", "ORIENTED", work_units=work_units)
        for _ in range(repetitions):
            tracemalloc.start()
            started = time.perf_counter_ns()
            sum(hash(str(index)) for index in range(work_units))
            cold.append(time.perf_counter_ns() - started)
            _, peak = tracemalloc.get_traced_memory()
            peaks.append(peak)
            tracemalloc.stop()

            started = time.perf_counter_ns()
            checkpoint = run.load("candidate", "orientation")
            resumed.append(time.perf_counter_ns() - started)
            assert checkpoint["work_units"] == work_units
    avoided = max(0, work_units * repetitions)
    return {
        "schema": "simplicio.loop.checkpoint-benchmark/v1",
        "environment": {"repetitions": repetitions, "work_units": work_units},
        "restart_from_zero": {"median_ns": int(statistics.median(cold)), "samples_ns": cold},
        "resume": {"median_ns": int(statistics.median(resumed)), "samples_ns": resumed},
        "observed": {
            "work_units_avoided": avoided,
            "speedup": statistics.median(cold) / max(1, statistics.median(resumed)),
            "peak_tracemalloc_bytes": max(peaks),
            "llm_calls": None,
            "tokens": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--work-units", type=int, default=10_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    result = measure(max(1, args.repetitions), max(1, args.work_units))
    rendered = json.dumps(result, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
