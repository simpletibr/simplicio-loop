from benchmarks.bench_delivery_240_100k import FILES, SYMBOLS, WARM_P95_LIMIT_MS


def test_issue_240_100k_benchmark_contract_is_explicit_and_fail_closed() -> None:
    assert SYMBOLS == 100_000
    assert FILES == 100
    assert WARM_P95_LIMIT_MS == 25.0
