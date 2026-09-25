"""Measure canonical PlanDAG projection creation and validation."""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from simplicio.plan_compiler import (
    PlanDAG,
    PlanNode,
    create_plan_projection,
    validate_plan_projection,
)


def run(iterations: int) -> dict[str, float | int]:
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    plan = PlanDAG(
        plan_id="plan-benchmark",
        goal_id="goal-benchmark",
        context_snapshot_id="snapshot-benchmark",
        revision="1",
        nodes=[PlanNode(node_id=f"node-{index}", capability="test.run") for index in range(20)],
        producer_id="simplicio-dev-cli",
        consumer_id="simplicio-runtime",
    )
    elapsed_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        projection = create_plan_projection(
            plan,
            target_consumer="simplicio-runtime",
            transformation_id="runtime.exec-view/v1",
        )
        validate_plan_projection(projection, source_plan=plan)
        elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(elapsed_ms)
    return {
        "iterations": iterations,
        "nodes": len(plan.nodes),
        "mean_ms": statistics.fmean(elapsed_ms),
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "operations_per_second": iterations / (sum(elapsed_ms) / 1000),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1_000)
    args = parser.parse_args()
    result = run(args.iterations)
    lines = ["# Plan contract benchmark", ""]
    for key, value in result.items():
        rendered = f"{value:.6f}" if isinstance(value, float) else str(value)
        lines.append(f"- {key}: {rendered}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
