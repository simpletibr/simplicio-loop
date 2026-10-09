"""Watcher wiring: intake_gate (#1465), claim_lease (#1464), watcher_github (#1470, #1471).

Each test drives tick.tick() end to end; only proc.run (gh, git, turbo) is faked.
"""
import asyncio
from datetime import timedelta

from simplicio_loop.claim_lease import ClaimStore
from simplicio_loop.github_lifecycle import render_lifecycle_comment
from simplicio_loop.watcher247 import config, state
from simplicio_loop.watcher247.__main__ import main as watcher_main

from .fakes import FIXED, PR_URL, FakeRun, baseline, issue, pr_row, read_json, run_tick, tasks, write_json


def test_repo_without_loop_toml_is_skipped(env):
    fake = env(FakeRun({"simplicio-b": [issue(2)], "simplicio-a": [issue(1)]}, opted_in={"simplicio-a"}))
    baseline()
    run_tick()
    assert fake.ran("gh", "issue", "list", "--repo", "simpletibr/simplicio-b") == []
    assert len(tasks(fake)) == 1 and "Issue #1" in tasks(fake)[0]
    assert read_json(config.STATUS)["skipped_repos"] == {"simplicio-b": "not_opted_in"}


def test_repo_gate_error_is_recorded_and_repo_skipped(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}, broken_gate={"simplicio-a"}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert read_json(config.STATUS)["skipped_repos"] == {"simplicio-a": "gh_api_error"}


def test_issue_without_loop_auto_label_is_skipped(env):
    fake = env(FakeRun({"simplicio-a": [issue(1, labels=()), issue(2)]}))
    baseline()
    run_tick()
    assert len(tasks(fake)) == 1 and "Issue #2" in tasks(fake)[0]
    assert read_json(config.STATUS)["skipped_issues"] == {"simplicio-a#1": "missing_label"}


def test_needs_human_posts_one_question_and_never_processes(env):
    fake = env(FakeRun({"simplicio-a": [issue(3, body="vago")]}))
    baseline()
    run_tick()
    run_tick()  # the second tick must not post the question again
    assert fake.turbo_argv == []
    assert len(fake.marker_comments(3)) == 1
    assert fake.canonical_state(3) == "BLOCKED"
    assert "Por favor, forneça" in fake.marker_comments(3)[0]["body"]
    assert len([w for w in fake.api_writes if w[0] == "POST"]) == 1


def test_expired_lease_is_reaped_then_retried_when_due(env, monkeypatch):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {
        "key": "simplicio-a#5", "owner": "crashed", "owner_token": "old",
        "lease_expires_at": (FIXED - timedelta(minutes=5)).timestamp(), "attempts": 1,
        "status": "running", "started_at": state.iso(FIXED - timedelta(minutes=10)),
    }})
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["reason_code"] == "lease_expired"
    assert fake.turbo_argv == []
    monkeypatch.setattr(state, "now", lambda: FIXED + timedelta(minutes=10))  # past the 5 min retry window
    run_tick()
    assert len(fake.turbo_argv) == 1
    assert read_json(config.CLAIMS)["simplicio-a#5"]["status"] == "done"


def test_heartbeat_runs_while_turbo_is_long(env, monkeypatch):
    env(FakeRun({"simplicio-a": [issue(6)]}, delay=0.2))
    baseline()
    beats = []
    original = ClaimStore.heartbeat

    async def counting(self, key, owner_token, ttl_s, now=None):
        beats.append(key)
        return await original(self, key, owner_token, ttl_s, now=now)

    monkeypatch.setattr(ClaimStore, "heartbeat", counting)
    monkeypatch.setattr(config, "HEARTBEAT_S", 0.02)
    run_tick()
    assert len(beats) >= 2
    assert read_json(config.CLAIMS)["simplicio-a#6"]["status"] == "done"


def test_one_status_comment_is_updated_in_place_per_phase(env):
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert len(fake.marker_comments(7)) == 1
    posts = [w for w in fake.api_writes if w[0] == "POST" and w[1].endswith("/issues/7/comments")]
    patches = [w for w in fake.api_writes if w[0] == "PATCH"]
    assert len(posts) == 1
    assert len(patches) >= 4  # PLANNED, IN_PROGRESS, VERIFYING, PR_OPEN
    assert fake.canonical_state(7) == "PR_OPEN"
    assert read_json(config.CLAIMS)["simplicio-a#7"]["pr"] == PR_URL


def test_claim_held_by_another_owner_skips_the_issue(env):
    fake = env(FakeRun({"simplicio-a": [issue(8)]}))
    body = render_lifecycle_comment(state="CLAIMED", run_id="other", attempt_id="x",
                                    agent_id="other-session")
    fake.comments[8] = [{"id": 4000, "body": body}]
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert fake.api_writes == []
    assert "other-session" in fake.marker_comments(8)[0]["body"]


def test_review_on_loop_pr_becomes_queued_fix_for_the_same_issue(env):
    review = {"author": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "body": "troque o retorno para dict"}
    fake = env(FakeRun(
        {"simplicio-a": [issue(7)]},
        prs=[pr_row(9, "loop/issue-7", review="CHANGES_REQUESTED")],
        pr_views={9: {"reviews": [review], "files": [{"path": "app.py"}], "statusCheckRollup": []}},
    ))
    baseline("simplicio-a#7")  # the issue is old, but the fix is new work for it
    run_tick()
    assert len(fake.turbo_argv) == 1
    assert "troque o retorno para dict" in tasks(fake)[0] and "Issue #7" in tasks(fake)[0]
    # git checkout origin/loop/issue-7 is now part of git worktree add -B in the new model
    assert any(a[4:6] == ["-B", "loop/issue-7"] and a[-1] == "origin/loop/issue-7" for a in fake.ran("git", "worktree", "add"))
    run_tick()  # the same review is never queued twice
    assert len(fake.turbo_argv) == 1


def test_legacy_running_claim_is_migrated_once_at_startup(env):
    fake = env(FakeRun({"simplicio-a": [issue(4)]}))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#4": {
        "status": "running", "attempts": 1, "started_at": state.iso(FIXED - timedelta(hours=1)),
    }})
    asyncio.run(watcher_main(once=True))
    claim = read_json(config.CLAIMS)["simplicio-a#4"]
    assert claim["status"] == "retry" and claim["reason_code"] == "lease_expired"
    assert fake.turbo_argv == []  # the migrated retry is not due yet


def test_epic_is_never_executed_directly(env):
    fake = env(FakeRun({"simplicio-a": [issue(9, title="[EPIC] reescrever o watcher")]}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert fake.canonical_state(9) == "BLOCKED"
    assert "épica" in fake.marker_comments(9)[0]["body"]
