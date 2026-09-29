import json
import pytest
from simplicio_loop.tasks_orchestrator import TasksOrchestrator

class Intake:
    def run(self, request):
        return {"run_identity": {"request": request}, "outcome": {"status": "PLANNED_NOT_EXECUTED"}}

def build(*, evidence=None, item_count=1, journal_dir=None):
    calls = []
    def dispatch(items, **kwargs):
        calls.append((items, kwargs))
        return {"workers": [{"status": "succeeded"}]}
    bridge = TasksOrchestrator(
        Intake(),
        lambda plan: [{"task_id": str(index)} for index in range(item_count)],
        lambda dispatched: {"passed": True, "evidence": evidence or [{"pr": "#1", "verification": "passed"}]},
        dispatch=dispatch, max_workers=2, retry_budget=3, journal_dir=journal_dir,
    )
    return bridge, calls

def test_action_gate_stops_before_dispatch():
    bridge, calls = build()
    result = bridge.run("all issues")
    assert (result["state"], result["reason"], calls) == ("partial", "action_gate_required", [])

def test_cancel_stops_before_dispatch():
    bridge, calls = build()
    result = bridge.run("all issues", cancel=True)
    assert result["state"] == "cancelled"
    assert calls == []


def test_cancel_persists_without_intake_availability():
    class UnavailableIntake:
        def run(self, request):
            raise RuntimeError("source unavailable")
    class Coordinator:
        def __init__(self):
            self.reasons = []
        def cancel_all(self, *, reason):
            self.reasons.append(reason)
            return ["active-worker"]
    coordinate = Coordinator()
    bridge = TasksOrchestrator(UnavailableIntake(), lambda plan: [], coordinate)
    result = bridge.run("all issues", cancel=True)
    assert result["state"] == "cancelled"
    assert result["cancelled"] == ["active-worker"]
    assert coordinate.reasons == ["cancel_requested"]

def test_authorized_pipeline_binds_dispatch_and_evidence(tmp_path):
    bridge, calls = build(journal_dir=str(tmp_path / "journals"))
    first = bridge.run("all issues", action_gate=True)
    second = bridge.run("all issues", action_gate=True)
    assert first["state"] == "completed"
    assert first == second
    assert len(calls) == 1
    assert calls[0][1]["retry_budget"] == 3
    assert calls[0][1]["journal_dir"] == str(tmp_path / "journals")
    durable = list((tmp_path / "idempotency").glob("*.json"))
    assert len(durable) == 1
    assert json.loads(durable[0].read_text(encoding="utf-8"))["state"] == "completed"


def test_dispatching_receipt_is_taken_over_after_crashed_owner_releases_lock(tmp_path):
    calls = []
    def dispatch(items, **kwargs):
        calls.append(items)
        if len(calls) == 1:
            raise RuntimeError("crash")
        return {"workers": [{"status": "succeeded"}]}
    bridge = TasksOrchestrator(
        Intake(), lambda plan: [{"task_id": "1"}],
        lambda dispatched: {"passed": True, "evidence": [{"pr": "#1", "verification": "passed"}]},
        dispatch=dispatch, journal_dir=str(tmp_path / "journals"),
    )
    with pytest.raises(RuntimeError, match="crash"):
        bridge.run("all issues", action_gate=True)
    receipt_path = next((tmp_path / "idempotency").glob("*.json"))
    interrupted = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert interrupted["state"] == "dispatching"
    assert interrupted["reason"] == "dispatch_interrupted"
    assert "crash" in interrupted["error"]
    result = bridge.run("all issues", action_gate=True)
    assert result["state"] == "completed"
    assert result["admission_fence"] == 2
    assert calls[0][0]["admission_fence"] == 1
    assert calls[1][0]["admission_fence"] == 2

def test_missing_verification_stays_partial():
    bridge, _ = build(evidence=[{"pr": "#1", "verification": None}])
    result = bridge.run("all issues", action_gate=True)
    assert (result["state"], result["reason"]) == ("partial", "evidence_incomplete")
