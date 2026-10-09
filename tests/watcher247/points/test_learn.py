"""learn (done): the only caller of retrospective; it aggregates what `trajectory` wrote for a SOLVED run.

Every context here comes from the real tick (`done_ctx`), never a hand-made turbo dict.
"""
import asyncio
import json
from dataclasses import replace

import pytest

from simplicio_loop.watcher247 import config, points

from ..fakes import FakeRun, baseline, issue, run_tick
from .tick_ctx import capture_done_ctx

LESSON = "simplicio-a: solved via turbo executor; verified by MEASURED|verify_passed: `python3 -m pytest -q`"


@pytest.fixture
def done_ctx(env, monkeypatch):
    return capture_done_ctx(env, monkeypatch)


def lessons(ctx):
    path = ctx.state_dir / ".simplicio-loop" / "orchestrator" / "lessons.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run_done(ctx):
    return {r.name: r for r in asyncio.run(points.run("done", ctx))}


def test_registered_at_done_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "learn"]
    assert (info.stage, info.blocking, info.conditional) == ("done", False, True)


def test_trajectory_runs_before_learn_at_done():
    assert [i.name for i in points.registered("done") if i.name in ("trajectory", "learn")] == ["trajectory", "learn"]


def test_skipped_when_the_run_is_not_solved(point_contract, done_ctx):
    ctx = replace(done_ctx, turbo_json={"turbo_status": "failed", "exit_code": 1, "verify": done_ctx.verify})
    assert point_contract("learn", ctx, expect="skipped").reason_code == "not_applicable"


def test_skipped_for_a_dict_with_status_the_tick_never_sends(point_contract, done_ctx):
    ctx = replace(done_ctx, turbo_json={"status": "ok"})
    assert point_contract("learn", ctx, expect="skipped").reason_code == "not_applicable"


def test_skipped_without_state_dir(point_contract, make_ctx, tmp_path):
    result = point_contract("learn", make_ctx(run_dir=tmp_path, turbo_json={"turbo_status": "ok"}), expect="skipped")
    assert result.reason_code == "no_state_dir"


def test_a_solved_tick_run_writes_one_lesson_with_hit_count_one(done_ctx):
    results = run_done(done_ctx)
    assert results["trajectory"].status == "ok"
    assert results["learn"].status == "ok"
    assert results["learn"].evidence == {
        "run_id": "simplicio-a-7", "records_seen": 1, "new_lessons": 1, "merged_lessons": 0,
        "lessons_path": str(done_ctx.state_dir / ".simplicio-loop" / "orchestrator" / "lessons.jsonl")}
    [row] = lessons(done_ctx)
    assert (row["lesson"], row["hit_count"]) == (LESSON, 1)


def test_the_same_lesson_in_another_run_raises_hit_count_to_two(done_ctx):
    run_done(done_ctx)
    other = replace(done_ctx, run_dir=done_ctx.run_dir.parent / "simplicio-a-8", issue={"number": 8})
    results = run_done(other)
    assert (results["learn"].evidence["new_lessons"], results["learn"].evidence["merged_lessons"]) == (0, 1)
    [row] = lessons(done_ctx)
    assert (row["lesson"], row["hit_count"]) == (LESSON, 2)


def test_issue_7_does_not_read_the_trajectory_of_issue_70(done_ctx):
    other = replace(done_ctx, run_dir=done_ctx.run_dir.parent / "simplicio-a-70", issue={"number": 70},
                    verify="MEASURED|verify_passed: `pytest -q`",
                    turbo_json={**done_ctx.turbo_json, "verify": "MEASURED|verify_passed: `pytest -q`"})
    run_done(other)
    results = run_done(done_ctx)
    assert (results["learn"].evidence["records_seen"], results["learn"].evidence["merged_lessons"]) == (1, 0)
    assert sorted((row["lesson"], row["hit_count"]) for row in lessons(done_ctx)) == [
        ("simplicio-a: solved via turbo executor; verified by MEASURED|verify_passed: `pytest -q`", 1), (LESSON, 1)]


def test_a_solved_tick_leaves_one_lesson_in_lessons_jsonl(env):
    env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    orchestrator = config.ROOT / ".simplicio-loop" / "orchestrator"
    [record] = [json.loads(line) for line in (orchestrator / "trajectory" / "simplicio-a-7.jsonl").read_text().splitlines()]
    assert (record["issue"], record["status"]) == (7, "ok")
    [row] = [json.loads(line) for line in (orchestrator / "lessons.jsonl").read_text().splitlines()]
    assert (row["lesson"], row["hit_count"]) == (LESSON, 1)
