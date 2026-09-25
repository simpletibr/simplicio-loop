"""Quality-first issue #186 benchmark with raw per-run evidence.

This benchmark uses an explicitly labelled deterministic fake InferenceBackend
to exercise the contract. It does not claim LiteRT device throughput.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import resource
import statistics
import tempfile
import time
from pathlib import Path

from simplicio_fast.semantic_scoring import (
    INFERENCE_BACKEND_SCHEMA,
    DerivedVectorStore,
    ModelIdentity,
    RuntimeEmbeddingProvider,
    SemanticBudgets,
    SemanticScorer,
    SourceDocument,
)


REPETITIONS = 10
MODEL_SHA = "186" * 21 + "1"
CORPUS = (
    SourceDocument.create(
        "a_cache", "MemoStore reuses computed values in a bounded cache."
    ),
    SourceDocument.create(
        "b_database", "Repository persists records with transactions."
    ),
    SourceDocument.create(
        "c_logging", "AuditSink writes structured diagnostic events."
    ),
    SourceDocument.create(
        "x_parser", "AstReader parses syntax trees and source tokens."
    ),
    SourceDocument.create(
        "y_retry", "DeadlineController retries transient failures safely."
    ),
    SourceDocument.create("z_auth", "LoginManager validates identity and credentials."),
)
QUERIES = (
    ("authenticate user", "z_auth"),
    ("memoization", "a_cache"),
    ("failure deadline", "y_retry"),
    ("source grammar", "x_parser"),
    ("sign in account", "z_auth"),
    ("reuse calculation", "a_cache"),
)
GROUPS = (
    (
        "auth",
        "authenticate",
        "login",
        "identity",
        "credential",
        "sign",
        "account",
        "user",
    ),
    ("cache", "memo", "memoization", "reuse", "calculation", "computed"),
    ("retry", "retries", "failure", "transient", "deadline"),
    ("parser", "parse", "parses", "syntax", "grammar", "ast", "source"),
    ("database", "repository", "persist", "record", "transaction"),
    ("log", "audit", "diagnostic", "event"),
)


def vector(text: str) -> tuple[float, ...]:
    lowered = text.casefold()
    return tuple(float(sum(lowered.count(word) for word in group)) for group in GROUPS)


class FrozenInferenceBackend:
    def capabilities(self):
        return {"schema": INFERENCE_BACKEND_SCHEMA, "operations": ["embeddings"]}

    def infer(self, request, *, deadline, cancel_event):
        return {
            "schema": "simplicio.inference-result/v1",
            "model_sha256": MODEL_SHA,
            "vectors": [vector(text) for text in request["inputs"]],
        }


def reciprocal_rank(ids: list[str], relevant: str) -> float:
    try:
        return 1.0 / (ids.index(relevant) + 1)
    except ValueError:
        return 0.0


def ndcg(ids: list[str], relevant: str) -> float:
    try:
        return 1.0 / math.log2(ids.index(relevant) + 2)
    except ValueError:
        return 0.0


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def run(output: Path, repetitions: int = REPETITIONS) -> dict[str, object]:
    if repetitions < 10:
        raise ValueError("quality benchmark requires at least ten repetitions")
    identity = ModelIdentity(
        model="frozen-quality-fixture",
        version="issue-186-v1",
        sha256=MODEL_SHA,
        preprocessing="lowercase-concept-groups-v1",
        dimension=len(GROUPS),
        max_tokens=128,
        license="repository-test-fixture",
    )
    raw: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="sfast-semantic-186-") as temporary:
        semantic = SemanticScorer(
            provider=RuntimeEmbeddingProvider(FrozenInferenceBackend(), identity),
            store=DerivedVectorStore(temporary),
            budgets=SemanticBudgets(max_selected=3, max_selected_tokens=32),
            minimum_confidence=0,
        )
        baseline = SemanticScorer(
            budgets=SemanticBudgets(max_selected=3, max_selected_tokens=32),
            minimum_confidence=0,
        )
        for mode, scorer in (
            ("baseline", baseline),
            ("runtime-contract-fixture", semantic),
        ):
            for repetition in range(repetitions):
                for query, relevant in QUERIES:
                    wall_start = time.perf_counter_ns()
                    cpu_start = time.process_time_ns()
                    receipt = scorer.score(
                        generation="frozen-generation-186",
                        query=query,
                        candidates=CORPUS,
                    )
                    wall_ms = (time.perf_counter_ns() - wall_start) / 1_000_000
                    cpu_ms = (time.process_time_ns() - cpu_start) / 1_000_000
                    selected = [item["canonical_id"] for item in receipt["selected"]]
                    raw.append(
                        {
                            "mode": mode,
                            "repetition": repetition,
                            "query": query,
                            "relevant": relevant,
                            "selected": selected,
                            "recall_at_3": float(relevant in selected[:3]),
                            "reciprocal_rank": reciprocal_rank(selected, relevant),
                            "ndcg_at_3": ndcg(selected[:3], relevant),
                            "token_budget_covered": float(
                                relevant in selected
                                and receipt["usage"]["selected_tokens"]
                                <= receipt["budgets"]["max_selected_tokens"]
                            ),
                            "wall_ms": wall_ms,
                            "cpu_ms": cpu_ms,
                            "rss_kib": resource.getrusage(
                                resource.RUSAGE_SELF
                            ).ru_maxrss,
                            "fallback_reason": receipt["fallback"]["reason_code"],
                            "cache_hit": receipt["cache"]["hit"],
                        }
                    )
    summary: dict[str, object] = {}
    for mode in ("baseline", "runtime-contract-fixture"):
        rows = [row for row in raw if row["mode"] == mode]
        walls = [float(row["wall_ms"]) for row in rows]
        cpus = [float(row["cpu_ms"]) for row in rows]
        summary[mode] = {
            "runs": len(rows),
            "recall_at_3": statistics.fmean(float(row["recall_at_3"]) for row in rows),
            "mrr": statistics.fmean(float(row["reciprocal_rank"]) for row in rows),
            "ndcg_at_3": statistics.fmean(float(row["ndcg_at_3"]) for row in rows),
            "token_budget_coverage": statistics.fmean(
                float(row["token_budget_covered"]) for row in rows
            ),
            "latency_ms": {
                "median": statistics.median(walls),
                "p95": percentile(walls, 0.95),
                "max": max(walls),
            },
            "cpu_ms": {
                "median": statistics.median(cpus),
                "p95": percentile(cpus, 0.95),
            },
            "peak_rss_kib": max(int(row["rss_kib"]) for row in rows),
        }
    baseline_quality = summary["baseline"]
    semantic_quality = summary["runtime-contract-fixture"]
    receipt = {
        "schema": "simplicio.fast.semantic-quality-benchmark/v1",
        "issue": 186,
        "repetitions": repetitions,
        "queries_per_repetition": len(QUERIES),
        "corpus_sha256": __import__("hashlib")
        .sha256(
            json.dumps(
                [(item.canonical_id, item.source_sha256) for item in CORPUS],
                separators=(",", ":"),
            ).encode()
        )
        .hexdigest(),
        "model": identity.record(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "summary": summary,
        "quality_gate": {
            "recall_non_regression": (
                semantic_quality["recall_at_3"] >= baseline_quality["recall_at_3"]
            ),
            "mrr_non_regression": semantic_quality["mrr"] >= baseline_quality["mrr"],
            "ndcg_non_regression": (
                semantic_quality["ndcg_at_3"] >= baseline_quality["ndcg_at_3"]
            ),
            "token_budget_non_regression": (
                semantic_quality["token_budget_coverage"]
                >= baseline_quality["token_budget_coverage"]
            ),
        },
        "raw_runs": raw,
        "limitations": [
            "Inference uses a deterministic frozen InferenceBackend/v1 fixture, not a LiteRT device.",
            "No on-device acceleration or provider token/cost claim is made.",
            "RSS is process high-water mark and may include interpreter baseline.",
        ],
    }
    if not all(receipt["quality_gate"].values()):
        raise RuntimeError("quality gate regressed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("bench/results/semantic_scoring_186.json")
    )
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    args = parser.parse_args()
    receipt = run(args.output, args.repetitions)
    print(json.dumps(receipt["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
