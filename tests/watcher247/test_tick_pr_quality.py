"""The PR-quality points (judge, delivery_gate) in the real tick: an empty diff stays done_no_diff (#1509)."""
import json

from simplicio_loop.watcher247 import config

from .fakes import FakeRun, baseline, issue, read_json, run_tick
from simplicio_loop.watcher247.worktrees import state_home


def point_statuses(name_repo, number):
    # State is now in state_home(repo, number)/.simplicio-loop/...
    events = (state_home(name_repo, number) / ".simplicio-loop" / "orchestrator" / "points" / f"{name_repo}-{number}"
              / "events.jsonl")
    payloads = [json.loads(line).get("payload") or {} for line in events.read_text().splitlines()]
    return {p["point"]: (p["status"], p.get("reason_code")) for p in payloads if "point" in p}


def test_empty_diff_ends_done_no_diff_and_judge_and_gate_are_skipped(env):
    fake = env(FakeRun({"simplicio-a": [issue(4)]}, diff=False))
    baseline()
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#4"]
    assert claim["status"] == "done_no_diff" and claim["pr"] is None
    assert "sem diff" in fake.marker_comments(4)[-1]["body"]
    seen = point_statuses("simplicio-a", 4)
    assert seen["judge"] == ("skipped", "no_diff")
    assert seen["delivery_gate"] == ("skipped", "no_diff")


def test_a_diff_is_judged_and_gated_in_the_tick(env):
    env(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert read_json(config.CLAIMS)["simplicio-a#5"]["status"] == "done"
    seen = point_statuses("simplicio-a", 5)
    assert seen["judge"][0] == "ok" and seen["delivery_gate"][0] == "ok"
