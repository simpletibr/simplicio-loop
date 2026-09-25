from __future__ import annotations

from pathlib import Path

from benchmarks.bench_rust_query_239 import _corpus, _percentile


def test_rust_query_benchmark_helpers_are_bounded_and_deterministic(tmp_path: Path) -> None:
    root, term = _corpus(tmp_path, 10)
    assert term == "value_0"
    assert len(list(root.glob("*.py"))) == 4
    assert _percentile([1.0, 2.0, 3.0], 0.95) == 2.9
