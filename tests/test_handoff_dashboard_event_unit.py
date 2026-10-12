"""A written handoff is a `handoff` dashboard event, and the budget counts continuations per task (#1608, part D)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import agent_handoff, dashboard_events, handoff_cli
from simplicio_loop.dashboard import budget

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "agent-handoff" / "v1" / "fixtures"
SCHEMA = Path(__file__).resolve().parent.parent / "contracts" / "dashboard-event" / "v1" / "schema.json"


def handoff(**changes):
    d = json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))
    d.update(changes)
    return d


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.delenv("SIMPLICIO_DASHBOARD_EVENTS", raising=False)
    return run


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def handoff_events(run):
    return [e for e in dashboard_events.read_events(run) if e["kind"] == "handoff"]


def event(seq, task, continuation, kind="handoff"):
    return {"schema": "simplicio.dashboard-event/v1", "seq": seq, "kind": kind, "task_id": task,
            "ts": "2026-10-10T10:00:%02d.000Z" % seq, "payload": {"step": "written", "continuation": continuation}}


def test_handoff_is_a_loop_kind_of_the_schema():
    enum = json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["kind"]["anyOf"][0]["enum"]
    assert "handoff" in enum
    assert "handoff" in dashboard_events.load().LOOP_KINDS


def test_writing_a_handoff_emits_one_handoff_event_for_its_task(run_dir, repo):
    doc = handoff()
    handoff_cli.store(repo, doc)
    found = handoff_events(run_dir)
    assert len(found) == 1
    assert found[0]["task_id"] == doc["task_id"]
    assert found[0]["payload"] == {"step": "written", "continuation": doc["continuation"], "basis": "MEASURED"}
    assert found[0]["refs"] == [".simplicio-loop/orchestrator/handoff/%s/%d.json" % (doc["run_id"], doc["continuation"])]


def test_a_refused_handoff_emits_no_event(run_dir, repo):
    with pytest.raises(agent_handoff.HandoffError):
        handoff_cli.store(repo, handoff(schema="simplicio.agent-handoff/v0"))
    assert handoff_events(run_dir) == []


def test_continuations_per_task_count_each_handoff_once():
    events = [event(1, "T1", 1), event(2, "T1", 2), event(3, "T1", 2), event(4, "T2", 1),
              event(5, "T2", 1, kind="lane_progress")]
    assert budget.continuations(events) == {"total": 3, "by_task": {"T1": 2, "T2": 1}}


def test_the_budget_report_carries_the_continuations(tmp_path):
    payload = budget.report(tmp_path, [event(1, "T1", 1)])
    assert payload["continuations"] == {"total": 1, "by_task": {"T1": 1}}
