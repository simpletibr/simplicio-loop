from __future__ import annotations

import json

from simplicio_loop import cli
from simplicio_loop.checkpoint_lifecycle import CheckpointLifecycle


def test_checkpoint_cli_inspect_cancel_and_gc(tmp_path, capsys):
    lifecycle = CheckpointLifecycle(
        tmp_path / ".simplicio-loop" / "loop-runs",
        task_id="task",
        attempt_id="attempt",
        source_commit="commit",
        mapper_generation="generation",
        base_path=tmp_path,
    )
    lifecycle.checkpoint("candidate", "candidate", "READY_TO_PROMOTE")
    common = [
        "--repo", str(tmp_path),
        "--task-id", "task",
        "--attempt-id", "attempt",
        "--source-commit", "commit",
        "--mapper-generation", "generation",
        "--base-path", str(tmp_path),
    ]
    assert cli.main(["checkpoint", "inspect", *common, "--candidate-id", "candidate"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "READY_TO_PROMOTE"
    assert cli.main([
        "checkpoint", "cancel", *common, "--candidate-id", "candidate", "--reason", "operator",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "CANCELLED"
    assert cli.main([
        "checkpoint", "gc", *common, "--retention-seconds", "0", "--apply",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] == ["candidate"]
