"""Deterministic labeled quality corpus for advisory capability ranking (#346)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
from typing import Any

from simplicio_fast.capability_ranking import CapabilityCandidate, rank_capabilities


SCHEMA = "simplicio.fast.capability-quality-receipt/v1"
DATASET_SCHEMA = "simplicio.fast.capability-quality-dataset/v1"


CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "python-query",
        "required": ["query", "python"],
        "scope": "repo-a",
        "top_k": 2,
        "relevance": {
            "worker:python-fast": 3,
            "worker:python-safe": 2,
        },
        "candidates": [
            {
                "handle": "worker:python-fast",
                "kind": "worker",
                "version": "1",
                "capabilities": ["query", "python"],
                "estimated_cost": 2,
                "estimated_latency_ms": 10,
                "policy_eligible": True,
                "scope": "repo-a",
                "metric_class": "measured",
            },
            {
                "handle": "worker:python-safe",
                "kind": "worker",
                "version": "1",
                "capabilities": ["query", "python"],
                "estimated_cost": 4,
                "estimated_latency_ms": 20,
                "policy_eligible": True,
                "scope": "repo-a",
                "metric_class": "measured",
            },
            {
                "handle": "worker:rust-only",
                "kind": "worker",
                "version": "1",
                "capabilities": ["query", "rust"],
                "estimated_cost": 1,
                "estimated_latency_ms": 1,
                "policy_eligible": True,
                "scope": "repo-a",
                "metric_class": "measured",
            },
            {
                "handle": "worker:python-unknown-policy",
                "kind": "worker",
                "version": "1",
                "capabilities": ["query", "python"],
                "estimated_cost": 1,
                "estimated_latency_ms": 1,
                "policy_eligible": None,
                "scope": "repo-a",
                "metric_class": "unknown",
            },
        ],
    },
    {
        "id": "bounded-tool",
        "required": ["tool", "bounded"],
        "scope": "tenant-a",
        "top_k": 2,
        "relevance": {"tool:bounded-fast": 3, "tool:bounded-safe": 1},
        "candidates": [
            {
                "handle": "tool:bounded-fast",
                "kind": "tool",
                "version": "2",
                "capabilities": ["tool", "bounded"],
                "estimated_cost": 2,
                "estimated_latency_ms": 8,
                "policy_eligible": True,
                "scope": "tenant-a",
                "metric_class": "measured",
            },
            {
                "handle": "tool:bounded-safe",
                "kind": "tool",
                "version": "2",
                "capabilities": ["tool", "bounded"],
                "estimated_cost": 5,
                "estimated_latency_ms": 15,
                "policy_eligible": True,
                "scope": "tenant-a",
                "metric_class": "estimated",
            },
            {
                "handle": "tool:foreign-tenant",
                "kind": "tool",
                "version": "2",
                "capabilities": ["tool", "bounded"],
                "estimated_cost": 1,
                "estimated_latency_ms": 1,
                "policy_eligible": True,
                "scope": "tenant-b",
                "metric_class": "measured",
            },
            {
                "handle": "tool:hard-incompatible",
                "kind": "tool",
                "version": "2",
                "capabilities": ["tool"],
                "estimated_cost": 0,
                "estimated_latency_ms": 0,
                "policy_eligible": True,
                "scope": "tenant-a",
                "metric_class": "simulated",
            },
        ],
    },
)


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ndcg(relevances: list[int], ideal: list[int]) -> float:
    def dcg(values: list[int]) -> float:
        return sum(value / math.log2(index + 2) for index, value in enumerate(values))

    ideal_score = dcg(ideal)
    return dcg(relevances) / ideal_score if ideal_score else 1.0


def run() -> dict[str, Any]:
    scenario_results: list[dict[str, Any]] = []
    for case in CASES:
        candidates = [CapabilityCandidate(**item) for item in case["candidates"]]
        result = rank_capabilities(
            candidates,
            tuple(case["required"]),
            required_scope=case["scope"],
            max_results=len(candidates),
        )
        ranked = result["candidates"]
        top = ranked[: int(case["top_k"])]
        relevance = case["relevance"]
        top_relevance = [int(relevance.get(item["handle"], 0)) for item in top]
        ideal = sorted((int(value) for value in relevance.values()), reverse=True)[: len(top)]
        relevant_total = sum(1 for value in relevance.values() if int(value) > 0)
        hits = sum(value > 0 for value in top_relevance)
        eligible_handles = [item["handle"] for item in ranked if item["eligible"]]
        scenario_results.append(
            {
                "id": case["id"],
                "top_k": case["top_k"],
                "ranked_handles": [item["handle"] for item in ranked],
                "eligible_handles": eligible_handles,
                "hard_incompatible_eligible": any(
                    item["handle"] == "tool:hard-incompatible" and item["eligible"]
                    for item in ranked
                ),
                "precision_at_k": hits / len(top) if top else 0.0,
                "recall_at_k": hits / relevant_total if relevant_total else 1.0,
                "ndcg_at_k": _ndcg(top_relevance, ideal),
                "authority": result["authority"],
                "metric_classes": sorted({item["metric_class"] for item in ranked}),
            }
        )
    return {
        "schema": SCHEMA,
        "status": "pass",
        "dataset": {
            "schema": DATASET_SCHEMA,
            "id": "capability-advisory-v1",
            "case_count": len(CASES),
            "digest": _digest(CASES),
        },
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "scenarios": scenario_results,
        "aggregate": {
            "precision_at_k": sum(item["precision_at_k"] for item in scenario_results) / len(scenario_results),
            "recall_at_k": sum(item["recall_at_k"] for item in scenario_results) / len(scenario_results),
            "ndcg_at_k": sum(item["ndcg_at_k"] for item in scenario_results) / len(scenario_results),
            "hard_incompatible_eligible": any(
                item["hard_incompatible_eligible"] for item in scenario_results
            ),
            "authority": "advisory_only",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
