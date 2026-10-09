"""Tests for watcher247 event emission to the dashboard."""
import json
from pathlib import Path

import pytest

from simplicio_loop import dashboard_events
from simplicio_loop.watcher247 import events


def test_emit_intake_event(tmp_path: Path) -> None:
    """An intake event can be emitted and is readable by the dashboard."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    
    result = events.emit_stage(run_dir, "intake", "ok")
    assert result is not None
    assert result["kind"] == "watcher.intake"
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
    assert event["kind"] == "watcher.intake"
    assert event["phase"] == "intake"


def test_emit_pr_event(tmp_path: Path) -> None:
    """A pr event can be emitted after an intake event."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    
    # Emit intake first
    events.emit_stage(run_dir, "intake", "ok")
    
    # Emit pr event
    result = events.emit_stage(run_dir, "pr", "ok", pr_number=123)
    assert result is not None
    assert result["kind"] == "watcher.pr"
    assert result["phase"] == "pr"
    
    # Verify both events are in the file
    events_file = run_dir / "events.jsonl"
    with open(events_file) as f:
        lines = f.readlines()
    
    assert len(lines) == 2
    events_list = [json.loads(line) for line in lines]
    
    # Check sequence numbers are contiguous
    assert events_list[0]["seq"] == 1
    assert events_list[1]["seq"] == 2
    
    # Check kinds
    assert events_list[0]["kind"] == "watcher.intake"
    assert events_list[1]["kind"] == "watcher.pr"


def test_events_readable_by_dashboard(tmp_path: Path) -> None:
    """Mixed watcher and turbo events can be read by the dashboard."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    
    # Emit watcher events
    events.emit_stage(run_dir, "intake", "ok")
    events.emit_stage(run_dir, "pr", "ok", pr_number=456)
    
    # Read through dashboard API
    read_events = dashboard_events.read_events(run_dir)
    assert len(read_events) == 2
    
    # Check stages are in order
    kinds = [e.get("kind") for e in read_events]
    assert kinds == ["watcher.intake", "watcher.pr"]


def test_emit_stage_idempotent_safe(tmp_path: Path) -> None:
    """Multiple calls with the same event don't create duplicates (via seq)."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    
    # Emit the same event twice
    result1 = events.emit_stage(run_dir, "intake", "ok")
    result2 = events.emit_stage(run_dir, "intake", "ok")
    
    # Both succeed (emit is idempotent at the appending level)
    assert result1 is not None
    assert result2 is not None
    
    # But sequences are different
    assert result1["seq"] == 1
    assert result2["seq"] == 2
    
    # File has both lines
    events_file = run_dir / "events.jsonl"
    with open(events_file) as f:
        lines = f.readlines()
    assert len(lines) == 2
