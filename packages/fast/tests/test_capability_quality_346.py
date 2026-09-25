from benchmarks.bench_capability_quality_346 import run


def test_capability_quality_receipt_is_deterministic_and_advisory() -> None:
    first = run()
    second = run()

    assert first == second
    assert first["dataset"]["schema"] == "simplicio.fast.capability-quality-dataset/v1"
    assert first["dataset"]["case_count"] == 2
    assert first["aggregate"]["authority"] == "advisory_only"
    assert first["aggregate"]["hard_incompatible_eligible"] is False
    assert first["aggregate"]["precision_at_k"] == 1.0
    assert first["aggregate"]["recall_at_k"] == 1.0
    assert first["aggregate"]["ndcg_at_k"] == 1.0
    assert {"estimated", "measured", "simulated", "unknown"} <= set(
        first["scenarios"][0]["metric_classes"]
        + first["scenarios"][1]["metric_classes"]
    )
