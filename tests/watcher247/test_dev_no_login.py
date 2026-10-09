"""SIMPLICIO_247_NO_LOGIN=1: a DEV-ONLY switch that skips the login/subscription gate of the tick, nothing else.

It is a release blocker (docs/RELEASE.md, scripts/release_rehearsal.py dev-switches): the tests here pin what it may do
(skip `subscription.mcp_subscription`, never read or write the login file, say so on every tick and every status) and what
it must not do (anything else: admission, opt-in, claims, budgets).
"""
from __future__ import annotations

import pytest

from simplicio_loop import auth
from simplicio_loop.watcher247 import config, subscription

from .fakes import FakeRun, baseline, issue, read_json, run_tick

SWITCH = "SIMPLICIO_247_NO_LOGIN"


@pytest.fixture
def gate(monkeypatch):
    """Counts the calls of the real subscription gate (the env fixture's stub is replaced) and forbids any login I/O."""
    calls = []

    async def counted():
        calls.append(1)
        return {"active": True, "reason": "ok"}

    def no_login_io(*_args, **_kwargs):
        raise AssertionError("the login file was touched")

    monkeypatch.setattr(subscription, "mcp_subscription", counted)
    monkeypatch.setattr(auth, "read_login", no_login_io)
    monkeypatch.setattr(auth, "refresh_if_due", no_login_io)
    monkeypatch.delenv(SWITCH, raising=False)
    return calls


def test_off_by_default_the_gate_runs(env, gate, capsys):
    env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick()
    assert gate == [1]
    status = read_json(config.STATUS)
    assert status["subscription"] == {"active": True, "reason": "ok"}
    assert "dev_no_login" not in str(status) and SWITCH not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["", "0", "10", "true", "TRUE", "yes", "on", " 1", "1 ", "01"])
def test_only_the_exact_value_one_turns_it_on(env, gate, monkeypatch, value):
    env(FakeRun({"simplicio-a": [issue(1)]}))
    monkeypatch.setenv(SWITCH, value)
    baseline()
    run_tick()
    assert gate == [1]
    assert "dev_no_login" not in str(read_json(config.STATUS))


def test_on_skips_the_gate_never_touches_the_login_and_still_works(env, gate, monkeypatch, tmp_path):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    login = tmp_path / "login.json"
    login.write_text('{"sentinel": true}\n')
    login.chmod(0o600)
    before = (login.read_bytes(), login.stat().st_mtime_ns)
    monkeypatch.setattr(config, "LOGIN", login)
    monkeypatch.setenv(SWITCH, "1")
    baseline()
    run_tick()
    assert gate == []
    assert (login.read_bytes(), login.stat().st_mtime_ns) == before
    status = read_json(config.STATUS)
    assert status["phase"] == "processed" and len(fake.turbo_argv) == 1
    sub = status["subscription"]
    assert sub["reason"] == "dev_no_login" and sub["active"] is False
    assert "ok" not in (sub.get("reason"), sub.get("status")) and sub.get("detail")


def test_on_every_tick_logs_loudly_and_every_status_says_so(env, gate, monkeypatch, capsys):
    env(FakeRun({"simplicio-a": [issue(1)], "simplicio-b": [issue(2)]}))
    monkeypatch.setenv(SWITCH, "1")
    seen = []

    def tick_and_check(phase):
        capsys.readouterr()
        run_tick()
        out = capsys.readouterr().out
        status = read_json(config.STATUS)
        assert status["phase"] == phase, status
        assert status["subscription"]["reason"] == "dev_no_login" and status["subscription"]["active"] is False
        lines = [line for line in out.splitlines() if SWITCH in line]
        assert len(lines) == 1 and "DEV" in lines[0] and "login" in lines[0].lower(), out
        seen.append(phase)

    tick_and_check("baselined")  # first tick: the baseline
    tick_and_check("idle")  # nothing new
    config.STOP.write_text("")
    tick_and_check("stopped")  # an early return still carries the field
    config.STOP.unlink()
    baseline("simplicio-b#2")
    tick_and_check("processed")
    assert seen == ["baselined", "idle", "stopped", "processed"] and gate == []


def test_on_bypasses_nothing_else(env, gate, monkeypatch):
    """No label, no trusted author, no repo opt-in: still skipped. The cap still stops the tick."""
    fake = env(FakeRun({"simplicio-a": [issue(1, labels=()), issue(2, association="NONE")],
                        "simplicio-b": [issue(3)]}, opted_in=["simplicio-a"]))
    monkeypatch.setenv(SWITCH, "1")
    baseline()
    run_tick()
    status = read_json(config.STATUS)
    assert fake.turbo_argv == []
    assert status["skipped_issues"] == {"simplicio-a#1": "missing_label", "simplicio-a#2": "author_not_allowed"}
    assert status["skipped_repos"] == {"simplicio-b": "not_opted_in"}
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "0")
    run_tick()
    status = read_json(config.STATUS)
    assert status["phase"] == "daily_cap_reached" and status["subscription"]["reason"] == "dev_no_login"


def test_dry_run_with_the_switch_stays_read_only_and_logs(env, gate, monkeypatch, capsys):
    env(FakeRun({"simplicio-a": [issue(1)]}))
    monkeypatch.setenv(SWITCH, "1")
    baseline()
    run_tick(dry_run=True)
    out = capsys.readouterr().out
    assert gate == [] and SWITCH in out and "[dry-run] would process simplicio-a#1" in out
    assert not config.STATUS.exists()
