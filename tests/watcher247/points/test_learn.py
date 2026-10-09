"""learn (done): call the existing learn implementation to update precedents after a SOLVED run."""
import json
from pathlib import Path

from simplicio_loop.watcher247 import points


def test_registered_at_done_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "learn"]
    assert (info.stage, info.blocking, info.conditional) == ("done", False, True)


def test_contract_skipped_when_not_solved(point_contract, make_ctx, tmp_path):
    """learn is skipped when turbo_json status is not ok."""
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "run-001"
    state_dir.mkdir()
    run_dir.mkdir()
    
    # turbo_json with non-ok status
    result = point_contract(
        "learn",
        make_ctx(state_dir=state_dir, run_dir=run_dir, turbo_json={"status": "error"}),
        expect="skipped"
    )
    assert result.reason_code == "not_applicable"


def test_contract_runs_when_solved(point_contract, make_ctx, tmp_path):
    """learn applies and returns ok when turbo_json status is ok."""
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "run-002"
    state_dir.mkdir()
    run_dir.mkdir()
    
    # turbo_json with ok status
    result = point_contract(
        "learn",
        make_ctx(state_dir=state_dir, run_dir=run_dir, turbo_json={"status": "ok"}),
        expect="ok"
    )
    assert result.evidence["run_id"] is not None
    assert result.evidence["new_lessons"] >= 0
    assert result.evidence["merged_lessons"] >= 0
    assert "index_path" in result.evidence


def test_skipped_without_state_dir(point_contract, make_ctx, tmp_path):
    """learn is skipped when state_dir is None."""
    result = point_contract(
        "learn",
        make_ctx(state_dir=None, run_dir=tmp_path, turbo_json={"status": "ok"}),
        expect="skipped"
    )
    assert result.reason_code == "no_state_dir"


def test_records_lessons_from_solved_run(point_contract, make_ctx, tmp_path):
    """learn records new and merged lessons after a solved run."""
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "run-solved"
    state_dir.mkdir()
    run_dir.mkdir()

    # Create trajectory jsonl with lessons
    traj_dir = state_dir / ".simplicio-loop" / "orchestrator" / "trajectory"
    traj_dir.mkdir(parents=True, exist_ok=True)
    traj_file = traj_dir / "run-solved.jsonl"
    traj_file.write_text(
        json.dumps({"lesson": "learned to refactor efficiently"}) + "\n" +
        json.dumps({"lesson": "use type hints for clarity"}) + "\n",
        encoding="utf-8"
    )

    result = point_contract(
        "learn",
        make_ctx(state_dir=state_dir, run_dir=run_dir, turbo_json={"status": "ok"}),
        expect="ok"
    )
    assert result.evidence["new_lessons"] == 2
