import json
from pathlib import Path

from simplicio_loop.progress import (
    PHASE_META,
    build_progress,
    render_markdown,
    render_text,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "contracts" / "progress" / "v1" / "snapshots.json"


def test_progress_snapshot_contract_covers_milestones_and_fanout():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema"] == "simplicio.progress-snapshots/v1"
    assert {case["id"] for case in payload["cases"]} >= {
        "single-0", "single-25", "single-50", "single-75", "single-100", "fanout-blocked"
    }
    for case in payload["cases"]:
        event = build_progress(case["state"])
        expected = case["expected"]
        assert {key: event[key] for key in ("percent", "status")} == {
            key: expected[key] for key in ("percent", "status")
        }, case["id"]
        assert event["gates"]["oracle"] is expected["oracle"], case["id"]
        if "lanes" in expected:
            assert len(event["lanes"]) == expected["lanes"]
        if "events" in expected:
            assert len(event["events"]) == expected["events"]


def test_progress_renderers_preserve_gates_actions_and_no_control_codes():
    state = next(case["state"] for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"] if case["id"] == "fanout-blocked")
    event = build_progress(state)
    markdown = render_markdown(event, ascii_only=True)
    plain = render_text(event, ascii_only=True)
    for output in (markdown, plain):
        assert "watcher_challenge" in output
        assert "reconcile" in output
        assert "\x1b" not in output
    assert "Lanes:" in markdown


def test_unverified_percent_100_is_clamped_until_oracle_receipt():
    state = {"run_id": "stale", "phase": "executing", "progress_percent": 100,
             "task_count": 1, "completion": {"ready": False, "verdict": "DELIVERY_PENDING"}}
    event = build_progress(state)
    assert event["percent"] == 99
    assert event["status"] == "RUNNING"
    assert event["gates"]["oracle"] is False


def test_finished_run_without_oracle_receipt_is_neither_running_nor_oracle_done():
    # Shape of a turbo run closed with status ok (phase done, finished_at stamped) whose
    # oracle receipt does not certify it: every gate stays false.
    state = {"run_id": "turbo-finished", "phase": "done", "task_count": 1,
             "current_action": "close", "next_action": "none", "finished_at": "2026-10-20T12:00:00Z",
             "evidence": {"ready": False, "status": "UNVERIFIED"},
             "completion": {"ready": False, "verdict": "DELIVERY_PENDING", "reason_code": "oracle_incomplete"}}
    event = build_progress(state)
    assert event["percent"] == 99
    assert event["status"] == "PENDING"
    assert event["label"] == "Finalizado, entrega pendente"
    assert event["icon"] == "📦"
    assert event["gates"] == {"evidence": False, "watcher": False, "oracle": False}
    assert event["completion"] == {"ready": False, "verdict": "DELIVERY_PENDING", "reason_code": "oracle_incomplete"}


def test_fully_gated_done_run_keeps_the_oracle_label_and_complete_status():
    state = {"run_id": "turbo-gated", "phase": "done", "task_count": 1,
             "current_action": "close", "next_action": "none", "finished_at": "2026-10-20T12:00:00Z",
             "evidence": {"ready": True, "status": "VERIFIED"},
             "watcher": {"status": "VERIFIED"},
             "completion": {"ready": True, "verdict": "COMPLETE"}}
    event = build_progress(state)
    assert event["percent"] == 100
    assert event["status"] == "COMPLETE"
    assert (event["icon"], event["label"]) == PHASE_META["done"]
    assert event["gates"] == {"evidence": True, "watcher": True, "oracle": True}
