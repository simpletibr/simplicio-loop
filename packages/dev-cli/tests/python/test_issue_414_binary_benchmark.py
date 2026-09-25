import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "issue_414_binary_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("issue_414_binary_benchmark", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_issue_414_benchmark_requires_ten_repetitions():
    with pytest.raises(ValueError, match="at least 10"):
        _module().run_benchmark(repeats=9)


def test_issue_414_benchmark_schema_has_all_sizes_and_lanes():
    report = _module().run_benchmark(repeats=10)
    assert report["schema"] == "simplicio.dev-cli.issue-414-binary-benchmark/v1"
    assert report["sizes"] == [1, 20, 200]
    assert {(row["size"], row["lane"]) for row in report["rows"]} == {
        (size, lane)
        for size in (1, 20, 200)
        for lane in ("json_legacy_adapter", "binary_fast_adapter", "binary_fast_rust_adapter")
    }
