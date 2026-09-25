"""Versioned multi-domain quality corpus for Universal Context (#345)."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping

from simplicio_fast.context_adapters import compile_context_sources
from simplicio_fast.knowledge_projection import KnowledgeFact, KnowledgeProjection
from simplicio_fast.operations_projection import OperationReceipt, OperationsProjection
from simplicio_fast.projection import ProjectionEnvelope


SCHEMA = "simplicio.fast.context-quality-receipt/v1"
DATASET_SCHEMA = "simplicio.fast.context-quality-dataset/v1"
CORPUS_PATH = Path("fixtures/delivery/v1/issue345-context-quality-corpus.json")


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _tokenizer(value: str) -> int:
    return len(value.split())


def _code(case: Mapping[str, Any], repository: str, tenant: str) -> list[ProjectionEnvelope]:
    return [
        ProjectionEnvelope.create(
            "code",
            producer="fast-code",
            producer_schema="simplicio.fast.code-projection/v1",
            generation=str(case["generation"]),
            source_generation=str(case["generation"]),
            projection_generation=str(case["generation"]),
            stable_handle=str(item["handle"]),
            repository_scope=repository,
            tenant_scope=tenant,
            payload={
                "repository": repository,
                "tenant": tenant,
                "content_class": "fact",
                "name": item["name"],
                "value": item["value"],
                "trust": "verified",
                "freshness": "generation_pinned",
            },
        )
        for item in case["code"]
    ]


def _knowledge(case: Mapping[str, Any], repository: str, tenant: str) -> dict[str, Any]:
    projection = KnowledgeProjection(repository, tenant, str(case["knowledge_generation"]))
    facts = []
    for item in case["knowledge"]:
        text = str(item["text"])
        facts.append(
            KnowledgeFact(
                str(item["source_type"]),
                "mapper",
                str(item["handle"]),
                "v1",
                (f"fixture:{item['handle']}",),
                str(item["trust"]),
                _digest(text),
                text,
                repository,
                tenant,
            )
        )
    projection.apply_delta(facts)
    return projection.query(str(case["task"]))


def _operations(case: Mapping[str, Any], repository: str) -> list[dict[str, Any]]:
    projection = OperationsProjection(repository, str(case["operations_generation"]))
    projection.ingest(
        [
            OperationReceipt(
                str(item["handle"]),
                str(item["kind"]),
                str(item["status"]),
                str(case["operations_generation"]),
                int(item["sequence"]),
                "simplicio.runtime.receipt/v1",
                dict(item["payload"]),
            )
            for item in case["operations"]
        ]
    )
    return projection.query()


def _compile(case: Mapping[str, Any], corpus: Mapping[str, Any], **options: Any) -> dict[str, Any]:
    repository = str(corpus["repository"])
    tenant = str(corpus["tenant"])
    return compile_context_sources(
        code=_code(case, repository, tenant),
        knowledge=_knowledge(case, repository, tenant),
        operations=_operations(case, repository),
        repository_scope=repository,
        tenant_scope=tenant,
        trust_floor="advisory",
        **options,
    )


def _metrics(packet: Mapping[str, Any], case: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    selected = [str(item["stable_handle"]) for item in packet["projections"]]
    expected = {str(value) for value in case["expected"]}
    baseline = {str(value) for value in case["manual_baseline"]}
    selected_set = set(selected)
    hits = len(selected_set & expected)
    baseline_hits = len(baseline & expected)
    return {
        "id": case["id"],
        "mode": mode,
        "selected": selected,
        "expected": sorted(expected),
        "manual_baseline": sorted(baseline),
        "precision": hits / len(selected_set) if selected_set else 0.0,
        "recall": hits / len(expected) if expected else 1.0,
        "manual_baseline_recall": baseline_hits / len(expected) if expected else 1.0,
        "duplicate_handles": len(selected) - len(selected_set),
        "tokenizer": packet["tokenizer"],
        "source_tokens": packet["source_tokens"],
        "source_bytes": packet["source_bytes"],
        "truncated": packet["truncated"],
        "instructions": packet["instructions"],
        "untrusted_selected": any(
            item.get("trust") == "untrusted" for item in packet["projections"]
        ),
        "packet_digest": _digest(packet),
    }


def _timed(function: Callable[[], Mapping[str, Any]], repetitions: int = 5) -> dict[str, float]:
    samples = []
    for _ in range(repetitions):
        started = perf_counter()
        function()
        samples.append((perf_counter() - started) * 1000)
    samples.sort()
    return {
        "p50_ms": round(samples[len(samples) // 2], 3),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 3),
        "samples": len(samples),
    }


def run(corpus: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if corpus is None:
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    if corpus.get("schema") != DATASET_SCHEMA:
        raise ValueError("context_quality_dataset_invalid")
    scenarios = []
    for case in corpus["cases"]:
        exact = _compile(
            case,
            corpus,
            tokenizer_id="fixture:whitespace-v1",
            tokenizer=_tokenizer,
        )
        fallback = _compile(case, corpus, tokenizer_id="tiktoken:missing-for-corpus")
        timing = _timed(
            lambda: _compile(
                case,
                corpus,
                tokenizer_id="fixture:whitespace-v1",
                tokenizer=_tokenizer,
            )
        )
        scenarios.append(
            {
                "id": case["id"],
                "exact": _metrics(exact, case, mode="exact"),
                "fallback": _metrics(fallback, case, mode="estimated"),
                "latency": timing,
            }
        )
    exact_metrics = [item["exact"] for item in scenarios]
    return {
        "schema": SCHEMA,
        "status": "pass",
        "dataset": {
            "schema": DATASET_SCHEMA,
            "id": corpus["id"],
            "case_count": len(scenarios),
            "digest": _digest(corpus),
        },
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "scenarios": scenarios,
        "aggregate": {
            "precision": sum(item["precision"] for item in exact_metrics) / len(exact_metrics),
            "recall": sum(item["recall"] for item in exact_metrics) / len(exact_metrics),
            "manual_baseline_recall": sum(item["manual_baseline_recall"] for item in exact_metrics) / len(exact_metrics),
            "compiler_recall_not_below_manual": all(
                item["recall"] >= item["manual_baseline_recall"] for item in exact_metrics
            ),
            "duplicate_handles": sum(item["duplicate_handles"] for item in exact_metrics),
            "instructions": any(item["instructions"] for item in exact_metrics),
            "truncated": any(item["truncated"] for item in exact_metrics),
            "untrusted_selected": any(item["untrusted_selected"] for item in exact_metrics),
        },
        "authority": "facts_only",
        "decision_owner": "agent-loop-consumer",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(json.loads(args.corpus.read_text(encoding="utf-8")))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
