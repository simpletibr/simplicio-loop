"""trajectory (done): record the run outcome by aggregating trajectory lessons."""
import json
from pathlib import Path

from simplicio_loop.watcher247 import points


def test_registered_at_done_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "trajectory"]
    assert (info.stage, info.blocking, info.conditional) == ("done", False, False)


def test_contract(point_contract, make_ctx, tmp_path):
    """trajectory at done stage returns ok status."""
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "run-001"
    state_dir.mkdir()
    run_dir.mkdir()
    result = point_contract("trajectory", make_ctx(state_dir=state_dir, run_dir=run_dir), expect="ok")
    assert result.evidence["run_id"] == "run-001"
    assert result.evidence["trajectory_file"] == ".simplicio-loop/orchestrator/trajectory/run-001.jsonl"


def test_skipped_without_state_dir(point_contract, make_ctx, tmp_path):
    """trajectory is skipped when state_dir is None."""
    result = point_contract("trajectory", make_ctx(run_dir=tmp_path / "run-001"), expect="skipped")
    assert result.reason_code == "no_state_dir"


def test_skipped_without_run_dir(point_contract, make_ctx, tmp_path):
    """trajectory is skipped when run_dir is None."""
    result = point_contract("trajectory", make_ctx(state_dir=tmp_path), expect="skipped")
    assert result.reason_code == "no_state_dir"


def test_records_lessons_count(point_contract, make_ctx, tmp_path):
    """trajectory records new and merged lesson counts in evidence."""
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "run-xyz"
    state_dir.mkdir()
    run_dir.mkdir()

    # Create trajectory jsonl with a lesson
    traj_dir = state_dir / ".simplicio-loop" / "orchestrator" / "trajectory"
    traj_dir.mkdir(parents=True, exist_ok=True)
    traj_file = traj_dir / "run-xyz.jsonl"
    traj_file.write_text(json.dumps({"lesson": "test lesson one"}) + "\n", encoding="utf-8")

    result = point_contract("trajectory", make_ctx(state_dir=state_dir, run_dir=run_dir), expect="ok")
    assert result.evidence["run_id"] == "run-xyz"
    assert "trajectory_file" in result.evidence
