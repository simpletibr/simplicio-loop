"""Held-out evaluation for the optional model lane in issue #517.

The assisted lane deliberately uses a deterministic topic fixture.  It proves
the RuntimeEmbeddingProvider wiring and evaluation protocol, but it is not a
learned model and must never be reported as production model evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from simplicio_fast import __version__
from simplicio_fast.semantic_scoring import (
    INFERENCE_BACKEND_SCHEMA,
    INFERENCE_RESULT_SCHEMA,
    DerivedVectorStore,
    ModelIdentity,
    RuntimeEmbeddingProvider,
    SemanticBudgets,
    SemanticScorer,
    SourceDocument,
)


SCHEMA = "simplicio.fast.optional-model-evaluation-receipt/v1"
DATASET_SCHEMA = "simplicio.fast.optional-model-evaluation-dataset/v1"
DEFAULT_DATASET = (
    Path(__file__).parents[1]
    / "fixtures"
    / "optional-model"
    / "v1"
    / "issue517-task-corpus.json"
)
REPETITIONS = 10
TOP_K = 3
GENERATION = "issue517-fixture-mapper-g1"
MODEL_DESCRIPTOR = "issue-517-deterministic-topic-fixture-v1"
MODEL_SHA = hashlib.sha256(MODEL_DESCRIPTOR.encode("utf-8")).hexdigest()
QUALITY_DELTA_THRESHOLD = 0.05
MAX_MODEL_P95_LATENCY_MS = 20.0
MAX_MODEL_RSS_DELTA_KIB = 32 * 1024

# These groups are a fixed contract fixture, not a trained representation. No
# split is used to train or tune this fixture; evaluation tasks contain
# paraphrases and exact-symbol/adversarial cases.
TOPIC_GROUPS = (
    ("semantic", "scorer", "ranking", "rank"),
    ("query", "plan", "symbol", "path", "index", "graph", "relation", "call"),
    ("knowledge", "precedent", "guidance", "provenance", "audit", "prior"),
    ("context", "budget", "limit", "bytes", "tokens", "prompt", "bounded"),
    ("mapper", "canonical", "handoff", "generation", "stable", "graph"),
    ("delivery", "changeset", "guarded", "source", "hash"),
    ("parser", "syntax", "ast", "language"),
    ("runtime", "inference", "model", "backend"),
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)
    return ordered[position]


def _repository_revision() -> tuple[str | None, str | None]:
    """Read the checkout revision without treating a missing Git repo as truth."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(Path(__file__).parents[1]), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError as error:
        return None, f"git_unavailable:{type(error).__name__}"
    revision = completed.stdout.strip()
    if completed.returncode != 0 or len(revision) != 40:
        return None, "git_revision_unavailable"
    return revision, None


def _topic_vector(text: str) -> tuple[float, ...]:
    lowered = text.casefold()
    return tuple(float(sum(lowered.count(word) for word in group)) for group in TOPIC_GROUPS)


class DeterministicTopicFixtureBackend:
    """A hermetic backend fixture; this class is not a learned model."""

    def capabilities(self) -> Mapping[str, Any]:
        return {"schema": INFERENCE_BACKEND_SCHEMA, "operations": ["embeddings"]}

    def infer(
        self,
        request: Mapping[str, Any],
        *,
        deadline: float,
        cancel_event: object,
    ) -> Mapping[str, Any]:
        del deadline, cancel_event
        return {
            "schema": INFERENCE_RESULT_SCHEMA,
            "model_sha256": MODEL_SHA,
            "vectors": [_topic_vector(text) for text in request["inputs"]],
        }


def _model_identity() -> ModelIdentity:
    return ModelIdentity(
        model="deterministic-topic-fixture",
        version="issue-517-v1",
        sha256=MODEL_SHA,
        preprocessing="casefold-curated-topic-groups-v1",
        dimension=len(TOPIC_GROUPS),
        max_tokens=128,
        license="repository-test-fixture",
    )


