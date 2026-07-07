"""Tests for observability.py's canonical estimator + savings-event ledger
producer (issue #88 AC3/AC4)."""

import json

from simplicio.observability import (
    SAVINGS_EVENT_SCHEMA,
    estimate_tokens,
    record_savings_event,
)


def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_estimate_tokens_positive_for_text():
    assert estimate_tokens("hello world this is a prompt") > 0


def test_record_savings_event_writes_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    out = record_savings_event(
        tmp_path,
        source="toon",
        baseline_tokens=100,
        actual_tokens=60,
        note="test block",
    )
    assert out is not None
    assert out == tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl"
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    event = lines[0]
    assert event["schema"] == SAVINGS_EVENT_SCHEMA
    assert event["source"] == "toon"
    assert event["tokens"]["baseline"] == 100
    assert event["tokens"]["actual"] == 60
    assert event["tokens"]["saved"] == 40
    assert event["tokens"]["pct_saved"] == 40.0
    assert event["note"] == "test block"
    assert "estimator" in event


def test_record_savings_event_appends(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    record_savings_event(tmp_path, source="toon", baseline_tokens=10, actual_tokens=5)
    record_savings_event(tmp_path, source="autoresearch", baseline_tokens=20, actual_tokens=18)
    out = tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl"
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    assert {e["source"] for e in lines} == {"toon", "autoresearch"}


def test_record_savings_event_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    out = record_savings_event(tmp_path, source="toon", baseline_tokens=10, actual_tokens=5)
    assert out is None
    assert not (tmp_path / ".simplicio" / "ledger").exists()


def test_record_savings_event_zero_baseline_no_division_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    out = record_savings_event(tmp_path, source="toon", baseline_tokens=0, actual_tokens=0)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0]["tokens"]["pct_saved"] == 0.0
