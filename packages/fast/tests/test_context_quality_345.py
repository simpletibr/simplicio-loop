from benchmarks.bench_context_quality_345 import run


def test_context_quality_corpus_is_versioned_and_preserves_recall() -> None:
    receipt = run()
    assert receipt["status"] == "pass"
    assert receipt["dataset"]["schema"] == "simplicio.fast.context-quality-dataset/v1"
    assert receipt["dataset"]["case_count"] == 2
    assert receipt["aggregate"]["compiler_recall_not_below_manual"] is True
    assert receipt["aggregate"]["recall"] == 1.0
    assert receipt["aggregate"]["instructions"] is False
    assert receipt["aggregate"]["untrusted_selected"] is False
    assert receipt["aggregate"]["duplicate_handles"] == 0
    assert receipt["authority"] == "facts_only"


def test_context_quality_has_exact_and_estimated_tokenizer_receipts() -> None:
    receipt = run()
    for scenario in receipt["scenarios"]:
        assert scenario["exact"]["tokenizer"]["mode"] == "exact"
        assert scenario["fallback"]["tokenizer"]["mode"] == "estimated"
        assert scenario["fallback"]["tokenizer"]["reason"] == "provider_tokenizer_unavailable"
        assert scenario["exact"]["packet_digest"].startswith("sha256:")
