"""Tick-level tests of the 24/7 watcher: every subprocess is answered by FakeRun (see fakes.py)."""
from __future__ import annotations

import asyncio
import io
import os
import urllib.error
from datetime import timedelta
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import config, proc, state, subscription, tick, verify
from simplicio_loop.watcher247.__main__ import main as watcher_main

from .fakes import FIXED, PR_URL, FakeRun, baseline, issue, read_json, run_tick, write_json


def test_first_tick_writes_baseline_only(env):
    fake = env(FakeRun({"simplicio-a": [issue(1), issue(2)]}))
    run_tick()
    assert read_json(config.BASELINE)["issues"] == ["simplicio-a#1", "simplicio-a#2"]
    assert fake.ran("simplicio-loop") == []
    assert fake.api_writes == []
    assert read_json(config.STATUS)["phase"] == "baselined"
    assert not config.CLAIMS.exists()


def test_baselined_issue_is_never_processed(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline("simplicio-a#1")
    run_tick()
    assert fake.ran("simplicio-loop") == []
    assert read_json(config.STATUS)["phase"] == "idle"


def test_exactly_one_due_issue_at_concurrency_one(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)], "simplicio-b": [issue(2)], "simplicio-c": [issue(3)]}, diff=False))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 1
    claims = read_json(config.CLAIMS)
    assert list(claims) == ["simplicio-a#1"]
    status = read_json(config.STATUS)
    assert status["phase"] == "processed" and status["last"] == "simplicio-a#1"


def test_turbo_ok_commits_opens_pr_and_comments_url(env):
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    baseline()
    run_tick()
    argv = fake.turbo_argv[0]
    assert argv[:2] == ["simplicio-loop", "turbo"]
    assert argv[argv.index("--repo") + 1] == str(config.WORK / "simplicio-a.wt" / "7")  # the item's own worktree, not the base clone
    assert argv[argv.index("--provider") + 1] == "openrouter"
    task = argv[argv.index("--task") + 1]
    assert "Issue #7: Add x" in task and "Protocolo Simplicio-Loop, nesta ordem" in task and "50 pontos" not in task
    assert "assinatura" not in task and "MCP" not in task, "the prompt no longer claims an MCP subscription"
    assert "dev-cli aplica" in task and "CLI de execucao planeja" in task, "it states what actually runs"
    assert fake.turbo_timeouts == [900]
    commit = fake.ran("git", "commit")[0]
    assert commit[3] == "loop: Add x\n\nCloses #7\n"
    assert fake.ran("git", "add", "-A") and fake.ran("git", "reset", "-q", "--", ".simplicio-loop")
    assert fake.ran("git", "push", "-u", "origin", "loop/issue-7")
    pr = fake.ran("gh", "pr", "create")[0]
    assert pr[pr.index("--base") + 1] == "main" and pr[pr.index("--head") + 1] == "loop/issue-7"
    assert PR_URL in fake.marker_comments(7)[-1]["body"]
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "done" and claim["pr"] == PR_URL and claim["turbo_status"] == "ok"
    assert (config.LOGS / "simplicio-a-7-1.log").exists()


def test_turbo_ok_without_diff_is_done_no_diff(env):
    fake = env(FakeRun({"simplicio-a": [issue(4)]}, diff=False))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("git", "commit") == []
    claim = read_json(config.CLAIMS)["simplicio-a#4"]
    assert claim["status"] == "done_no_diff" and claim["pr"] is None
    assert "sem diff" in fake.marker_comments(4)[-1]["body"]


def test_first_failure_schedules_retry_in_six_hours(env):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}, turbo_ok=False))
    baseline()
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["attempts"] == 1 and claim["error"] == "boom"
    assert claim["next_try_at"] == state.iso(FIXED + timedelta(hours=6))
    assert "parou" not in fake.marker_comments(5)[-1]["body"]


def test_retry_is_not_due_before_six_hours(env):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}, turbo_ok=False))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {"attempts": 1, "status": "retry", "next_try_at": state.iso(FIXED + timedelta(hours=6))}})
    run_tick()
    assert fake.turbo_argv == []


def test_second_failure_is_dead_with_stop_comment(env):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}, turbo_ok=False))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {"attempts": 1, "status": "retry", "next_try_at": state.iso(FIXED)}})
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "dead" and claim["attempts"] == 2
    assert "parou" in fake.marker_comments(5)[-1]["body"]
    run_tick()  # dead is final
    assert len(fake.turbo_argv) == 1


