"""Regression coverage for the PlanDAG conformance benchmark."""

from __future__ import annotations

import pytest

from bench.plan_contract_benchmark import run


def test_benchmark_reports_real_positive_measurements() -> None:
    result = run(5)

    assert result["iterations"] == 5
    assert result["nodes"] == 20
    assert result["mean_ms"] > 0
    assert result["p95_ms"] > 0
    assert result["operations_per_second"] > 0


def test_benchmark_rejects_empty_sample() -> None:
    with pytest.raises(ValueError, match="iterations"):
        run(0)
