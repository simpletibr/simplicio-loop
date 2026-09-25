from benchmarks.bench_installed_sdk_348 import run


def test_issue348_installed_python_consumer_receipt_passes() -> None:
    receipt = run()
    assert receipt["schema"] == "simplicio.fast.installed-sdk-receipt/v1"
    assert receipt["status"] == "pass"
    assert all(receipt["checks"].values())
    assert len(receipt["steps"]) == 8


def test_issue348_receipt_keeps_non_python_gates_explicit() -> None:
    receipt = run()
    assert receipt["residuals"] == [
        "backpressure_cancellation",
        "cross_platform_artifacts",
        "upgrade_rollback_receipts",
    ]
