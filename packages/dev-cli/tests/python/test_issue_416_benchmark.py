import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "issue_416_transaction_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("issue_416_transaction_benchmark", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_issue_416_benchmark_requires_ten_repetitions():
    with pytest.raises(ValueError, match="at least 10"):
        _module().run_benchmark(repeats=9)


@pytest.mark.timeout(300)
def test_issue_416_benchmark_reports_real_direct_and_transaction_lanes():
    report = _module().run_benchmark(repeats=10)
    assert report["schema"] == "simplicio.dev-cli.issue-416-transaction-benchmark/v1"
    assert report["sizes"] == [1, 20, 200]
    measured = [row for row in report["rows"] if row["status"] == "PASS"]
    assert len(measured) == 9
    assert {row["lane"] for row in measured} == {
        "direct_mechanical",
        "python_transaction",
        "fast_python_apply",
    }
    assert all(row["repeats"] == 10 and row["p50_ms"] > 0 and row["p95_ms"] > 0 for row in measured)
    unavailable = [row for row in report["rows"] if row["status"] == "UNAVAILABLE"]
    assert len(unavailable) == 3
    assert {row["lane"] for row in unavailable} == {"fast_rust_apply"}
