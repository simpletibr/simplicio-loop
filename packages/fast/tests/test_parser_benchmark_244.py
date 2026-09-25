from benchmarks.bench_parser_244 import run


def test_parser_benchmark_reports_raw_resource_and_reuse_metrics() -> None:
    receipt = run(symbols=(200,), repetitions=10)

    assert receipt["schema"] == "simplicio.fast.parser-adapter-benchmark/v1"
    result = receipt["results"]["200"]
    for category in ("cold", "one_file", "unchanged"):
        measured = result[category]
        assert measured["repetitions"] == 10
        assert measured["wall_ms_p95"] is not None
        assert measured["wall_ms_p99"] is not None
        assert len(measured["raw"]) == 10
    assert result["cold"]["parsed_files_median"] == 2
    assert result["one_file"]["parsed_files_median"] == 1
    assert result["unchanged"]["parsed_files_median"] == 0
    assert result["unchanged"]["reused_files_median"] == 2
