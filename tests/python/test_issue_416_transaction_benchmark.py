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


def test_issue_416_fast_payload_comes_from_official_producer(tmp_path):
    module = _module()
    fast = pytest.importorskip("simplicio_fast.binary_changeset")
    module._prepare_root(tmp_path, 1)

    payload = module._fast_payload(1, tmp_path, fast)
    decoded = fast.decode_binary(payload)

    assert decoded.repository == str(tmp_path.resolve())
    assert len(decoded.operations) == 1
    assert decoded.operations[0].op == "replace-range"
    assert decoded.operations[0].before_sha256
    assert decoded.operations[0].after_sha256


def test_issue_416_rust_lane_is_unavailable_without_explicit_native_binary(monkeypatch):
    module = _module()
    monkeypatch.delenv("SIMPLICIO_FAST_NATIVE", raising=False)
    session = module.FastEngineSession()
    try:
        reason = module._fast_lane_unavailable("rust", object(), session)
    finally:
        session.close()

    assert reason == "SIMPLICIO_FAST_NATIVE is not configured"
