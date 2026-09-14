from __future__ import annotations

import pytest

from simplicio_loop import runner as runner_mod
from simplicio_loop.mapper_operations import MapperOperationsAdapter
from simplicio_loop.remote_queue import QueueUnavailable


def test_mapper_claim_retries_a_failed_task_on_a_fresh_adapter(tmp_path, monkeypatch):
    database = tmp_path / "operations.sqlite"
    monkeypatch.setenv("SIMPLICIO_MAPPER_OPERATIONS_DB", str(database))

    operations = MapperOperationsAdapter(database, auto_create=True)
    operations.initialize()
    operations.register_slot("default", 1)

    first_operations, first_attempt = runner_mod._claim_mapper_operation_attempt(
        tmp_path,
        run_id="run-1",
        task_index=1,
        task_id="task-1",
        worker_id="worker-1",
        targets=["src/worker.py"],
    )
    failed = first_operations.complete(
        first_attempt.lease,
        status="failed",
        receipt={"status": "failed", "reason": "test failure"},
    )
    assert failed["status"] == "failed"
    assert operations.status("task-1")["state"] == "failed"

    _, retry_attempt = runner_mod._claim_mapper_operation_attempt(
        tmp_path,
        run_id="run-1",
        task_index=1,
        task_id="task-1",
        worker_id="worker-1",
        targets=["src/worker.py"],
    )

    assert retry_attempt.lease.task_id == "task-1"
    assert retry_attempt.lease.attempt_id != first_attempt.lease.attempt_id
    assert operations.status("task-1")["state"] == "running"


def test_mapper_claim_never_requeues_a_completed_task(tmp_path, monkeypatch):
    database = tmp_path / "operations.sqlite"
    monkeypatch.setenv("SIMPLICIO_MAPPER_OPERATIONS_DB", str(database))

    operations = MapperOperationsAdapter(database, auto_create=True)
    operations.initialize()
    operations.register_slot("default", 1)

    first_operations, first_attempt = runner_mod._claim_mapper_operation_attempt(
        tmp_path,
        run_id="run-1",
        task_index=1,
        task_id="task-1",
        worker_id="worker-1",
        targets=["src/worker.py"],
    )
    completed = first_operations.complete(
        first_attempt.lease,
        status="completed",
        receipt={"status": "completed", "proof": "verified"},
    )
    assert completed["status"] == "completed"
    assert operations.status("task-1")["state"] == "completed"

    with pytest.raises(QueueUnavailable, match="returned no lease"):
        runner_mod._claim_mapper_operation_attempt(
            tmp_path,
            run_id="run-1",
            task_index=1,
            task_id="task-1",
            worker_id="worker-1",
            targets=["src/worker.py"],
        )

    assert operations.status("task-1")["state"] == "completed"
