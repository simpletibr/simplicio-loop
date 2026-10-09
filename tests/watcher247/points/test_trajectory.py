"""trajectory (done): writes the run outcome to orchestrator/trajectory/<run_id>.jsonl, the file `learn` reads.

Every context here comes from the real tick (`done_ctx`), never a hand-made turbo dict.
"""
import json
from dataclasses import replace

import pytest

from simplicio_loop.watcher247 import points

from .tick_ctx import capture_done_ctx

PR_URL = "https://github.com/simpletibr/simplicio-a/pull/9"
LABEL = "UNVERIFIED|no_test_command"
TRAJECTORY = ".simplicio-loop/orchestrator/trajectory/simplicio-a-7.jsonl"
# The dict host_mode.run_exec returns (the default executor); the tick's openrouter path returns the first three keys.
EXEC_TURBO = {
    "turbo_status": "ok", "exit_code": 0, "verify": "MEASURED|verify_passed: `pytest -q`", "executor": "exec",
    "steps": [
        {"role": "plan", "family": "codex", "model": "gpt-5", "effort": "low", "outcome": "failed"},
        {"role": "fix", "family": "claude", "model": "opus", "effort": "high", "outcome": "ok"},
    ],
}


@pytest.fixture
def done_ctx(env, monkeypatch):
    return capture_done_ctx(env, monkeypatch)


def records(ctx):
    path = ctx.state_dir / TRAJECTORY
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_registered_at_done_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "trajectory"]
    assert (info.stage, info.blocking, info.conditional) == ("done", False, False)


def test_the_tick_context_carries_turbo_status_not_status(done_ctx):
    assert done_ctx.turbo_json == {"turbo_status": "ok", "exit_code": 0, "verify": LABEL}
    assert done_ctx.verify == LABEL and done_ctx.pr_url == PR_URL


def test_records_the_real_outcome_of_the_tick_run(point_contract, done_ctx):
    result = point_contract("trajectory", done_ctx, expect="ok")
    assert result.evidence == {"run_id": "simplicio-a-7", "trajectory_file": TRAJECTORY, "status": "ok",
                               "lesson": f"simplicio-a: solved via turbo executor; verified by {LABEL}"}
    assert records(done_ctx) == [{
        "run_id": "simplicio-a-7", "issue": 7, "status": "ok", "verify": LABEL, "executor": None, "steps": [],
        "attempts": 1, "role": None, "family": None, "pr_url": PR_URL,
        "lesson": f"simplicio-a: solved via turbo executor; verified by {LABEL}"}]


def test_records_the_steps_of_an_exec_run(point_contract, done_ctx):
    ctx = replace(done_ctx, turbo_json=EXEC_TURBO, verify=EXEC_TURBO["verify"], family="codex")
    point_contract("trajectory", ctx, expect="ok")
    [record] = records(ctx)
    assert (record["executor"], record["attempts"], record["family"]) == ("exec", 2, "codex")
    assert record["steps"] == EXEC_TURBO["steps"]
    assert record["lesson"] == "simplicio-a: solved via exec executor (claude/opus, codex/gpt-5); verified by MEASURED|verify_passed: `pytest -q`"


def test_a_failed_run_is_recorded_without_a_lesson(point_contract, done_ctx):
    ctx = replace(done_ctx, turbo_json={"turbo_status": "failed", "exit_code": 1, "verify": LABEL})
    point_contract("trajectory", ctx, expect="ok")
    [record] = records(ctx)
    assert record["status"] == "failed" and "lesson" not in record


def test_the_same_run_id_is_replaced_not_appended(point_contract, done_ctx):
    point_contract("trajectory", done_ctx, expect="ok")
    point_contract("trajectory", done_ctx, expect="ok")
    assert len(records(done_ctx)) == 1


def test_skipped_without_state_dir(point_contract, make_ctx, tmp_path):
    result = point_contract("trajectory", make_ctx(run_dir=tmp_path / "run-001"), expect="skipped")
    assert result.reason_code == "no_state_dir"


def test_skipped_without_run_dir(point_contract, make_ctx, tmp_path):
    result = point_contract("trajectory", make_ctx(state_dir=tmp_path), expect="skipped")
    assert result.reason_code == "no_state_dir"
