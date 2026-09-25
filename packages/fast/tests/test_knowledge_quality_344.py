import json
from pathlib import Path

from benchmarks.bench_knowledge_quality_344 import DEFAULT_CORPUS, run


def test_issue344_frozen_corpus_receipt_passes_quality_gates() -> None:
    receipt = run(DEFAULT_CORPUS)
    assert receipt["schema"] == "simplicio.fast.knowledge-quality-receipt/v1"
    assert receipt["status"] == "pass"
    assert receipt["metrics"]["checks"] == {"ndcg_at_k": True, "precision_at_k": True, "recall_at_k": True}
    assert receipt["metrics"]["recall_at_k"] == 1.0
    assert receipt["metrics"]["ndcg_at_k"] == 1.0
    assert all(row["ranking"] == ["lexical-fallback"] for row in receipt["queries"])


def test_issue344_corpus_is_versioned_and_has_provenance() -> None:
    raw = json.loads(Path(DEFAULT_CORPUS).read_text(encoding="utf-8"))
    assert raw["schema"] == "simplicio.fast.knowledge-quality-corpus/v1"
    assert raw["provenance"]["kind"] == "repository_fixture"
    assert len(raw["provenance"]["sources"]) >= 4
    assert len(raw["facts"]) >= 8
    assert len(raw["queries"]) >= 8
