from __future__ import annotations

import json

from simplicio_loop import cli
from simplicio_loop.checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from simplicio_loop.fast_fanout import FastFanoutCoordinator
from simplicio_loop.fast_integration import FAST_CHANGESET_SCHEMA


class FakeFast:
    def __init__(self, lifecycle=None):
        self.applied = []
        self.lifecycle = lifecycle

    def prepare(self, task):
        return {
            "status": "READY",
            "generation": "generation-1",
            "context_hash": "context-1",
            "plan_hash": "plan-1",
        }

    def apply(self, changeset, *, winner, generation, context_hash):
        if self.lifecycle is not None:
            assert self.lifecycle.fence_path.exists(), "apply happened before winner fence"
        self.applied.append((winner, generation, context_hash))
        return {"status": "READY"}


def changeset():
    return {
        "schema": FAST_CHANGESET_SCHEMA,
        "changes": [{
            "path": "app.py",
            "expected_sha256": "a" * 64,
            "replacements": [{"start_line": 1, "end_line": 1, "content": "x"}],
        }],
        "generation": "generation-1",
        "context_hash": "context-1",
    }


def test_fast_fanout_uses_durable_overlays_fence_and_cancellation(tmp_path):
    lifecycle = CheckpointLifecycle(
        tmp_path / ".simplicio-loop" / "loop-runs",
        task_id="task",
        attempt_id="attempt",
        source_commit="commit",
        fast_generation="generation-1",
        base_path=tmp_path,
    )
    fast = FakeFast(lifecycle)
    coordinator = FastFanoutCoordinator(tmp_path, integration=fast, lifecycle=lifecycle)
    coordinator.prepare("task")
    left = coordinator.acquire_slot("left", overlay_tree_hash="tree-left")
    right = coordinator.acquire_slot("right", overlay_tree_hash="tree-right")
    assert left["overlay_path"] != right["overlay_path"]
    coordinator.record_candidate("left", "candidate-b", changeset(), verified=False)
    coordinator.record_candidate("right", "candidate-a", changeset(), verified=True)

    result = coordinator.promote_winner()

    assert result["status"] == "PROMOTED"
    assert result["checkpoint_lifecycle"]["status"] == "SEALED"
    assert result["checkpoint_lifecycle"]["fence"]["winner_id"] == "candidate-a"
    assert result["checkpoint_lifecycle"]["fence"]["winner_id"] == result["winner"]
    assert fast.applied == [(True, "generation-1", "context-1")]
    assert coordinator.snapshot()["slots"][0]["state"] == "released"
    assert lifecycle.load("candidate-a", "candidate")["state"] == "READY_TO_PROMOTE"
    assert (lifecycle.cancellations / "candidate-b.json").exists()


def test_lifecycle_failure_blocks_before_any_fast_apply(tmp_path, monkeypatch):
    lifecycle = CheckpointLifecycle(
        tmp_path / ".simplicio-loop" / "loop-runs",
        task_id="task",
        attempt_id="attempt",
        source_commit="commit",
        fast_generation="generation-1",
        base_path=tmp_path,
    )
    fast = FakeFast()
    coordinator = FastFanoutCoordinator(tmp_path, integration=fast, lifecycle=lifecycle)
    coordinator.prepare("task")
    coordinator.acquire_slot("slot", overlay_tree_hash="tree")
    coordinator.record_candidate("slot", "candidate", changeset(), verified=True)
    monkeypatch.setattr(
        lifecycle,
        "converge_selected",
        lambda **kwargs: (_ for _ in ()).throw(LifecycleError("fence unavailable")),
    )

    result = coordinator.promote_winner()

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "checkpoint_lifecycle_failed"
    assert result["apply"] is None
    assert fast.applied == []


def test_checkpoint_cli_inspect_cancel_and_gc(tmp_path, capsys):
    lifecycle = CheckpointLifecycle(
        tmp_path / ".simplicio-loop" / "loop-runs",
        task_id="task",
        attempt_id="attempt",
        source_commit="commit",
        fast_generation="generation",
        base_path=tmp_path,
    )
    lifecycle.checkpoint("candidate", "candidate", "READY_TO_PROMOTE")
    common = [
        "--repo", str(tmp_path),
        "--task-id", "task",
        "--attempt-id", "attempt",
        "--source-commit", "commit",
        "--fast-generation", "generation",
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
