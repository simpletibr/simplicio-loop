"""Benchmark the structured-concurrency runtime added for issue #212.

Measures wall-clock latency for running N independent tasks:
  - sequentially, via the existing synchronous ``pipeline.run_task`` loop
    (the unchanged baseline every CLI invocation still uses today);
  - concurrently, via ``pipeline.run_tasks_async`` at a bounded concurrency.

``run_task`` itself is replaced with a deterministic fake that sleeps for a
fixed duration to simulate blocking IO (subprocess/test-run latency) without
depending on a real LLM provider or git worktree — this isolates the
runtime's own dispatch/concurrency overhead from provider variance, which is
the thing issue #212 actually changed.
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio import pipeline  # noqa: E402

RESULTS_JSON = ROOT / "bench" / "results_async_pipeline_bench.json"
RESULTS_MD = ROOT / "bench" / "results_async_pipeline_bench.md"

TASK_COUNT = 8
SIMULATED_IO_SECONDS = 0.1
CONCURRENCY = 4


def _fake_run_task(**kwargs: Any) -> dict[str, Any]:
    time.sleep(SIMULATED_IO_SECONDS)
    return {"task_id": kwargs["target"], "applied": True}


def _task_specs(n: int) -> list[dict[str, Any]]:
    return [
        {
            "root": "/tmp/bench-repo",
            "stack": "python",
            "goal": "benchmark goal",
            "target": f"file_{i}.py",
            "criteria": "criteria",
            "constraints": "constraints",
        }
        for i in range(n)
    ]


def run_sequential(specs: list[dict[str, Any]]) -> float:
    start = time.perf_counter()
    for spec in specs:
        pipeline.run_task(**spec)
    return time.perf_counter() - start


def run_async(specs: list[dict[str, Any]], concurrency: int) -> float:
    start = time.perf_counter()
    asyncio.run(pipeline.run_tasks_async(specs, concurrency=concurrency))
    return time.perf_counter() - start


def main() -> int:
    original_run_task = pipeline.run_task
    pipeline.run_task = _fake_run_task
    try:
        specs = _task_specs(TASK_COUNT)
        sequential_seconds = run_sequential(specs)
        async_seconds = run_async(specs, CONCURRENCY)
    finally:
        pipeline.run_task = original_run_task

    speedup = sequential_seconds / async_seconds if async_seconds else float("inf")
    result = {
        "task_count": TASK_COUNT,
        "simulated_io_seconds": SIMULATED_IO_SECONDS,
        "concurrency": CONCURRENCY,
        "sequential_seconds": round(sequential_seconds, 4),
        "async_seconds": round(async_seconds, 4),
        "speedup_x": round(speedup, 2),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }

    RESULTS_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    RESULTS_MD.write_text(
        "# Async pipeline benchmark (issue #212)\n\n"
        f"- Tasks: {TASK_COUNT}, simulated IO per task: {SIMULATED_IO_SECONDS}s, "
        f"concurrency: {CONCURRENCY}\n"
        f"- Sequential (existing `run_task` loop): {result['sequential_seconds']}s\n"
        f"- Concurrent (`run_tasks_async`): {result['async_seconds']}s\n"
        f"- Speedup: {result['speedup_x']}x\n"
        f"- Platform: {result['platform']} / Python {result['python_version']}\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
