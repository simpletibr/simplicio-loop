"""The point registry contract (#1509): registration, ordering, isolation, blocking, conditionals, emission."""
import asyncio
import json

import pytest

from simplicio_loop import execution_report
from simplicio_loop.watcher247 import points


def ok(name):
    async def fn(ctx):
        return points.PointResult(name, "ok", {"seen": ctx.repo})
    return fn


def run(stage, ctx):
    return asyncio.run(points.run(stage, ctx))


def test_stages_are_the_six_of_the_tick():
    assert points.STAGES == ("intake", "plan", "apply", "verify", "pr", "done")


def test_register_and_run_returns_results(empty_registry, make_ctx):
    points.register("alpha", "plan", ok("alpha"))
    [result] = run("plan", make_ctx())
    assert result == points.PointResult("alpha", "ok", {"seen": "simplicio-demo"}, None)


def test_run_only_runs_the_requested_stage(empty_registry, make_ctx):
    points.register("alpha", "plan", ok("alpha"))
    points.register("beta", "verify", ok("beta"))
    assert [r.name for r in run("verify", make_ctx())] == ["beta"]
    assert run("pr", make_ctx()) == []


def test_order_is_registration_order(empty_registry, make_ctx):
    for name in ("zulu", "alpha", "mike"):
        points.register(name, "apply", ok(name))
    assert [r.name for r in run("apply", make_ctx())] == ["zulu", "alpha", "mike"]
    assert [i.name for i in points.registered("apply")] == ["zulu", "alpha", "mike"]


def test_bad_registrations_are_refused(empty_registry):
    points.register("alpha", "plan", ok("alpha"))
    with pytest.raises(ValueError):
        points.register("alpha", "pr", ok("alpha"))  # one name, one point
    with pytest.raises(ValueError):
        points.register("beta", "nowhere", ok("beta"))
    with pytest.raises(TypeError):
        points.register("gamma", "plan", lambda ctx: None)  # not async
    with pytest.raises(ValueError):
        points.register("delta", "done", ok("delta"), blocking=True)  # the claim is released by then


def test_error_is_isolated_and_the_next_point_still_runs(empty_registry, make_ctx):
    async def boom(ctx):
        raise RuntimeError("kaput")
    points.register("boom", "verify", boom)
    points.register("after", "verify", ok("after"))
    first, second = run("verify", make_ctx())
    assert (first.name, first.status) == ("boom", "error")
    assert first.reason_code == "point_exception"
    assert "kaput" in first.evidence["error"]
    assert (second.name, second.status) == ("after", "ok")


def test_a_non_result_is_an_error_not_a_crash(empty_registry, make_ctx):
    async def wrong(ctx):
        return "ok"
    points.register("wrong", "plan", wrong)
    [result] = run("plan", make_ctx())
    assert (result.status, result.reason_code) == ("error", "invalid_result")


def test_blocking_error_stops_the_stage_with_point_blocked(empty_registry, make_ctx):
    async def boom(ctx):
        raise RuntimeError("kaput")
    points.register("first", "pr", ok("first"))
    points.register("gate", "pr", boom, blocking=True)
    points.register("never", "pr", ok("never"))
    with pytest.raises(points.PointBlocked) as caught:
        run("pr", make_ctx())
    assert caught.value.stage == "pr" and caught.value.name == "gate"
    assert [r.name for r in caught.value.results] == ["first", "gate"]
    assert caught.value.reason_code == "point_exception"


def test_blocking_point_returning_blocked_also_stops(empty_registry, make_ctx):
    async def gate(ctx):
        return points.PointResult("gate", "blocked", {}, "no_template")
    points.register("gate", "pr", gate, blocking=True)
    with pytest.raises(points.PointBlocked) as caught:
        run("pr", make_ctx())
    assert caught.value.reason_code == "no_template"


def test_non_blocking_blocked_result_is_returned_and_the_stage_goes_on(empty_registry, make_ctx):
    async def gate(ctx):
        return points.PointResult("gate", "blocked", {}, "no_template")
    points.register("gate", "pr", gate)
    points.register("after", "pr", ok("after"))
    results = run("pr", make_ctx())
    assert [r.status for r in results] == ["blocked", "ok"]
    with pytest.raises(points.PointBlocked) as caught:
        points.raise_if_blocked("pr", results)
    assert caught.value.name == "gate" and caught.value.reason_code == "no_template"
    points.raise_if_blocked("pr", results[1:])


def test_blocking_deferred_stops_the_stage_with_point_deferred(empty_registry, make_ctx):
    async def governor(ctx):
        return points.PointResult("governor", "deferred", {"free_gb": 1}, "low_disk")
    points.register("governor", "intake", governor, blocking=True)
    points.register("never", "intake", ok("never"))
    with pytest.raises(points.PointDeferred) as caught:
        run("intake", make_ctx())
    assert isinstance(caught.value, points.PointBlocked)
    assert (caught.value.name, caught.value.reason_code) == ("governor", "low_disk")
    assert [r.name for r in caught.value.results] == ["governor"]


