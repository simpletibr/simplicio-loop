"""Provider-free raw-count/latency benchmark for issue #258."""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

from simplicio.atomic_execution import AttemptContext, execute_work_item_once
from simplicio.plan_compiler import EffectPlan, PlanNode, RecordingEffectSink


def percentile(samples: list[float], quantile: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * quantile))]


def main() -> int:
    runs = 5_000
    node = PlanNode("edit", "edit.apply")
    effect = EffectPlan("effect-1", "edit", "write", "runtime", "stable-key")
    sink = RecordingEffectSink()
    latencies: list[float] = []
    successes = 0
    for index in range(runs):
        started = time.perf_counter_ns()
        observation = execute_work_item_once(
            node,
            AttemptContext(f"attempt-{index}", "lease-1", "fence-1", "snapshot-1"),
            effects=[effect],
            verifications=[],
            effect_sink=sink,
        )
        latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        successes += observation.outcome == "effect_submitted"
    result = {
        "schema": "simplicio.dev-cli.atomic-attempt-benchmark/v1",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "runs": runs,
        "atomic_attempts": runs,
        "effect_calls": len(sink.received),
        "successes": successes,
        "ac_evidence_success_rate": successes / runs,
        "model_calls": 0,
        "subprocesses": 0,
        "threads_created": 0,
        "worktrees_created": 0,
        "tokens": 0,
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 6),
            "p50": round(percentile(latencies, 0.50), 6),
            "p95": round(percentile(latencies, 0.95), 6),
        },
    }
    output = Path(__file__).with_name("results_atomic_attempt.json")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
