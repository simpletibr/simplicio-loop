"""The tick calls the point registry exactly once per stage (#1509); the points themselves are tested apart."""
from __future__ import annotations

from datetime import timedelta

import pytest

from simplicio_loop.watcher247 import config, points

from .fakes import PR_URL, FakeRun, baseline, issue, read_json, run_tick, tasks


@pytest.fixture
def stages(monkeypatch):
    """Record every (stage, ctx) the tick sends to points.run; each answers with one ok result."""
    seen: list[tuple[str, points.PointContext]] = []

    async def fake_run(stage, ctx):
        seen.append((stage, ctx))
        return [points.PointResult(f"spy_{stage}", "ok")]

    monkeypatch.setattr(points, "run", fake_run)
    return seen


def test_one_run_per_stage_in_order(env, stages):
    env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    baseline()
    run_tick()
    assert [stage for stage, _ in stages] == ["intake", "plan", "apply", "verify", "pr", "done"]


def test_context_carries_what_each_stage_knows(env, stages):
    env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    baseline()
    run_tick()
    by_stage = dict(stages)
    clone = config.WORK / "simplicio-a"
    for stage, ctx in stages:
        assert ctx.repo == "simplicio-a" and ctx.issue["number"] == 7 and ctx.clone == clone
        assert ctx.state_dir == config.ROOT
        assert ctx.run_dir == clone / ".simplicio-loop" / "orchestrator" / "points" / "simplicio-a-7"
    assert "Issue #7: Add x" in by_stage["plan"].task_text
    assert by_stage["apply"].turbo_json["turbo_status"] == "ok"
    assert by_stage["verify"].verify == by_stage["apply"].turbo_json["verify"]
    assert by_stage["pr"].pr_url is None
    assert by_stage["done"].pr_url == PR_URL


def test_no_diff_run_still_ends_with_done(env, stages):
    env(FakeRun({"simplicio-a": [issue(4)]}, diff=False))
    baseline()
    run_tick()
    assert [stage for stage, _ in stages][-1] == "done"
    assert dict(stages)["done"].pr_url is None


def test_blocked_result_at_pr_stops_the_pr(env, monkeypatch):
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    ran = []

    async def gate(stage, ctx):
        ran.append(stage)
        if stage == "pr":
            return [points.PointResult("delivery_gate", "blocked", {}, "gate_failed")]
        return []

    monkeypatch.setattr(points, "run", gate)
    run_tick()
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("git", "commit") == []
    assert "done" not in ran
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "retry" and claim["reason_code"] == "gate_failed"  # a failed attempt, not dead
    assert "gate_failed" in fake.marker_comments(7)[-1]["body"]


def raise_at(monkeypatch, stage, status, code, evidence=None, ran=None):
    """points.run raises the typed exception of a blocking point `judge` at `stage`; the other stages are empty."""
    async def fake_run(current, ctx):
        if ran is not None:
            ran.append(current)
        if current == stage:
            result = points.PointResult("judge", status, evidence or {}, code)
            kind = points.PointDeferred if status == "deferred" else points.PointBlocked
            raise kind(current, "judge", code, [result])
        return []

    monkeypatch.setattr(points, "run", fake_run)


def test_blocked_at_verify_retries_with_the_reasons_and_is_dead_only_at_the_max(env, monkeypatch):
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    monkeypatch.setattr(config, "RETRY_AFTER", timedelta(0))  # the retry is due on the next tick
    raise_at(monkeypatch, "verify", "blocked", "judge_reject", {"why": "no tests"})
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "retry" and claim["attempts"] == 1 and claim["reason_code"] == "judge_reject"
    assert claim["owner_token"] is None  # released
    body = fake.marker_comments(7)[-1]["body"]
    assert "judge_reject" in body and "no tests" in body
    assert fake.ran("gh", "pr", "create") == []

    run_tick()  # attempt 2 is told why attempt 1 was refused, and the limit (2) is reached
    first, second = tasks(fake)
    assert "judge_reject" not in first and "judge_reject" in second and "no tests" in second
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "dead" and claim["attempts"] == config.MAX_ATTEMPTS
    assert "judge_reject" in fake.marker_comments(7)[-1]["body"]

    run_tick()  # dead stays dead
    assert len(tasks(fake)) == 2


def test_deferred_at_intake_consumes_no_attempt_and_is_due_on_the_next_tick(env, monkeypatch):
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    ran, real_run = [], points.run
    raise_at(monkeypatch, "intake", "deferred", "low_disk", ran=ran)
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "retry" and claim["attempts"] == 0  # the attempt is given back
    assert claim["owner_token"] is None and claim["lease_expires_at"] is None  # claim and lease released
    assert claim.get("next_try_at") is None and claim["reason_code"] == "low_disk"
    assert ran == ["intake"] and tasks(fake) == []
    assert "deferred: low_disk" in fake.marker_comments(7)[-1]["body"]

    monkeypatch.setattr(points, "run", real_run)  # the condition cleared: the real registry runs again
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "done" and claim["attempts"] == 1


def test_deferred_never_reaches_dead_however_often_it_repeats(env, monkeypatch):
    env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    raise_at(monkeypatch, "intake", "deferred", "high_load")
    for _ in range(config.MAX_ATTEMPTS + 2):
        run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "retry" and claim["attempts"] == 0


def test_a_blocked_attempt_is_recorded_as_failed_in_the_escalation_ladder(tmp_path):
    from simplicio_loop import escalation
    from simplicio_loop.watcher247 import tick
    ctx = points.PointContext(repo="simplicio-a", clone=tmp_path, family="codex")
    tick._note_failed_attempt(ctx, 7, "judge: judge_reject")
    ladder = escalation.load_escalation_state(tmp_path, 7, "codex")
    assert [(r.outcome, r.error) for r in ladder.records] == [("failed", "judge: judge_reject")]


def test_error_and_skipped_results_do_not_change_the_tick(env, monkeypatch):
    env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()

    async def fake_run(stage, ctx):
        return [points.PointResult("p", "error", {}, "point_exception"), points.PointResult("q", "skipped")]

    monkeypatch.setattr(points, "run", fake_run)
    run_tick()
    assert read_json(config.CLAIMS)["simplicio-a#7"]["status"] == "done"


def test_the_real_registry_runs_in_the_tick_and_writes_events(env):
    env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    events = (config.WORK / "simplicio-a" / ".simplicio-loop" / "orchestrator" / "points" / "simplicio-a-7" / "events.jsonl")
    assert "toolchain_detect" in events.read_text()
    assert read_json(config.CLAIMS)["simplicio-a#7"]["status"] == "done"
