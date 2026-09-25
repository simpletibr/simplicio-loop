from benchmarks.bench_issue242_hotpath import run


def test_issue242_hotpath_receipt_requires_thirty_repetitions() -> None:
    receipt = run(scales=(1_000,), repetitions=30)
    row = receipt["scales"]["1000"]
    assert receipt["status"] == "pass"
    assert row["performance_gates"]["status"] == "pass"
    assert row["unchanged"]["summary"]["repetitions"] == 30
    assert row["one_file"]["summary"]["repetitions"] == 30
    assert row["unchanged"]["summary"]["wall_ms_p95"] >= row["unchanged"]["summary"]["wall_ms_median"]
    assert row["unchanged"]["summary"]["wall_ms_p99"] >= row["unchanged"]["summary"]["wall_ms_p95"]


def test_issue242_hotpath_keeps_external_metrics_explicit() -> None:
    receipt = run(scales=(1_000,), repetitions=30)
    assert receipt["environment"]["metric_reasons"] == {"page_faults": "not_collected", "rss_kib": "not_collected"}
    assert "Linux_receipt" in receipt["residuals"]
