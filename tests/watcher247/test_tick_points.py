"""The tick calls the point registry exactly once per stage (#1509); the points themselves are tested apart."""
from __future__ import annotations

import json

import pytest

from simplicio_loop.watcher247 import config, points

from .fakes import PR_URL, FakeRun, baseline, issue, read_json, run_tick


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
    assert claim["status"] == "dead" and claim["reason_code"] == "gate_failed"
    assert "gate_failed" in fake.marker_comments(7)[-1]["body"]


def test_the_real_registry_runs_in_the_tick_and_writes_events(env):
    env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    events = (config.WORK / "simplicio-a" / ".simplicio-loop" / "orchestrator" / "points" / "simplicio-a-7" / "events.jsonl")
    assert "toolchain_detect" in events.read_text()
    assert read_json(config.CLAIMS)["simplicio-a#7"]["status"] == "done"


def test_a_solved_tick_leaves_one_lesson_in_lessons_jsonl(env):
    env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    orchestrator = config.ROOT / ".simplicio-loop" / "orchestrator"
    [record] = [json.loads(line) for line in (orchestrator / "trajectory" / "simplicio-a-7.jsonl").read_text().splitlines()]
    assert (record["issue"], record["status"], record["pr_url"]) == (7, "ok", PR_URL)
    [row] = [json.loads(line) for line in (orchestrator / "lessons.jsonl").read_text().splitlines()]
    assert row["lesson"] == "simplicio-a: solved via turbo executor; verified by UNVERIFIED|no_test_command"
    assert row["hit_count"] == 1
