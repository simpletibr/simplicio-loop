"""Tests for non-blocking technical-debt behavior (#681)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import finding_router
from simplicio_loop.technical_debt import (
    build_notice,
    read_notices,
    record_notice,
)


def test_notice_is_deduplicated_and_replayed(tmp_path: Path):
    (tmp_path / "state.json").write_text(json.dumps({"phase": "executing"}), encoding="utf-8")
    first = record_notice(
        tmp_path,
        run_id="run-1",
        reason_code="fanout_serial_fallback",
        stage="dispatch",
        source="test",
        message="serial lane",
        next_action="configure worktrees",
    )
    second = record_notice(
        tmp_path,
        run_id="run-1",
        reason_code="fanout_serial_fallback",
        stage="dispatch",
        source="test",
        message="serial lane again",
        next_action="configure worktrees",
    )
    assert first["debt_id"] == second["debt_id"]
    assert second["occurrences"] == 2
    assert len(read_notices(tmp_path)) == 1
    (tmp_path / "technical-debt.json").unlink()
    replayed = read_notices(tmp_path)
    assert len(replayed) == 1 and replayed[0]["occurrences"] == 2
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["degraded"] is True
    assert state["phase"] == "executing"


def test_hard_blocker_cannot_be_downgraded():
    with pytest.raises(ValueError):
        build_notice(
            run_id="run-1",
            reason_code="source_drift",
            stage="planning",
            source="test",
            message="drift",
            next_action="replan",
        )


def test_finding_router_technical_debt_does_not_block(tmp_path: Path, monkeypatch):
    store = tmp_path / "routes.json"
    monkeypatch.setattr(finding_router, "LOCAL_STORE", store)
    result = finding_router.route_finding(
        "dispatch", "fanout-1", "medium", "runner.py", True,
        item_id="T1", classification="technical_debt",
    )
    assert result.blocking is False
    assert finding_router.completion_blocked("T1") is False
    assert finding_router.technical_debts("T1")[0]["classification"] == "technical_debt"
