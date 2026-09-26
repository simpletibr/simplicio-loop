from __future__ import annotations

import sqlite3

import pytest

from simplicio_loop.local_task_queue import LocalTaskQueue
from simplicio_loop.remote_queue import QueueConflict


def test_local_task_queue_uses_mapper_operations_and_replays_outcomes(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    queue.submit("b", depends_on=["a"])
    with pytest.raises(QueueConflict, match="dependencies"):
        queue.claim_local("b", "worker", idempotency_key="b-1")

    lease = queue.claim_local("a", "worker", idempotency_key="a-1")
    intent = queue.persist_intent(lease, {"effect": "write"})
    assert intent["digest"].startswith("sha256:")
    receipt = queue.record_outcome(lease, "verified_success", receipt={"proof": "ok"})
    assert receipt["digest"].startswith("sha256:")

    restarted = LocalTaskQueue(tmp_path)
    assert restarted.path.endswith(".simplicio-loop/data/operations.sqlite")
    assert not (tmp_path / ".simplicio-loop/orchestrator/queue.sqlite3").exists()
    assert restarted.inspect_local("a")["outcome"]["outcome"] == "verified_success"
    assert restarted.claim_local("b", "worker-2", idempotency_key="b-2").task_id == "b"
    replay = restarted._operations.replay(restarted._journal_id)
    assert replay["valid"] is True
    assert replay["events"][-1]["event_type"] == "local-task.snapshot"
    with sqlite3.connect(restarted.path) as database:
        tables = {row[0] for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert not {"local_meta", "local_dependencies", "local_outcomes", "local_transitions"} & tables
