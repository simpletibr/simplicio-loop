from benchmarks.bench_tokenizer_matrix_240 import PROVIDERS, TASKS, run


def test_tokenizer_matrix_is_bounded_and_explicit() -> None:
    receipt = run()
    assert receipt["schema"] == "simplicio.fast.tokenizer-matrix/v1"
    assert len(receipt["providers"]) == len(PROVIDERS)
    for provider in receipt["providers"]:
        assert provider["provider"] in PROVIDERS
        if provider["status"] == "exact":
            assert len(provider["tasks"]) == len(TASKS)
            assert all(item["tokens"] >= 0 for item in provider["tasks"])
        else:
            assert provider["reason_code"] == "provider_tokenizer_unavailable"