def _load_dataset(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("schema") != DATASET_SCHEMA:
        raise ValueError("optional_model_dataset_schema_invalid")
    if dataset.get("generation") != GENERATION:
        raise ValueError("optional_model_dataset_generation_invalid")
    candidates = dataset.get("candidates")
    splits = dataset.get("splits")
    if not isinstance(candidates, list) or not isinstance(splits, dict):
        raise ValueError("optional_model_dataset_shape_invalid")
    if any(not isinstance(item, dict) for item in candidates):
        raise ValueError("optional_model_candidate_invalid")
    for candidate in candidates:
        if (
            not isinstance(candidate.get("canonical_id"), str)
            or not candidate["canonical_id"].strip()
            or not isinstance(candidate.get("text"), str)
            or not candidate["text"].strip()
            or not isinstance(candidate.get("evidence"), dict)
        ):
            raise ValueError("optional_model_candidate_invalid")
    candidate_ids = [item["canonical_id"] for item in candidates]
    if any(not isinstance(value, str) or not value for value in candidate_ids):
        raise ValueError("optional_model_candidate_id_invalid")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("optional_model_candidate_id_duplicate")
    query_ids: list[str] = []
    for split in ("train", "dev", "evaluation"):
        queries = splits.get(split)
        if not isinstance(queries, list) or not queries:
            raise ValueError(f"optional_model_{split}_split_invalid")
        for query in queries:
            if (
                not isinstance(query, dict)
                or not isinstance(query.get("id"), str)
                or not query["id"].strip()
                or not isinstance(query.get("task"), str)
                or not query["task"].strip()
            ):
                raise ValueError("optional_model_query_invalid")
            query_ids.append(query["id"])
            expected = query.get("expected")
            if not isinstance(expected, list) or any(
                item not in candidate_ids for item in expected
            ):
                raise ValueError("optional_model_expected_invalid")
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("optional_model_query_id_duplicate")
    if not isinstance(dataset.get("provenance"), dict):
        raise ValueError("optional_model_provenance_missing")
    return dataset


def _documents(
    candidates: Sequence[Mapping[str, Any]], structural_scores: Mapping[str, Any]
) -> tuple[SourceDocument, ...]:
    documents = []
    for candidate in candidates:
        canonical_id = str(candidate["canonical_id"])
        raw_score = structural_scores.get(canonical_id, 0.0)
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise ValueError("optional_model_structural_score_invalid")
        documents.append(
            SourceDocument.create(
                canonical_id,
                candidate["text"],
                structural_score=float(raw_score),
            )
        )
    return tuple(documents)


def _rank(row: Mapping[str, Any], ranked: Sequence[str]) -> int:
    for index, canonical_id in enumerate(ranked, start=1):
        if canonical_id in row["expected"]:
            return index
    return 0


def _ndcg(ranked: Sequence[str], expected: set[str], k: int) -> float:
    actual = ranked[:k]
    dcg = sum(
        (1.0 if canonical_id in expected else 0.0) / math.log2(index + 2)
        for index, canonical_id in enumerate(actual)
    )
    ideal = sum(
        1.0 / math.log2(index + 2)
        for index in range(min(k, len(expected)))
    )
    return dcg / ideal if ideal else 0.0


def _evaluate(
    scorer: SemanticScorer,
    *,
    mode: str,
    candidates: Sequence[Mapping[str, Any]],
    evaluation: Sequence[Mapping[str, Any]],
    generation: str,
    evidence: Mapping[str, Mapping[str, Any]],
    repetitions: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repetition in range(repetitions):
        for query in evaluation:
            started = time.perf_counter_ns()
            cpu_started = time.process_time_ns()
            receipt = scorer.score(
                generation=generation,
                query=str(query["task"]),
                candidates=_documents(candidates, query.get("structural_scores", {})),
            )
            wall_ms = (time.perf_counter_ns() - started) / 1_000_000
            cpu_ms = (time.process_time_ns() - cpu_started) / 1_000_000
            ranked = [str(item["canonical_id"]) for item in receipt["results"]]
            selected = [str(item["canonical_id"]) for item in receipt["selected"]]
            expected = {str(item) for item in query["expected"]}
            hits_at_1 = len(set(selected[:1]).intersection(expected))
            selected_top_k = selected[:TOP_K]
            hits = len(set(selected_top_k).intersection(expected))
            quality_evaluable = bool(expected)
            provenance_ok = all(
                item["provenance"]["generation"] == generation
                and item["provenance"]["source_sha256"]
                == evidence[item["canonical_id"]]["source_sha256"]
                and item["canonical_id"] in evidence
                for item in receipt["results"]
            )
            row = {
                "mode": mode,
                "repetition": repetition,
                "id": query["id"],
                "task": query["task"],
                "ranked": ranked,
                "selected": selected,
                "expected": sorted(expected),
                "exact_symbol": bool(query.get("exact_symbol", False)),
                "adversarial": bool(query.get("adversarial", False)),
                "ambiguous": bool(query.get("ambiguous", False)),
                "quality_evaluable": quality_evaluable,
                "recall_at_1": hits_at_1 / len(expected)
                if quality_evaluable
                else None,
                "recall_at_3": hits / len(expected) if quality_evaluable else None,
                "precision_at_3": hits / len(selected_top_k) if selected_top_k else 0.0,
                "mrr": 1.0 / _rank(query, ranked) if _rank(query, ranked) else 0.0,
                "ndcg_at_3": _ndcg(ranked, expected, TOP_K)
                if quality_evaluable
                else None,
                "completion_quality": float(expected.issubset(selected))
                if quality_evaluable
                else None,
                "target_rank": _rank(query, ranked),
                "budget_compliant": (
                    receipt["usage"]["request_bytes"] <= receipt["budgets"]["max_request_bytes"]
                    and receipt["usage"]["selected_tokens"]
                    <= receipt["budgets"]["max_selected_tokens"]
                ),
                "provenance_ok": provenance_ok,
                "fallback_reason": receipt["fallback"]["reason_code"],
                "cache_hit": receipt["cache"]["hit"],
                "local_inference_ms": float(receipt["metrics"]["embed_rerank_ms"]),
                "wall_ms": wall_ms,
                "cpu_ms": cpu_ms,
                "rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            }
            rows.append(row)
    return rows


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    quality = [row for row in rows if row["quality_evaluable"]]
    wall = [float(row["wall_ms"]) for row in rows]
    cpu = [float(row["cpu_ms"]) for row in rows]
    inference = [float(row["local_inference_ms"]) for row in rows]
    return {
        "runs": len(rows),
        "evaluation_queries": len({row["id"] for row in rows}),
        "quality_queries": len({row["id"] for row in quality}),
        "recall_at_3": statistics.fmean(float(row["recall_at_3"]) for row in quality),
        "recall_at_1": statistics.fmean(float(row["recall_at_1"]) for row in quality),
        "precision_at_3": statistics.fmean(float(row["precision_at_3"]) for row in quality),
        "mrr": statistics.fmean(float(row["mrr"]) for row in quality),
        "ndcg_at_3": statistics.fmean(float(row["ndcg_at_3"]) for row in quality),
        "completion_quality": statistics.fmean(
            float(row["completion_quality"]) for row in quality
        ),
        "budget_compliance": all(bool(row["budget_compliant"]) for row in rows),
        "provenance_checks": all(bool(row["provenance_ok"]) for row in rows),
        "exact_symbol_rows": sum(bool(row["exact_symbol"]) for row in rows),
        "adversarial_rows": sum(bool(row["adversarial"]) for row in rows),
        "latency_ms": {
            "p50": statistics.median(wall),
            "p95": _percentile(wall, 0.95),
            "max": max(wall),
        },
        "cpu_ms": {
            "p50": statistics.median(cpu),
            "p95": _percentile(cpu, 0.95),
        },
        "local_inference_latency_ms": {
            "p50": statistics.median(inference),
            "p95": _percentile(inference, 0.95),
            "max": max(inference),
        },
        "peak_rss_kib": max(int(row["rss_kib"]) for row in rows),
        "cache_hit_rate": sum(bool(row["cache_hit"]) for row in rows) / len(rows),
        "remote_tokens_per_green_work_item": None,
        "remote_tokens_reason": "local_inference_no_provider_token_telemetry",
        "total_cost": None,
        "total_cost_reason": "local_inference_no_cost_telemetry",
    }


def run(
    dataset_path: Path = DEFAULT_DATASET, *, repetitions: int = REPETITIONS
) -> dict[str, Any]:
    if repetitions < 10:
        raise ValueError("issue 517 evaluation requires at least ten repetitions")
    dataset = _load_dataset(dataset_path)
    candidates = dataset["candidates"]
    evaluation = dataset["splits"]["evaluation"]
    evidence: dict[str, dict[str, Any]] = {}
    repository_root = Path(__file__).parents[1]
    for candidate in candidates:
        canonical_id = str(candidate["canonical_id"])
        source_path = repository_root / str(candidate["evidence"]["path"])
        if not source_path.is_file():
            raise ValueError(f"optional_model_evidence_source_missing:{source_path}")
        evidence[canonical_id] = {
            **dict(candidate["evidence"]),
            "generation": GENERATION,
            "source_sha256": hashlib.sha256(
                str(candidate["text"]).encode("utf-8")
            ).hexdigest(),
            "source_file_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }

    budgets = SemanticBudgets(
        max_candidates=len(candidates),
        max_selected=TOP_K,
        max_request_bytes=32_000,
        max_selected_tokens=96,
    )
    baseline = SemanticScorer(budgets=budgets, minimum_confidence=0.0)
    identity = _model_identity()
    with tempfile.TemporaryDirectory(prefix="sfast-optional-model-517-") as directory:
        assisted = SemanticScorer(
            provider=RuntimeEmbeddingProvider(
                DeterministicTopicFixtureBackend(), identity
            ),
            store=DerivedVectorStore(directory),
            budgets=budgets,
            minimum_confidence=0.0,
        )
        rows = []
        rows.extend(
            _evaluate(
                baseline,
                mode="deterministic-baseline",
                candidates=candidates,
                evaluation=evaluation,
                generation=GENERATION,
                evidence=evidence,
                repetitions=repetitions,
            )
        )
        rows.extend(
            _evaluate(
                assisted,
                mode="optional-contract-fixture",
                candidates=candidates,
                evaluation=evaluation,
                generation=GENERATION,
                evidence=evidence,
                repetitions=repetitions,
            )
        )

    by_mode = {
        mode: [row for row in rows if row["mode"] == mode]
        for mode in ("deterministic-baseline", "optional-contract-fixture")
    }
    summaries = {mode: _summary(mode_rows) for mode, mode_rows in by_mode.items()}
    baseline_by_query = {
        (row["id"], row["repetition"]): row
        for row in by_mode["deterministic-baseline"]
    }
    assisted_by_query = {
        (row["id"], row["repetition"]): row
        for row in by_mode["optional-contract-fixture"]
    }
    exact_non_regression = all(
        assisted_by_query[key]["target_rank"]
        <= baseline_by_query[key]["target_rank"]
        for key in baseline_by_query
        if baseline_by_query[key]["exact_symbol"]
        and baseline_by_query[key]["target_rank"]
    )
    rss_delta = (
        summaries["optional-contract-fixture"]["peak_rss_kib"]
        - summaries["deterministic-baseline"]["peak_rss_kib"]
    )
    model_summary = summaries["optional-contract-fixture"]
    baseline_summary = summaries["deterministic-baseline"]
    quality_delta = model_summary["mrr"] - baseline_summary["mrr"]
    recall_at_1_delta = (
        model_summary["recall_at_1"] - baseline_summary["recall_at_1"]
    )
    revision, revision_reason = _repository_revision()
    promotion_gate = {
        "held_out_metric_improved": recall_at_1_delta >= QUALITY_DELTA_THRESHOLD,
        "exact_symbol_non_regression": exact_non_regression,
        "budget_compliance": model_summary["budget_compliance"],
        "canonical_provenance": model_summary["provenance_checks"],
        "latency_limit": model_summary["latency_ms"]["p95"]
        <= MAX_MODEL_P95_LATENCY_MS,
        "rss_limit": rss_delta <= MAX_MODEL_RSS_DELTA_KIB,
        "authorized_production_model": False,
    }
    receipt = {
        "schema": SCHEMA,
        "issue": 517,
        "status": "not_promoted",
        "decision": "keep_deterministic_default_fixture_only",
        "dataset": {
            "schema": DATASET_SCHEMA,
            "id": dataset["dataset_id"],
            "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "generation": GENERATION,
            "candidate_count": len(candidates),
            "split_counts": {
                split: len(dataset["splits"][split])
                for split in ("train", "dev", "evaluation")
            },
            "evaluation_is_held_out": True,
            "provenance": dataset["provenance"],
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "resource_unit": "KiB",
        },
        "repository": {
            "name": dataset["repository"],
            "revision": revision,
            "revision_reason": revision_reason,
        },
        "artifacts": {
            "fast": {
                "version": __version__,
                "binary_digest": None,
                "binary_digest_reason": "central_native_binary_unavailable",
            },
            "mapper": {
                "generation": GENERATION,
                "artifact_digest": None,
                "artifact_digest_reason": "integrated_mapper_artifact_unavailable",
            },
        },
        "baseline_scope": {
            "explicit_symbol_path": "Snapshot exact/name/path/kind indexes",
            "task_intent": "deterministic task terms plus lexical/structural score",
            "graph_proximity": "query-plan causal prefetch; not a semantic score",
            "precedent_ranking": "KnowledgeProjection lexical fallback",
            "context_budget": "bounded candidate, byte and selected-token budgets",
            "bm25": "not implemented or claimed by this revision",
        },
        "model": {
            "kind": "deterministic_contract_fixture",
            "production": False,
            "learned": False,
            "identity": identity.record(),
            "cpu_threads_requested": 1,
            "peak_rss_delta_kib": rss_delta,
            "resource_limits": {
                "max_p95_latency_ms": MAX_MODEL_P95_LATENCY_MS,
                "max_rss_delta_kib": MAX_MODEL_RSS_DELTA_KIB,
            },
        },
        "summary": summaries,
        "deltas": {
        "recall_at_3": model_summary["recall_at_3"]
            - baseline_summary["recall_at_3"],
            "recall_at_1": recall_at_1_delta,
            "precision_at_3": model_summary["precision_at_3"]
            - baseline_summary["precision_at_3"],
            "mrr": quality_delta,
            "ndcg_at_3": model_summary["ndcg_at_3"]
            - baseline_summary["ndcg_at_3"],
            "completion_quality": model_summary["completion_quality"]
            - baseline_summary["completion_quality"],
            "p95_latency_ms": model_summary["latency_ms"]["p95"]
            - baseline_summary["latency_ms"]["p95"],
            "peak_rss_kib": rss_delta,
        },
        "promotion_gate": promotion_gate,
        "limitations": [
            "The assisted lane is a deterministic fixture, not a learned or downloadable model.",
            "Mapper-shaped handles are fixture evidence; integrated Mapper generation and artifact digest were unavailable locally.",
            "Remote provider tokens and total cost are null because local inference exposes neither.",
            "Task completion quality is candidate coverage under the declared context budget, not a green work-item result.",
        ],
        "evidence_bindings": evidence,
        "raw_runs": rows,
    }
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--json-out", type=Path, default=Path("bench/results/optional_model_517.json")
    )
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    args = parser.parse_args()
    receipt = run(args.dataset, repetitions=args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
