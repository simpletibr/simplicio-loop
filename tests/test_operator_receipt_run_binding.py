"""Operator receipts written into a run dir must bind that run."""

from __future__ import annotations

import pytest

from simplicio_loop import runner


def test_operator_receipt_without_run_id_is_bound_to_its_run_dir():
    assert runner._receipt_run_id({}, "run-abc") == "run-abc"
    assert runner._receipt_run_id({"run_id": ""}, "run-abc") == "run-abc"
    assert runner._receipt_run_id({"run_id": "run-abc"}, "run-abc") == "run-abc"


def test_operator_receipt_with_foreign_run_id_is_rejected():
    with pytest.raises(RuntimeError, match="not bound to the current run"):
        runner._require_matching_run_id({"run_id": "run-other"}, "run-abc", "operator")