def test_non_blocking_deferred_is_returned_and_raise_if_blocked_types_it(empty_registry, make_ctx):
    async def governor(ctx):
        return points.PointResult("governor", "deferred", {}, "high_load")
    points.register("governor", "pr", governor)
    points.register("after", "pr", ok("after"))
    results = run("pr", make_ctx())
    assert [r.status for r in results] == ["deferred", "ok"]
    with pytest.raises(points.PointDeferred) as caught:
        points.raise_if_blocked("pr", results)
    assert caught.value.reason_code == "high_load"


def test_blocked_carries_the_reasons_of_the_blocking_result(empty_registry, make_ctx):
    async def judge(ctx):
        return points.PointResult("judge", "blocked", {"verdict": "REJECT", "why": "no tests"}, "judge_reject")
    points.register("judge", "verify", judge, blocking=True)
    with pytest.raises(points.PointBlocked) as caught:
        run("verify", make_ctx())
    assert not isinstance(caught.value, points.PointDeferred)
    assert "judge_reject" in caught.value.reasons() and "no tests" in caught.value.reasons()


def test_conditional_point_is_skipped_when_applies_is_false(empty_registry, make_ctx):
    called = []

    async def web(ctx):
        called.append(ctx.repo)
        return points.PointResult("web", "ok")
    points.register("web", "verify", web, applies=lambda ctx: ctx.role == "ui")
    [skipped] = run("verify", make_ctx(role="backend"))
    assert (skipped.name, skipped.status, skipped.reason_code) == ("web", "skipped", "not_applicable")
    assert called == []
    [ran] = run("verify", make_ctx(role="ui"))
    assert ran.status == "ok" and called == ["simplicio-demo"]
    assert [i.conditional for i in points.registered()] == [True]


def test_applies_that_raises_is_an_error_result(empty_registry, make_ctx):
    def applies(ctx):
        raise KeyError("x")
    points.register("web", "verify", ok("web"), applies=applies)
    [result] = run("verify", make_ctx())
    assert (result.status, result.reason_code) == ("error", "applies_exception")


def test_registered_metadata(empty_registry):
    points.register("alpha", "plan", ok("alpha"), blocking=True)
    [info] = points.registered()
    assert (info.name, info.stage, info.blocking, info.conditional) == ("alpha", "plan", True, False)
    assert info.module == __name__


def test_context_is_frozen_and_every_field_is_optional():
    ctx = points.PointContext(repo="r")
    assert ctx.issue is None and ctx.clone is None and ctx.run_dir is None and ctx.pr_url is None
    with pytest.raises(Exception):
        ctx.repo = "other"


def test_results_go_to_events_and_execution_report(empty_registry, make_ctx, tmp_path):
    points.register("alpha", "plan", ok("alpha"))
    points.register("beta", "plan", ok("beta"), applies=lambda ctx: False)
    run_dir = tmp_path / "clone" / "runs" / "points-demo-7"
    state_dir = tmp_path / "state"
    ctx = make_ctx(issue={"number": 7}, run_dir=run_dir, state_dir=state_dir)
    run("plan", ctx)
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert [(e["kind"], e["phase"], e["payload"]["point"], e["payload"]["status"]) for e in events] == [
        ("watcher.point", "plan", "alpha", "ok"), ("watcher.point", "plan", "beta", "skipped")]
    report = execution_report.load_latest(state_dir)
    assert report["schema"] == "simplicio.execution-report/v1" and report["run_id"] == "points-demo-7"
    assert [t["task_id"] for t in report["tasks"]] == ["plan:alpha", "plan:beta"]
    assert report["tasks"][0]["issue"] == "7" and report["tasks"][0]["evidence"] == {"seen": "simplicio-demo"}
    run("verify", ctx)  # no point at verify: nothing is written
    run("done", ctx)
    assert len(execution_report.load_latest(state_dir)["tasks"]) == 2


def test_a_second_stage_extends_the_same_report(empty_registry, make_ctx, tmp_path):
    points.register("alpha", "plan", ok("alpha"))
    points.register("omega", "done", ok("omega"))
    ctx = make_ctx(issue={"number": 7}, run_dir=tmp_path / "r" / "points-demo-7", state_dir=tmp_path / "state")
    run("plan", ctx)
    run("done", ctx)
    report = execution_report.load_latest(tmp_path / "state")
    assert [t["task_id"] for t in report["tasks"]] == ["plan:alpha", "done:omega"]
    assert report["status"] == "COMPLETE"


def test_emission_failure_never_breaks_the_stage(empty_registry, make_ctx, tmp_path):
    points.register("alpha", "plan", ok("alpha"))
    blocker = tmp_path / "file"
    blocker.write_text("x")
    [result] = run("plan", make_ctx(run_dir=blocker / "under", state_dir=blocker / "state", issue={"number": 1}))
    assert result.status == "ok"
