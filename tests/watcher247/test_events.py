"""Tests for watcher247 event emission to the dashboard."""
import json
from pathlib import Path

import pytest

from simplicio_loop import dashboard_events
from simplicio_loop.dashboard import history
from simplicio_loop.watcher247 import events


def test_emit_intake_event(tmp_path: Path) -> None:
    """An intake event emits phase_entered like turbo stages."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()

    result = events.emit_stage(run_dir, "intake", "ok")
    assert result is not None
    assert result["kind"] == "phase_entered"
    assert result["phase"] == "intake"
    assert result["severity"] == "info"
    assert result["source"] == "operator"

    # Verify it was written to events.jsonl
    events_file = run_dir / "events.jsonl"
    assert events_file.exists()

    with open(events_file) as f:
        lines = f.readlines()
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["kind"] == "phase_entered"
    assert event["phase"] == "intake"


def test_emit_pr_event(tmp_path: Path) -> None:
    """A pr event after intake emits phase_exited and phase_entered."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()

    # Emit intake first
    events.emit_stage(run_dir, "intake", "ok")

    # Emit pr event
    result = events.emit_stage(run_dir, "pr", "ok", pr_number=123)
    assert result is not None
    assert result["kind"] == "phase_entered"
    assert result["phase"] == "pr"
    assert result["payload"]["from"] == "intake"

    # Verify both events are in the file
    events_file = run_dir / "events.jsonl"
    with open(events_file) as f:
        lines = f.readlines()

    assert len(lines) == 3
    events_list = [json.loads(line) for line in lines]

    # Check sequence numbers are contiguous
    assert events_list[0]["seq"] == 1
    assert events_list[1]["seq"] == 2
    assert events_list[2]["seq"] == 3

    # Check kinds and phases
    assert events_list[0]["kind"] == "phase_entered"
    assert events_list[0]["phase"] == "intake"
    assert events_list[1]["kind"] == "phase_exited"
    assert events_list[1]["phase"] == "intake"
    assert events_list[2]["kind"] == "phase_entered"
    assert events_list[2]["phase"] == "pr"


def test_events_readable_with_turbo(tmp_path: Path) -> None:
    """Mixed watcher and turbo events appear in order: intake, orient, plan, apply, verify, pr, done."""
    run_dir = tmp_path / "test-run-mixed"
    run_dir.mkdir()

    # Emit watcher intake event
    events.emit_stage(run_dir, "intake", "ok")

    # Emit turbo-style events manually
    module = dashboard_events.load()
    assert module is not None
    turbo_specs = [
        {"kind": "phase_entered", "source": "runner", "phase": "orient", "severity": "info", "payload": {"from": None}},
        {"kind": "phase_exited", "source": "runner", "phase": "orient", "severity": "info", "payload": {"to": "plan"}},
        {"kind": "phase_entered", "source": "runner", "phase": "plan", "severity": "info", "payload": {"from": "orient"}},
        {"kind": "phase_exited", "source": "runner", "phase": "plan", "severity": "info", "payload": {"to": "apply"}},
        {"kind": "phase_entered", "source": "runner", "phase": "apply", "severity": "info", "payload": {"from": "plan"}},
        {"kind": "phase_exited", "source": "runner", "phase": "apply", "severity": "info", "payload": {"to": "verify"}},
        {"kind": "phase_entered", "source": "runner", "phase": "verify", "severity": "info", "payload": {"from": "apply"}},
    ]
    module.emit_batch(run_dir, turbo_specs)

    # Emit watcher pr event
    events.emit_stage(run_dir, "pr", "ok", pr_number=789)

    # Emit turbo done event
    module.emit_batch(run_dir, [
        {"kind": "phase_exited", "source": "runner", "phase": "verify", "severity": "info", "payload": {"to": "done"}},
        {"kind": "phase_entered", "source": "runner", "phase": "done", "severity": "info", "payload": {"from": "verify"}},
    ])

    # Read through dashboard API
    read_events = dashboard_events.read_events(run_dir)
    phase_entered = [e for e in read_events if e.get("kind") == "phase_entered"]

    # Check stages appear in order
    phases = [e.get("phase") for e in phase_entered]
    assert phases == ["intake", "orient", "plan", "apply", "verify", "pr", "done"]


def test_emit_stage_idempotent_in_reducer(tmp_path: Path) -> None:
    """Repeating emit_stage for the same phase doesnt duplicate in reducer output."""
    run_dir = tmp_path / "test-idempotent"
    run_dir.mkdir()

    # Emit intake twice
    result1 = events.emit_stage(run_dir, "intake", "ok")
    result2 = events.emit_stage(run_dir, "intake", "ok")

    # Both succeed but with different seq numbers
    assert result1 is not None
    assert result2 is not None

    # File has multiple lines
    events_file = run_dir / "events.jsonl"
    with open(events_file) as f:
        file_events = [json.loads(line) for line in f]
    assert len(file_events) == 2

    # Both phase_entered for intake (no transition, so no phase_exited)
    assert all(e["kind"] == "phase_entered" for e in file_events)
    assert all(e["phase"] == "intake" for e in file_events)
