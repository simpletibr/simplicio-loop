from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "issue_419_fast_hot_path_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("issue_419_fast_hot_path_benchmark", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_issue_419_benchmark_requires_ten_repetitions():
    with pytest.raises(ValueError, match="at least 10"):
        _module().run_benchmark(repeats=9)


def test_issue_419_fast_payload_comes_from_official_producer(tmp_path):
    module = _module()
    fast = pytest.importorskip("simplicio_fast.binary_changeset")

    payload = module._fast_payload(1, tmp_path, fast, "test")
    decoded = fast.decode_binary(payload)

    assert decoded.repository == str(tmp_path.resolve())
    assert decoded.operations[0].op == "create"
    assert decoded.operations[0].after_sha256


def test_issue_419_rust_lane_is_unavailable_without_explicit_native_binary(monkeypatch):
    module = _module()
    monkeypatch.delenv("SIMPLICIO_FAST_NATIVE", raising=False)

    reason = module._fast_lane_unavailable("rust", object())

    assert reason == "SIMPLICIO_FAST_NATIVE is not configured"


def test_issue_419_benchmark_stats_keep_worktree_sample_count():
    module = _module()

    row = module._stats([1.0, 2.0, 3.0], repeats=3, worktrees=1)
    metrics = module._sum_metrics([{"subprocesses": 1}, {"subprocesses": 2}])

    assert row["status"] == "PASS"
    assert row["samples"] == 3
    assert row["worktrees"] == 1
    assert metrics["subprocesses"] == 3
