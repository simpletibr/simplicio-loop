"""Frozen corpus quality receipt for issue #344."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import time
from typing import Any

from simplicio_fast.knowledge_projection import KnowledgeFact, KnowledgeProjection, _digest


SCHEMA = "simplicio.fast.knowledge-quality-receipt/v1"
DEFAULT_CORPUS = Path(__file__).parents[1] / "fixtures" / "knowledge" / "v1" / "issue344-quality-corpus.json"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _ndcg(expected: list[str], actual: list[str], k: int) -> float:
    expected_rank = {handle: len(expected) - index for index, handle in enumerate(expected)}
    dcg = sum(expected_rank.get(handle, 0) / math.log2(index + 2) for index, handle in enumerate(actual[:k]))
    ideal = sum(score / math.log2(index + 2) for index, score in enumerate(sorted(expected_rank.values(), reverse=True)[:k]))
    return dcg / ideal if ideal else 1.0


def _fact(raw: dict[str, Any]) -> KnowledgeFact:
    text = raw["text"]
    digest = _digest(text)
    supplied = raw.get("digest", digest)
    if supplied != digest:
        raise ValueError(f"fact_digest_mismatch:{raw.get('stable_handle')}")
    return KnowledgeFact(
        raw["source_type"], raw["producer"], raw["stable_handle"], raw["version"],
        tuple(raw["provenance"]), raw["trust"], digest, text, raw["repository"],
        raw["scope"], raw.get("valid_from"), raw.get("valid_until"), raw.get("state", "active"),
        tuple(raw.get("applicability", ())),
    )


def run(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, Any]:
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    if raw.get("schema") != "simplicio.fast.knowledge-quality-corpus/v1":
        raise ValueError("corpus_schema_invalid")
    facts = tuple(_fact(item) for item in raw["facts"])
    handles = [fact.stable_handle for fact in facts]
    if len(handles) != len(set(handles)) or not raw["queries"]:
        raise ValueError("corpus_identity_invalid")
    projection = KnowledgeProjection(raw["repository"], raw["scope"], raw["generation"])
    projection.apply_delta(facts)
    k = raw["quality_gates"]["k"]
    query_rows: list[dict[str, Any]] = []
    for query in raw["queries"]:
        started = time.perf_counter()
        result = projection.query(query["task"], max_results=k)
        elapsed_ms = (time.perf_counter() - started) * 1000
        actual = result["handles"]
        expected = query["expected"]
        relevant = len(set(actual[:k]).intersection(expected))
        query_rows.append({
            "id": query["id"],
            "expected": expected,
            "actual": actual,
            "recall_at_k": relevant / len(expected),
            "precision_at_k": relevant / k,
            "ndcg_at_k": _ndcg(expected, actual, k),
            "latency_ms": elapsed_ms,
            "ranking": [item["explain"]["ranking"] for item in result["results"]],
        })
    averages = {
        metric: statistics.mean(row[metric] for row in query_rows)
        for metric in ("recall_at_k", "precision_at_k", "ndcg_at_k")
    }
    gates = raw["quality_gates"]
    checks = {
        "recall_at_k": averages["recall_at_k"] >= gates["min_recall_at_k"],
        "precision_at_k": averages["precision_at_k"] >= gates["min_precision_at_k"],
        "ndcg_at_k": averages["ndcg_at_k"] >= gates["min_ndcg_at_k"],
    }
    return {
        "schema": SCHEMA,
        "status": "pass" if all(checks.values()) else "fail",
        "corpus": {
            "id": raw["corpus_id"],
            "sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "facts": len(facts),
            "queries": len(query_rows),
            "provenance": raw["provenance"],
        },
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "config": {"k": k, "gates": {key: gates[key] for key in sorted(gates) if key != "k"}},
        "metrics": {**averages, "checks": checks, "latency_ms_p50": statistics.median(row["latency_ms"] for row in query_rows)},
        "queries": query_rows,
        "receipt_sha256": hashlib.sha256(_canonical({"corpus": raw["corpus_id"], "queries": query_rows, "metrics": averages})).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.corpus)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
