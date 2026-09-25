from __future__ import annotations

from benchmarks.bench_hot_path_497 import run
from simplicio_fast.capability_ranking import CapabilityCandidate, rank_capabilities


def test_capability_cache_is_precomputed_without_changing_ranking() -> None:
    candidate = CapabilityCandidate(
        "worker:cached",
        "worker",
        "1",
        ["query", "context", "query"],
        policy_eligible=True,
    )
    assert candidate._capability_set == frozenset({"query", "context"})
    result = rank_capabilities([candidate], ("context", "query"))
    assert result["required_capabilities"] == ["context", "query"]
    assert result["candidates"][0]["matched_capabilities"] == ["context", "query"]
    assert result["candidates"][0]["missing_capabilities"] == []


def test_hot_path_benchmark_reports_deterministic_semantics_and_metrics() -> None:
    receipt = run(scales=(1, 16), repetitions=5)
    assert receipt["status"] == "pass"
    assert receipt["optimization"]["portable"] is True
    assert receipt["optimization"]["isa_dispatch"] == "none"
    assert receipt["environment"]["metric_reasons"]["copied_bytes"] == "not_collected"
    assert set(receipt["scales"]) == {"1", "16"}
    for row in receipt["scales"].values():
        kernel = row["kernel"]
        assert kernel["semantics_equal"] is True
        assert kernel["baseline_uncached"]["sample_digest"]
        assert kernel["optimized_cached"]["sample_digest"]
        assert row["ranking"]["result_digest"]
