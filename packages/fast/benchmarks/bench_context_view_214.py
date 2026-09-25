"""Cold/warm ContextView benchmark with ten Prism tasks and quality receipts."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from simplicio_fast.context_view import (
    ContextAuthority,
    ContextBudget,
    ContextIdentity,
    ContextItem,
    ContextViewService,
)


SCHEMA = "simplicio.fast.context-view-benchmark/v1"


def _percentiles(samples: list[float]) -> dict[str, object]:
    ordered = sorted(samples)
    return {
        "samples_ms": samples,
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
    }


def _fixture():
    authority = ContextAuthority(
        "benchmark-agent",
        "bench-fence",
        ("context:read",),
        ("src", "tests", "receipts"),
    )
    budget = ContextBudget(max_tokens=64, max_bytes=4096, max_nodes=8)
    items = [
        ContextItem.create(
            kind="fact",
            handle=f"fact-{index}",
            content=f"bounded fact {index}",
            base_generation="benchmark-g1",
            token_count=4,
            path=f"src/module_{index}.py",
            relevance=1 - index / 20,
            provenance=("mapper:benchmark-pack",),
        )
        for index in range(5)
    ]
    items.extend(
        [
            ContextItem.create(
                kind="test",
                handle="test-1",
                content="context view integration passed",
                base_generation="benchmark-g1",
                token_count=6,
                path="tests/test_context_view_214.py",
                provenance=("test:context-view",),
            ),
            ContextItem.create(
                kind="receipt",
                handle="receipt-1",
                content="receipt_hash=observed",
                base_generation="benchmark-g1",
                token_count=4,
                path="receipts/context-view.json",
                provenance=("receipt:benchmark",),
            ),
        ]
    )
    items.extend(
        ContextItem.create(
            kind="span",
            handle=f"background-{index}",
            content=("background context " + str(index) + " ") * 8,
            base_generation="benchmark-g1",
            token_count=20,
            path=f"src/background_{index}.py",
            relevance=0.1,
            provenance=("mapper:benchmark-pack",),
        )
        for index in range(193)
    )
    expected = {
        "test-1",
        "receipt-1",
        *(f"fact-{index}" for index in range(5)),
        "background-0",
    }
    return authority, budget, items, expected


def _request(task: int, authority: ContextAuthority, budget: ContextBudget):
    from simplicio_fast.context_view import ContextViewRequest

    return ContextViewRequest(
        repository="benchmark/context-view",
        identity=ContextIdentity(
            "benchmark-prism",
            f"slot-{task % 4}",
            f"task-{task}",
            1,
            f"agent-{task}",
            "implementer",
        ),
        base_generation="benchmark-g1",
        requested_capability="context:read",
        goal_fragment="benchmark bounded context selection",
        budget=budget,
        authority_digest=authority.digest,
        fence=authority.fence,
    )


def run(*, repetitions: int = 10, tasks: int = 10) -> dict[str, object]:
    if repetitions < 10:
        raise ValueError("repetitions must be at least ten")
    if tasks != 10:
        raise ValueError("the preregistered workload contains exactly ten tasks")
    authority, budget, items, expected = _fixture()
    cold_samples: list[float] = []
    warm_samples: list[float] = []
    cold_quality: list[float] = []
    warm_quality: list[float] = []
    bounded_coverages: list[float] = []
    warm_hits = 0
    for _ in range(repetitions):
        started = time.perf_counter()
        for task in range(tasks):
            view = ContextViewService().materialize(
                _request(task, authority, budget), authority, items
            )
            selected = {item["handle"] for item in view.selected}
            cold_quality.append(len(selected & expected) / len(expected))
            bounded_coverages.append(float(view.quality["coverage"]))
        cold_samples.append((time.perf_counter() - started) * 1000)

        service = ContextViewService()
        service.materialize(_request(0, authority, budget), authority, items)
        started = time.perf_counter()
        for task in range(tasks):
            view = service.materialize(
                _request(task, authority, budget), authority, items
            )
            warm_hits += int(view.cache["outcome"] == "hit")
            selected = {item["handle"] for item in view.selected}
            warm_quality.append(len(selected & expected) / len(expected))
            bounded_coverages.append(float(view.quality["coverage"]))
        warm_samples.append((time.perf_counter() - started) * 1000)

    return {
        "schema": SCHEMA,
        "status": "measured",
        "workload": {
            "tasks": tasks,
            "repetitions": repetitions,
            "base_generation": "benchmark-g1",
            "overlay": None,
            "budget": budget.record(),
            "items_per_task": len(items),
        },
        "cold": {
            **_percentiles(cold_samples),
            "cache_policy": "empty cache per task",
            "quality_coverage_mean": statistics.mean(cold_quality),
            "bounded_candidate_coverage_mean": statistics.mean(
                bounded_coverages[: repetitions * tasks]
            ),
        },
        "warm": {
            **_percentiles(warm_samples),
            "cache_policy": "shared equivalent base selection",
            "cache_hits_observed": warm_hits,
            "cache_lookups": repetitions * tasks,
            "quality_coverage_mean": statistics.mean(warm_quality),
            "bounded_candidate_coverage_mean": statistics.mean(
                bounded_coverages[repetitions * tasks :]
            ),
        },
        "quality_gate": {
            "cold_coverage_equal_warm": cold_quality == warm_quality,
            "minimum_expected_coverage": min(cold_quality + warm_quality),
            "expected_handles": sorted(expected),
            "abstentions": 0,
        },
        "token_savings": None,
        "token_savings_reason": "MODEL_TOKEN_ACCOUNTING_NOT_OBSERVED",
        "python": sys.version.split()[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--tasks", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args()
    receipt = run(repetitions=args.repetitions, tasks=args.tasks)
    encoded = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
