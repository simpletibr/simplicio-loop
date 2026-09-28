"""Issue #1364: mapper wait ceiling and a held receipt that names the missing check."""
from __future__ import annotations

import simplicio_loop.runner as runner
from simplicio_loop.loop_execution_receipt import _held_reason


def test_mapper_wait_defaults_to_the_index_ceiling(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", raising=False)
    assert runner._mapper_timeout_seconds() == 300


def test_held_receipt_names_unverified_scenarios():
    state = {
        "tasks": [
            {"scenarios": [
                {"id": "SCN1", "title": "phone is stable", "verified": False},
                {"id": "SCN2", "title": "cache is metered", "verified": True},
            ]},
        ],
    }
    reason = _held_reason("held", state)
    assert "cannot publish a VERIFIED v1 receipt" in reason
    assert "phone is stable" in reason
    assert "cache is metered" not in reason
