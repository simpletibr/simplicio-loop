from __future__ import annotations

from pathlib import Path

from benchmarks.bench_rust_query_239 import _corpus


def test_relation_corpus_emits_high_cardinality_edges(tmp_path: Path) -> None:
    root, term = _corpus(tmp_path, 20, with_relations=True)
    assert term == "value_0"
    assert len(list(root.glob("*.py"))) == 5
    assert "value_0()" in next(root.glob("*.py")).read_text(encoding="utf-8")
