from __future__ import annotations

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

