"""Issue #198: quality-first Q0/Q1/Q2 benchmark contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import random
import subprocess

import pytest

import simplicio_fast.quant_benchmark as quant_benchmark
from simplicio_fast.quant_benchmark import (
    BENCH_SCHEMA,
    BENCHMARK_SCHEMA,
    DATASET_SCHEMA,
    MANIFEST_SCHEMA,
    QuantBenchmarkError,
    QuantLaneIndex,
    build_fixture,
    concurrency_receipt,
    digest,
    quality_metrics,
    repository_corpus_receipt,
    run_benchmark,
    run_quant_benchmark,
)
from simplicio_fast.turboquant import exact_rerank
from simplicio_fast.vector_index import TurboQuantIndex


def _index(tmp_path: Path, lane: str = "Q2b") -> tuple:
    dataset = build_fixture(64, dimension=8)
    config_hash = digest({"candidate_k": 20, "result_k": 10})
    index = QuantLaneIndex.build(
        dataset.records,
        lane=lane,
        generation="generation-one",
        corpus_hash=dataset.corpus_hash,
        embedding_hash=dataset.embedding_hash,
        config_hash=config_hash,
        candidate_k=20,
        result_k=10,
        seed=dataset.seed,
    )
    path = index.persist_atomic(tmp_path / f"{lane}.sfastq")
    return dataset, config_hash, index, path


def test_pr217_compact_api_remains_compatible():
    vectors = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.7, 0.7, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]
    queries = [[0.9, 0.1, 0.0, 0.0], [0.1, 0.9, 0.0, 0.0]]
    first = run_quant_benchmark(vectors, queries, top_k=2)
    second = run_quant_benchmark(vectors, queries, top_k=2)
    assert first["schema"] == BENCH_SCHEMA == BENCHMARK_SCHEMA
    assert set(first["lanes"]) == {
        "Q0_full",
        "Q1_8bit",
        "Q2_turboquant_4bit",
    }
    assert first["lanes"] == second["lanes"]
    assert first["cpu_ms"] is None
    assert first["cpu_ms_null_reason"] == "NOT_MEASURED"
    assert first["rss_bytes"] is None
    assert first["deprecated"] is True
    assert first["replacement"] == "run_benchmark"


def test_frozen_dataset_hashes_every_input_and_embedding_contract():
    first = build_fixture(257, dimension=12, seed=198)
    second = build_fixture(257, dimension=12, seed=198)
    changed = build_fixture(257, dimension=12, seed=199)
    assert first == second
    assert first.dataset_hash != changed.dataset_hash
    receipt = first.receipt()
    assert receipt["schema"] == DATASET_SCHEMA
    assert receipt["corpus_hash"] == first.corpus_hash
    assert receipt["query_hash"] == first.query_hash
    assert receipt["judgments_hash"] == first.judgments_hash
    assert receipt["embedding"]["sha256"] == first.embedding_hash
    assert receipt["embedding"]["normalization"] == "l2"
    assert all(
        math.isclose(sum(value * value for value in vector), 1.0, rel_tol=1e-12)
        for _, vector in first.records
    )


@pytest.mark.parametrize("lane", ("Q0", "Q1", "Q2a", "Q2b"))
def test_every_lane_has_content_addressed_manifest_and_real_file(tmp_path, lane):
    dataset, config_hash, index, path = _index(tmp_path, lane)
    receipt = index.manifest.receipt()
    assert receipt["schema"] == MANIFEST_SCHEMA
    assert receipt["lane"] == lane
    assert receipt["index_bytes"] == path.stat().st_size
    assert (
        receipt["index_hash"]
        == __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    )
    assert (
        index.verify_file(
            path,
            generation="generation-one",
            corpus_hash=dataset.corpus_hash,
            embedding_hash=dataset.embedding_hash,
            config_hash=config_hash,
        )["index_bytes"]
        > 0
    )


def test_q2_without_and_with_integral_rerank_are_distinct_and_attributed(tmp_path):
    dataset, _, q2a, _ = _index(tmp_path, "Q2a")
    _, _, q2b, _ = _index(tmp_path, "Q2b")
    query = dataset.queries[0]
    approximate, approximate_timing = q2a.query(query.vector)
    reranked, rerank_timing = q2b.query(query.vector)
    assert approximate_timing["rerank_ms"] == 0
    assert rerank_timing["rerank_ms"] > 0
    assert set(reranked).issubset(
        {
            item.canonical_id
            for item in exact_rerank(
                query.vector,
                dataset.records,
                metric="cosine",
                top_k=len(dataset.records),
            )
        }
    )
    assert len(approximate) == len(reranked) == 10


def test_q0_and_q2b_differential_match_existing_production_paths(tmp_path):
    dataset, _, q0, _ = _index(tmp_path, "Q0")
    _, _, q2b, _ = _index(tmp_path, "Q2b")
    production = TurboQuantIndex.build(
        dataset.records,
        seed=dataset.seed,
        metric="cosine",
        generation="generation-one",
    )
    for query in dataset.queries[:4]:
        expected = tuple(
            item.canonical_id
            for item in exact_rerank(
                query.vector,
                dataset.records,
                metric="cosine",
                top_k=10,
            )
        )
        q0_ids, _ = q0.query(query.vector)
        q2b_ids, _ = q2b.query(query.vector)
        receipt = production.query(query.vector, requested_k=10, candidate_k=20)
        production_ids = tuple(item["canonical_id"] for item in receipt["results"])
        assert q0_ids == expected
        assert q2b_ids == production_ids


def test_quality_metrics_cover_all_required_cutoffs_ndcg_mrr_and_abstention():
    relevant = ("a", "b", "c")
    observed = quality_metrics(relevant, ("a", "x", "b"))
    assert observed["recall_at_1"] == 1.0
    assert observed["precision_at_5"] == 2 / 5
    assert observed["recall_at_10"] == 2 / 3
    assert 0 < observed["ndcg_at_10"] < 1
    assert observed["mrr"] == 1.0
    assert observed["abstention_rate"] == 0.0
    empty = quality_metrics(relevant, ())
    assert empty["abstention_rate"] == 1.0
    assert empty["mrr"] == 0.0
    with pytest.raises(ValueError, match="must not be empty"):
        quality_metrics((), ("a",))


def test_stale_corrupt_cross_generation_and_backend_fail_with_stable_codes(
    tmp_path,
):
    dataset, config_hash, index, path = _index(tmp_path)
    cases = (
        (
            {
                "generation": "other",
                "corpus_hash": dataset.corpus_hash,
                "embedding_hash": dataset.embedding_hash,
                "config_hash": config_hash,
            },
            "INDEX_CROSS_GENERATION",
        ),
        (
            {
                "generation": "generation-one",
                "corpus_hash": "1" * 64,
                "embedding_hash": dataset.embedding_hash,
                "config_hash": config_hash,
            },
            "INDEX_STALE",
        ),
        (
            {
                "generation": "generation-one",
                "corpus_hash": dataset.corpus_hash,
                "embedding_hash": dataset.embedding_hash,
                "config_hash": config_hash,
                "backend": "rust",
            },
            "BACKEND_INCOMPATIBLE",
        ),
    )
    for kwargs, reason in cases:
        with pytest.raises(QuantBenchmarkError) as captured:
            index.verify_file(path, **kwargs)
        assert captured.value.reason_code == reason
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(QuantBenchmarkError) as captured:
        index.verify_file(
            path,
            generation="generation-one",
            corpus_hash=dataset.corpus_hash,
            embedding_hash=dataset.embedding_hash,
            config_hash=config_hash,
        )
    assert captured.value.reason_code == "INDEX_CORRUPT"


def test_fault_before_atomic_swap_preserves_previous_generation(tmp_path):
    dataset, _, index, path = _index(tmp_path)
    previous = path.read_bytes()

    def fail(stage: str, temporary: Path) -> None:
        assert stage == "before_swap"
        assert temporary.is_file()
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        index.persist_atomic(path, fault=fail)
    assert path.read_bytes() == previous
    assert not tuple(tmp_path.glob("*.tmp"))
    assert dataset.records


def test_faults_during_build_and_query_fail_without_publishing(monkeypatch, tmp_path):
    import simplicio_fast.quant_benchmark as module

    dataset = build_fixture(32, dimension=8)
    config_hash = digest({"fault": True})
    calls = 0
    original_quantize = module.turboquant_quantize

    def fail_build(vector, seed):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("build fault")
        return original_quantize(vector, seed)

    monkeypatch.setattr(module, "turboquant_quantize", fail_build)
    with pytest.raises(RuntimeError, match="build fault"):
        QuantLaneIndex.build(
            dataset.records,
            lane="Q2b",
            generation="g",
            corpus_hash=dataset.corpus_hash,
            embedding_hash=dataset.embedding_hash,
            config_hash=config_hash,
            candidate_k=20,
            result_k=10,
            seed=dataset.seed,
        )
    assert not tuple(tmp_path.iterdir())
    monkeypatch.setattr(module, "turboquant_quantize", original_quantize)
    index = QuantLaneIndex.build(
        dataset.records,
        lane="Q2b",
        generation="g",
        corpus_hash=dataset.corpus_hash,
        embedding_hash=dataset.embedding_hash,
        config_hash=config_hash,
        candidate_k=20,
        result_k=10,
        seed=dataset.seed,
    )

    def fail_query(*args, **kwargs):
        raise RuntimeError("query fault")

    monkeypatch.setattr(module, "approximate_candidates", fail_query)
    with pytest.raises(RuntimeError, match="query fault"):
        index.query(dataset.queries[0].vector)
    with pytest.raises(ValueError, match="dimension mismatch"):
        index.query((1.0,))


def test_property_determinism_bounds_duplicates_nan_and_degenerate_vectors(
    tmp_path,
):
    generator = random.Random(198)
    for seed in range(25):
        records = []
        for index in range(17):
            vector = tuple(generator.uniform(-10, 10) for _ in range(7))
            records.append((f"{seed}-{index}", vector))
        corpus_hash = digest(records)
        config_hash = digest({"seed": seed})
        first = QuantLaneIndex.build(
            records,
            lane="Q2b",
            generation="g",
            corpus_hash=corpus_hash,
            embedding_hash=corpus_hash,
            config_hash=config_hash,
            candidate_k=10,
            result_k=5,
            seed=seed,
        )
        second = QuantLaneIndex.build(
            records,
            lane="Q2b",
            generation="g",
            corpus_hash=corpus_hash,
            embedding_hash=corpus_hash,
            config_hash=config_hash,
            candidate_k=10,
            result_k=5,
            seed=seed,
        )
        assert first.serialized_payload() == second.serialized_payload()
        assert first.query(records[0][1])[0] == second.query(records[0][1])[0]
        assert all(
            -8 <= code <= 7 for entry in first._entries for code in entry.encoded.codes
        )
    common = {
        "lane": "Q0",
        "generation": "g",
        "corpus_hash": "1" * 64,
        "embedding_hash": "2" * 64,
        "config_hash": "3" * 64,
        "candidate_k": 2,
        "result_k": 1,
        "seed": 1,
    }
    with pytest.raises(ValueError, match="unique"):
        QuantLaneIndex.build((("x", (1.0,)), ("x", (2.0,))), **common)
    with pytest.raises(ValueError, match="finite"):
        QuantLaneIndex.build((("x", (float("nan"),)),), **common)
    with pytest.raises(ValueError, match="finite"):
        QuantLaneIndex.build((("x", (float("inf"),)),), **common)
    zero = QuantLaneIndex.build((("x", (0.0, 0.0)),), **common)
    assert zero.query((0.0, 0.0))[0] == ("x",)
    with pytest.raises(ValueError, match="at least one"):
        QuantLaneIndex.build((), **common)


@pytest.mark.parametrize("slots", (1, 5, 20))
def test_concurrent_slots_are_deterministic_and_isolated(tmp_path, slots):
    dataset, _, index, _ = _index(tmp_path)
    first = concurrency_receipt(index, dataset.queries, slots=slots)
    second = concurrency_receipt(index, dataset.queries, slots=slots)
    assert first["slots"] == slots
    assert first["isolated_calls"] == slots
    assert first["result_digest"] == second["result_digest"]


def test_direct_parallel_queries_have_identical_golden_results(tmp_path):
    dataset, _, index, _ = _index(tmp_path)
    query = dataset.queries[0].vector
    with ThreadPoolExecutor(max_workers=20) as executor:
        outputs = tuple(executor.map(lambda _: index.query(query)[0], range(40)))
    assert len(set(outputs)) == 1


def test_real_repository_corpus_is_content_addressed_without_embedding():
    receipt = repository_corpus_receipt(Path(__file__).parents[1])
    assert receipt["kind"] == "real-repository-corpus"
    assert receipt["source"] == "git-head-tree"
    assert receipt["tracked_only"] is True
    assert len(receipt["source_commit"]) == 40
    assert len(receipt["source_tree"]) == 40
    assert receipt["files"] > 0
    assert len(receipt["corpus_hash"]) == 64
    assert receipt["embedded"] is False
    assert receipt["embedded_null_reason"]


def test_real_corpus_is_identical_in_clean_clone_and_excludes_transients(
    tmp_path,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".gitignore").write_text(
        ".pytest_cache/\n*.scratch.json\n",
        encoding="utf-8",
    )
    (source / "README.md").write_text("tracked\n", encoding="utf-8")
    tracked = source / "src" / "example.py"
    tracked.parent.mkdir()
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", source], check=True)
    subprocess.run(["git", "-C", source, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            source,
            "-c",
            "user.name=Quant Fixture",
            "-c",
            "user.email=quant@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    cache = source / ".pytest_cache" / "README.md"
    cache.parent.mkdir()
    cache.write_text("ignored cache\n", encoding="utf-8")
    (source / "untracked.json").write_text("{}", encoding="utf-8")
    (source / "ignored.scratch.json").write_text("{}", encoding="utf-8")

    original = repository_corpus_receipt(source)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", source, clone], check=True)
    cloned = repository_corpus_receipt(clone)

    assert original == cloned
    assert set(original["source_hashes"]) == {"README.md", "src/example.py"}
    assert all(
        ".pytest_cache" not in path and "untracked" not in path
        for path in original["source_hashes"]
    )


def test_small_real_benchmark_has_ten_raw_repetitions_and_separate_classes(
    tmp_path,
):
    receipt = run_benchmark(
        Path(__file__).parents[1],
        sizes=(64, 100_000, 1_000_000),
        repetitions=10,
        max_vectors=64,
        dimension=8,
        candidate_k=20,
        result_k=10,
    )
    assert receipt["schema"] == BENCHMARK_SCHEMA
    assert receipt["classification"] == "MEASURED"
    assert receipt["simulated"]["classification"] == "SIMULATED"
    assert receipt["simulated"]["values"] is None
    assert receipt["parity"]["rust"] is None
    assert receipt["parity"]["rust_compilation_attempted"] is False
    assert len(receipt["unavailable_sizes"]) == 2
    assert {item["classification"] for item in receipt["unavailable_sizes"]} == {
        "BLOCKED"
    }
    assert {item["status"] for item in receipt["unavailable_sizes"]} == {"unavailable"}
    assert all(item["value"] is None for item in receipt["unavailable_sizes"])
    assert {item["reason"] for item in receipt["unavailable_sizes"]} == {
        "CAPACITY_LIMIT_CONFIGURED"
    }
    case = receipt["measured"][0]
    assert set(case["lanes"]) == {"Q0", "Q1", "Q2a", "Q2b"}
    assert case["lanes"]["Q2a"]["rerank_ms"]["p50"] == 0
    assert case["lanes"]["Q2b"]["rerank_ms"]["p50"] > 0
    for lane in case["lanes"].values():
        assert lane["classification"] == "MEASURED"
        assert len(lane["raw_samples"]) == 10
        assert lane["python_deterministic"] is True
        assert lane["rust_parity"] is None
        assert lane["rust_parity_null_reason"]
        assert lane["query_ms"]["p99"] >= lane["query_ms"]["p95"]
        assert lane["manifest"]["corpus_hash"] == case["dataset"]["corpus_hash"]
        json.dumps(lane)
    gate = case["promotion_gate"]
    assert gate["decision"] in {"PROMOTE", "REJECT"}
    assert set(gate["checks"]) >= {
        "quality_recall",
        "quality_ndcg",
        "memory_policy",
        "latency",
        "rerank_present",
        "measured_only",
    }


def test_memory_gate_is_end_to_end_unless_shared_store_is_explicit():
    q0 = {
        "classification": "MEASURED",
        "quality": {"recall_at_10": 1.0, "ndcg_at_10": 1.0},
        "index_bytes": 100,
        "total_storage_bytes": 100,
        "promotion_memory_bytes": 100,
        "integral_store_shared": False,
        "query_ms": {"p95": 10.0},
        "rerank_ms": {"p50": 0.0},
    }
    q2b = {
        "classification": "MEASURED",
        "quality": {"recall_at_10": 1.0, "ndcg_at_10": 1.0},
        "index_bytes": 20,
        "total_storage_bytes": 120,
        "promotion_memory_bytes": 120,
        "integral_store_shared": False,
        "query_ms": {"p95": 10.0},
        "rerank_ms": {"p50": 1.0},
    }
    dedicated = quant_benchmark._promotion_gate(
        q0,
        q2b,
        max_recall_regression=0.02,
        max_ndcg_regression=0.02,
        minimum_index_reduction=0.50,
        maximum_latency_ratio=1.50,
    )
    assert dedicated["observed"]["index_reduction"] == pytest.approx(0.80)
    assert dedicated["observed"]["total_storage_reduction"] == pytest.approx(-0.20)
    assert dedicated["checks"]["memory_policy"] is False
    assert dedicated["decision"] == "REJECT"

    q2b["integral_store_shared"] = True
    q2b["promotion_memory_bytes"] = 20
    shared = quant_benchmark._promotion_gate(
        q0,
        q2b,
        max_recall_regression=0.02,
        max_ndcg_regression=0.02,
        minimum_index_reduction=0.50,
        maximum_latency_ratio=1.50,
    )
    assert shared["observed"]["storage_policy"] == "shared-integral-store"
    assert shared["checks"]["memory_policy"] is True
    assert shared["decision"] == "PROMOTE"
