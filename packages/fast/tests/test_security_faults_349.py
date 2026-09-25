from benchmarks.bench_security_faults_349 import run


def test_issue349_fault_matrix_fails_closed_with_explicit_reasons() -> None:
    receipt = run()
    assert receipt["schema"] == "simplicio.fast.security-fault-receipt/v1"
    assert receipt["status"] == "pass"
    assert receipt["summary"] == {"failed": 0, "passed": 8, "total": 8}
    assert all(row["passed"] for row in receipt["cases"])
    assert receipt["cases"][0]["observed"] == "accepted"
    assert receipt["cases"][6]["observed"] == "empty_result"


def test_issue349_fault_receipt_keeps_external_gates_explicit() -> None:
    receipt = run()
    assert receipt["residuals"] == [
        "installed_consumer_e2e",
        "rust_parity",
        "resource_benchmark",
        "rollout_receipt",
    ]