def test_no_subscription_processes_nothing(env, monkeypatch):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()

    async def inactive():
        return {"active": False, "reason": "subscription_required"}

    monkeypatch.setattr(subscription, "mcp_subscription", inactive)
    run_tick()
    assert fake.calls == []
    status = read_json(config.STATUS)
    assert status["phase"] == "subscription_required"
    assert status["subscription"]["reason"] == "subscription_required"


def test_stop_file_idles(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    config.STOP.write_text("")
    run_tick()
    assert fake.calls == []
    status = read_json(config.STATUS)
    assert status["phase"] == "stopped" and status["stopped"] is True


def test_skip_labels_are_never_processed(env):
    fake = env(FakeRun({"simplicio-a": [issue(1, labels=["wontfix"]), issue(2, labels=["simplicio-loop:skip"])]}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert read_json(config.STATUS)["skipped_issues"] == {"simplicio-a#1": "skip_label", "simplicio-a#2": "skip_label"}
    assert fake.api_writes == []


def test_in_flight_equals_concurrency(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    names = ["simplicio-a", "simplicio-b", "simplicio-c", "simplicio-d"]
    fake = env(FakeRun({n: [issue(i)] for i, n in enumerate(names, 1)}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert fake.max_turbo == 2
    assert len(fake.turbo_argv) == 2
    assert read_json(config.STATUS)["processed"] == ["simplicio-a#1", "simplicio-b#2"]

def test_same_repo_issues_overlap_each_in_its_own_worktree(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    bodies = ["Ajustar `a.py` para o fluxo.", "Ajustar `b.py` para o fluxo."]
    fake = env(FakeRun({"simplicio-a": [issue(1, body=bodies[0]), issue(2, body=bodies[1])]}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 2
    assert fake.max_turbo == 2 and fake.max_worktrees == 2
    assert set(fake.turbo_cwds) == {config.WORK / "simplicio-a.wt" / "1", config.WORK / "simplicio-a.wt" / "2"}
    assert fake.worktrees == {}  # both removed
    assert set(read_json(config.CLAIMS)) == {"simplicio-a#1", "simplicio-a#2"}


def test_different_repos_do_overlap(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    fake = env(FakeRun({"simplicio-a": [issue(1)], "simplicio-b": [issue(2)]}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert fake.max_turbo == 2

def test_dry_run_reads_but_writes_nothing(env, tmp_path):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    before = sorted(p.name for p in tmp_path.iterdir())
    asyncio.run(watcher_main(once=True, dry_run=True))
    assert fake.turbo_argv == [] and fake.api_writes == []
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_tick_error_is_recorded_in_status(env, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("gh exploded")

    env(FakeRun({}))
    monkeypatch.setattr(tick.github, "repos", boom)
    assert asyncio.run(watcher_main(once=True)) == 0
    status = read_json(config.STATUS)
    assert status["phase"] == "error" and "gh exploded" in status["error"]


# --- dirty() -----------------------------------------------------------------


@pytest.mark.parametrize("porcelain,expected", [
    ("", False),
    ("?? .simplicio-loop/state.json\n?? .simplicio-loop/x\n", False),
    (" M .gitignore\n", False),
    (" M src/app.py\n", True),
    ("?? .simplicio-loop/x\n M src/app.py\n", True),
])
def test_dirty(env, porcelain, expected):
    async def fake(argv, timeout=120, cwd=None):
        return proc.Result(0, porcelain)

    env(fake)
    assert asyncio.run(tick.dirty(Path("/x"))) is expected


def test_parse_turbo_variants():
    assert verify.parse_turbo("") == {}
    assert verify.parse_turbo('{"status": "ok"}') == {"status": "ok"}
    assert verify.parse_turbo('noise\n{"schema": "s", "status": "ok"}') == {"schema": "s", "status": "ok"}
    assert verify.parse_turbo("plain failure")["status"] == "failed"


def test_run_kills_process_on_timeout():
    with pytest.raises(TimeoutError):
        asyncio.run(proc.run(["sleep", "30"], timeout=0.3))


def test_run_returns_output():
    result = asyncio.run(proc.run(["sh", "-c", "echo out; echo err >&2; exit 3"], timeout=10))
    assert (result.returncode, result.stdout, result.stderr) == (3, "out\n", "err\n")


# --- mcp_subscription reason codes ----------------------------------------------


def http_error(code=401):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"denied"))


@pytest.fixture
def login(tmp_path, monkeypatch):
    path = tmp_path / "login.json"
    monkeypatch.setattr(config, "LOGIN", path)
    return path


def entitlement(**over):
    ent = {"active": True, "status": "active", "source": "stripe", "tier": "pro", "plan": "p"}
    return {"active": True, "entitlement": {**ent, **over}}


def set_http(monkeypatch, handler):
    async def fake(method, url, payload=None, headers=None):
        return handler(method, url, payload, headers)

    monkeypatch.setattr(subscription, "http_json", fake)


def reason():
    return asyncio.run(subscription.mcp_subscription())


def test_subscription_login_missing(login):
    assert reason()["reason"] == "login_missing"


def test_subscription_login_without_tokens(login):
    write_json(login, {})
    assert reason()["reason"] == "login_missing"


def test_subscription_login_insecure_when_others_can_read_the_file(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})
    login.chmod(0o644)
    set_http(monkeypatch, lambda *a: pytest.fail("no request may be made with an unsafe login file"))
    result = reason()
    assert result["reason"] == "login_insecure" and result["active"] is False
    assert f"chmod 600 {login}" in result["detail"]


def test_subscription_login_insecure_for_a_symlink_and_a_loose_folder(login, tmp_path, monkeypatch):
    set_http(monkeypatch, lambda *a: pytest.fail("no request may be made with an unsafe login file"))
    real = tmp_path / "real.json"
    write_json(real, {"access_token": "a", "access_expires_at": 4102444800})
    login.symlink_to(real)
    assert reason()["reason"] == "login_insecure"
    login.unlink()
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})
    login.parent.chmod(0o777)
    try:
        result = reason()
    finally:
        login.parent.chmod(0o700)
    assert result["reason"] == "login_insecure" and "chmod 700" in result["detail"]


def test_subscription_directory_or_fifo_as_login_is_login_missing_not_a_traceback(login):
    login.mkdir()
    assert reason()["reason"] == "login_missing"
    login.rmdir()
    os.mkfifo(login, 0o600)
    assert reason()["reason"] == "login_missing"


def test_subscription_ok(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})
    seen = {}

    def handler(method, url, payload, headers):
        seen.update(method=method, url=url, auth=headers["Authorization"])
        return entitlement()

    set_http(monkeypatch, handler)
    result = reason()
    assert result["active"] is True and result["reason"] == "ok" and result["tier"] == "pro"
    assert seen == {"method": "GET", "url": config.VALIDATE_URL, "auth": "Bearer a"}


@pytest.mark.parametrize("over", [
    {"tier": "free"}, {"status": "canceled"}, {"source": "trial"}, {"active": False},
])
def test_subscription_required(login, monkeypatch, over):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})
    set_http(monkeypatch, lambda *a: entitlement(**over))
    assert reason()["reason"] == "subscription_required"


def test_paid_sources():
    assert config.PAID_SOURCES == {"subscription", "stripe", "admin"}


def test_login_path_follows_env_then_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "svc"))
    monkeypatch.delenv("SIMPLICIO_247_LOGIN", raising=False)
    assert config.default_login() == tmp_path / "svc" / ".simplicio" / "login.json"
    monkeypatch.setenv("SIMPLICIO_247_LOGIN", str(tmp_path / "custom.json"))
    assert config.default_login() == tmp_path / "custom.json"
    assert "/root" not in str(config.default_login())


def test_subscription_entitlement_required_on_http_error(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})

    def handler(*a):
        raise http_error()

    set_http(monkeypatch, handler)
    result = reason()
    assert result["reason"] == "entitlement_required" and result["detail"] == "denied"


def test_subscription_validate_unreachable(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})

    def handler(*a):
        raise OSError("down")

    set_http(monkeypatch, handler)
    assert reason()["reason"] == "validate_unreachable"


def test_subscription_refresh_failed(login, monkeypatch):
    write_json(login, {"access_token": "old", "refresh_token": "r", "access_expires_at": 0})

    def handler(*a):
        raise http_error(400)

    set_http(monkeypatch, handler)
    assert reason()["reason"] == "refresh_failed"


def test_subscription_refresh_stores_tokens_then_validates(login, monkeypatch):
    write_json(login, {"access_token": "old", "refresh_token": "r", "access_expires_at": 0})

    def handler(method, url, payload, headers):
        if method == "POST":
            assert payload["grant_type"] == "refresh_token" and payload["refresh_token"] == "r"
            return {"access_token": "new", "refresh_token": "r2", "expires_in": 3600}
        assert headers["Authorization"] == "Bearer new"
        return entitlement()

    set_http(monkeypatch, handler)
    assert reason()["reason"] == "ok"
    stored = read_json(login)
    assert stored["access_token"] == "new" and stored["refresh_token"] == "r2"
    assert oct(login.stat().st_mode & 0o777) == "0o600"
