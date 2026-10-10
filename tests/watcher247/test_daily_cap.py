"""Tick-level daily cap and sandbox refusal: the tick processes nothing and status.json says why."""
from __future__ import annotations

from datetime import datetime, timezone

from simplicio_loop.watcher247 import config, sandbox, state, tick
from .fakes import FakeRun, baseline, issue, read_json, run_tick, write_json


def test_issues_cap_reached_processes_nothing(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "2")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    write_json(config.BUDGET, {"day": "2026-01-01", "issues": 2, "model_calls": 2, "prs": 0})
    run_tick()
    assert fake.turbo_argv == [] and fake.ran("gh", "issue", "list") == []
    status = read_json(config.STATUS)
    assert status["phase"] == "daily_cap_reached" and status["reason_code"] == "daily_cap_reached"
    assert status["budget"]["issues"] == 2 and status["budget"]["max_issues"] == 2


def test_prs_cap_reached_processes_nothing(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_PRS_PER_DAY", "1")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    write_json(config.BUDGET, {"day": "2026-01-01", "issues": 0, "model_calls": 0, "prs": 1})
    run_tick()
    assert fake.turbo_argv == []
    assert read_json(config.STATUS)["phase"] == "daily_cap_reached"


def test_the_map_gc_still_runs_when_the_daily_cap_is_reached(env, monkeypatch):
    """#1671: the cap limits the work on issues, not the housekeeping. A watcher that sits at its cap most of the day must
    still collect the map store, so the gc is called before the cap returns. A dry run never does it."""
    calls = []
    monkeypatch.setattr(tick, "_map_gc_bases", lambda: calls.append("gc"))
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "2")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    write_json(config.BUDGET, {"day": "2026-01-01", "issues": 2, "model_calls": 2, "prs": 0})
    run_tick(dry_run=True)
    assert calls == []
    run_tick()
    assert calls == ["gc"]
    assert fake.turbo_argv == [] and read_json(config.STATUS)["phase"] == "daily_cap_reached"


def test_batch_never_exceeds_remaining_issues(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "2")
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "3")
    fake = env(FakeRun({"simplicio-a": [issue(1), issue(2), issue(3)]}, diff=False))
    baseline()
    write_json(config.BUDGET, {"day": "2026-01-01", "issues": 0, "model_calls": 0, "prs": 0})
    run_tick()
    assert len(fake.turbo_argv) == 2
    counted = read_json(config.BUDGET)
    assert counted["issues"] == 2 and counted["model_calls"] == 2


def test_cap_counts_pr_opened(env):
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert read_json(config.BUDGET)["prs"] == 1
    assert fake.ran("gh", "pr", "create")


def test_cap_resets_on_next_utc_day(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "1")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}, diff=False))
    baseline()
    write_json(config.BUDGET, {"day": "2026-01-01", "issues": 1, "model_calls": 1, "prs": 0})
    monkeypatch.setattr(state, "now", lambda: datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc))
    run_tick()
    assert len(fake.turbo_argv) == 1
    assert read_json(config.BUDGET)["day"] == "2026-01-02"


def test_no_sandbox_refuses_the_tick(env, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: None)
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick()
    assert fake.turbo_argv == [] and fake.calls == []
    status = read_json(config.STATUS)
    assert status["phase"] == "blocked" and status["reason_code"] == "sandbox_unavailable"


def test_turbo_runs_through_the_sandbox_with_scrubbed_env(env, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap" if binary == "bwrap" else None)
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}, diff=False))
    wrapped = []

    async def spy(argv, timeout=120, cwd=None, env=None, stdin=None):
        if argv[0] == "bwrap":
            wrapped.append((argv, env))
            argv = argv[argv.index("--") + 1:]
        return await fake(argv, timeout, cwd, stdin=stdin)

    monkeypatch.setattr(tick.proc, "run", spy)
    baseline()
    run_tick()
    argv, turbo_env = wrapped[0]
    assert argv[:2] == ["bwrap", "--ro-bind"]
    assert "GH_TOKEN" not in turbo_env and "must-not-leak" not in turbo_env.values()
