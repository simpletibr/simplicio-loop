"""Tests for mutants D, E, F: _map_gc_bases must NOT be called when STOP file exists, onboarding is pending, or sandbox refuses."""
from __future__ import annotations

from simplicio_loop.watcher247 import config, sandbox, state, tick, onboarding
from .fakes import FakeRun, baseline, issue, read_json, run_tick, write_json


def test_map_gc_not_called_when_stop_file_exists(env, monkeypatch):
    """Mutant D: _map_gc_bases must NOT run when STOP file exists (called after STOP check)."""
    calls = []
    monkeypatch.setattr(tick, "_map_gc_bases", lambda: calls.append("gc"))
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    config.STOP.parent.mkdir(parents=True, exist_ok=True)
    config.STOP.touch()
    run_tick()
    assert calls == [], f"_map_gc_bases was called but STOP file exists: {calls}"
    assert read_json(config.STATUS)["phase"] == "stopped"


def test_map_gc_not_called_when_onboarding_pending(env, monkeypatch):
    """Mutant E: _map_gc_bases must NOT run when onboarding is pending (no GitHub token)."""
    calls = []
    monkeypatch.setattr(tick, "_map_gc_bases", lambda: calls.append("gc"))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick()
    assert calls == [], f"_map_gc_bases was called but onboarding is pending: {calls}"
    status = read_json(config.STATUS)
    assert status["phase"] == "setup_required" and "github_token_missing" in status.get("reason_code", "")


def test_map_gc_not_called_when_sandbox_refuses(env, monkeypatch):
    """Mutant F: _map_gc_bases must NOT run when sandbox refuses."""
    calls = []
    monkeypatch.setattr(tick, "_map_gc_bases", lambda: calls.append("gc"))
    monkeypatch.delenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", raising=False)
    # sandbox refuses when SIMPLICIO_247_ALLOW_UNSANDBOXED is unset and bwrap is not found
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick()
    assert calls == [], f"_map_gc_bases was called but sandbox refused: {calls}"
    status = read_json(config.STATUS)
    assert status["phase"] == "blocked" and status["reason_code"] == "sandbox_unavailable"


def test_map_gc_called_normally_when_all_checks_pass(env, monkeypatch):
    """Baseline test: _map_gc_bases IS called when STOP, onboarding, and sandbox all pass."""
    calls = []
    monkeypatch.setattr(tick, "_map_gc_bases", lambda: calls.append("gc"))
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick(dry_run=True)
    assert calls == [], "dry_run should not call _map_gc_bases"
    run_tick()
    assert calls == ["gc"], f"_map_gc_bases should be called on normal tick: {calls}"
