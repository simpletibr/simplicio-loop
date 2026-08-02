from __future__ import annotations

import pytest

from scripts.issue_498_lock_benchmark import run_benchmark


def test_issue_498_benchmark_emits_measured_single_writer_matrix():
    report = run_benchmark(repeats=10, writer_counts=(1,))

    assert report["schema"] == "simplicio.dev-cli.issue-498-lock-benchmark/v1"
    assert report["issue"] == 498
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["status"] == "PASS"
    assert row["repeats"] == 10
    assert row["p50_ms"] > 0
    assert row["p95_ms"] >= row["p50_ms"]


def test_issue_498_benchmark_rejects_short_runs():
    with pytest.raises(ValueError, match="at least 10"):
        run_benchmark(repeats=9, writer_counts=(1,))
