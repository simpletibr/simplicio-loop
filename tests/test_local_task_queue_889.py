from __future__ import annotations

import json
import sqlite3
import subprocess

import pytest

from simplicio_loop.local_task_queue import (
    EVENT_SCHEMA,
    JOURNAL_PREFIX,
    LEGACY_SCHEMA,
    SCHEMA,
    LocalTaskQueue,
)
from simplicio_loop.local_task_queue_cli import cli_main
from simplicio_loop.remote_queue import QueueConflict, QueueUnavailable


def test_fencing_restart_dependencies_and_verified_completion(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    queue.submit("b", depends_on=["a"])
    with pytest.raises(QueueConflict, match="dependencies"):
        queue.claim_local("b", "w", idempotency_key="b1")
    lease = queue.claim_local("a", "w", idempotency_key="a1", ttl=30)
    queue.persist_intent(lease, {"effect": "write"})
    queue.record_outcome(lease, "verified_success", receipt={"proof": "ok"})
    restarted = LocalTaskQueue(tmp_path)
    assert restarted.inspect_local("a")["outcome"]["outcome"] == "verified_success"
    second = restarted.claim_local("b", "w2", idempotency_key="b2")
    assert isinstance(second.fencing_token, str) and second.fencing_token


def test_stop_prevents_claim_and_requests_active_cancellation(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    queue.claim_local("a", "w", idempotency_key="a1")
    queue.submit("b")
    queue.stop()
    with pytest.raises(QueueConflict, match="stopped"):
        queue.submit("after-stop")
    with pytest.raises((KeyError, QueueUnavailable)):
        queue.task("after-stop")
    with pytest.raises(QueueConflict, match="stopped"):
        queue.claim_local("b", "w", idempotency_key="b1")
    assert queue.task("a")["cancellation_requested"] == 1
    queue.resume()
    assert queue.claim_local("b", "w", idempotency_key="b1").task_id == "b"


def test_unknown_outcome_requires_reconciliation_and_retry_provenance(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    lease = queue.claim_local("a", "w", idempotency_key="a1")
    queue.record_outcome(lease, "unknown_outcome")
    with pytest.raises(QueueConflict, match="receipt"):
        queue.reconcile_unknown("a", verified=True)
    with pytest.raises(QueueConflict, match="provenance"):
        queue.reconcile_unknown("a", verified=False)
    queue.reconcile_unknown("a", verified=False, provenance={"idempotent": True})
    retry = queue.claim_local("a", "w2", idempotency_key="a2")
    with pytest.raises(QueueConflict, match="provenance"):
        queue.record_outcome(retry, "retryable_failure")


def test_receipts_history_doctor_and_mapper_migration_contract(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    lease = queue.claim_local("a", "w", idempotency_key="a1")
    receipt = queue.record_outcome(
        lease, "retryable_failure", provenance={"idempotent": True}
    )
    assert receipt["digest"].startswith("sha256:")
    assert len(queue.inspect_local("a")["transitions"]) == 3
    assert queue.doctor_local()["healthy"] is True
    migrated = queue.migrate(dry_run=False)
    assert migrated == {
        "schema": SCHEMA,
        "dry_run": False,
        "backup": None,
        "from_schema": SCHEMA,
        "migrated_records": 0,
        "migrated_provenance": 0,
    }
    assert queue.status_local()["journal_mode"] == "mapper-store"


def test_mapper_journal_unknown_event_fails_closed_in_doctor(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    replay = queue._operations.replay(JOURNAL_PREFIX + queue.path)
    queue._operations.append_event(
        JOURNAL_PREFIX + queue.path,
        "local-task.invalid",
        {"schema": EVENT_SCHEMA, "operation": "invalid", "state": {}},
        expected_seq=queue._last_seq(replay),
    )
    result = queue.doctor_local()
    assert result["healthy"] is False


def test_cancel_reclaim_drain_top_and_retention(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("queued")
    assert [item["task_id"] for item in queue.top()] == ["queued"]
    assert queue.cancel_local("queued")["status"] == "cancelled"
    queue.submit("active")
    queue.claim_local("active", "w", idempotency_key="active", ttl=30)
    assert queue.cancel_local("active")["status"] == "cancelling"
    assert queue.drain(timeout=0)["status"] == "cancelling"
    queue.resume()
    queue.submit("stale")
    queue.claim_local("stale", "w", idempotency_key="stale", ttl=0.01)
    assert queue.reclaim_stale(now=10**30) == ["active", "stale"]
    queue.submit("done")
    lease = queue.claim_local("done", "w", idempotency_key="done")
    queue.record_outcome(lease, "verified_success", receipt={"proof": True})
    with pytest.raises(QueueConflict, match="terminal"):
        queue.cancel_local("done")
    assert queue.task("done")["state"] == "completed"
    assert queue.gc_terminal()["eligible"] == ["done"]
    assert queue.gc_terminal(apply=True)["removed"] == ["done"]


def test_mapper_database_has_no_local_task_authority_tables(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    with sqlite3.connect(queue.path) as database:
        tables = {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert not {
        "local_meta", "local_dependencies", "local_outcomes", "local_transitions"
    } & tables


def test_json_cli_surface(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    for args in (
        ["--repo", str(tmp_path), "--route", "legacy", "status"],
        ["--repo", str(tmp_path), "--route", "legacy", "top", "--limit", "1"],
        ["--repo", str(tmp_path), "--route", "legacy", "inspect", "a"],
        ["--repo", str(tmp_path), "--route", "legacy", "cancel", "a"],
        ["--repo", str(tmp_path), "--route", "legacy", "drain", "--timeout", "0"],
        ["--repo", str(tmp_path), "--route", "legacy", "resume"],
        ["--repo", str(tmp_path), "--route", "legacy", "doctor"],
        ["--repo", str(tmp_path), "--route", "legacy", "reclaim"],
        ["--repo", str(tmp_path), "--route", "legacy", "gc"],
    ):
        assert cli_main(args) == 0
        assert capsys.readouterr().out.strip().startswith(("{", "["))


def test_cli_terminal_conflict_is_stable_json(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    queue = LocalTaskQueue(tmp_path)
    queue.submit("done")
    lease = queue.claim_local("done", "w", idempotency_key="done")
    queue.record_outcome(lease, "verified_success", receipt={"proof": True})
    assert cli_main(["--repo", str(tmp_path), "--route", "legacy", "cancel", "done"]) == 3
    value = json.loads(capsys.readouterr().out)
    assert value == {
        "schema": "simplicio.loop.local-task-queue-error/v1",
        "status": "error",
        "code": "conflict",
        "reason": "terminal outcome is immutable",
    }


def test_stale_fence_cannot_write_intent_or_terminal_outcome(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    queue.submit("a")
    stale = queue.claim_local("a", "old", idempotency_key="old", ttl=0.01)
    queue.reclaim_stale(now=10**30)
    current = queue.claim_local("a", "new", idempotency_key="new")
    with pytest.raises(QueueConflict, match="(?i)stale|active|expired"):
        queue.persist_intent(stale, {"effect": "write"})
    with pytest.raises(QueueConflict, match="(?i)stale|active|expired"):
        queue.record_outcome(stale, "verified_success", receipt={"proof": "stale"})
    queue.record_outcome(current, "verified_success", receipt={"proof": "current"})
    assert queue.task("a")["state"] == "completed"


def test_cli_rejects_non_root_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    child = tmp_path / "child"
    child.mkdir()
    assert cli_main(["--repo", str(child), "status"]) == 2


def test_mapper_cli_route_does_not_construct_legacy_queue(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    calls = []

    class FakeOperations:
        def list_ready(self, *, limit):
            calls.append(("top", limit))
            return {"schema": "mapper", "tasks": []}

    class FakeMapperQueue:
        def __init__(self, database, *, auto_create):
            calls.append(("construct", database, auto_create))
            self.database = database
            self.operations = FakeOperations()

        def status(self, task_id=None):
            calls.append(("status", task_id))
            return {"schema": "mapper", "task_id": task_id}

        def capabilities(self):
            return {"schema": "mapper", "capabilities": {"fencing": True}}

    monkeypatch.setattr("simplicio_loop.local_task_queue_cli.MapperQueue", FakeMapperQueue)
    database = str(tmp_path / "operations.sqlite")
    assert cli_main([
        "--repo", str(tmp_path), "--route", "mapper", "--mapper-db", database, "status"
    ]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "mapper"
    assert calls == [("construct", database, False), ("status", None)]
    assert not (tmp_path / ".simplicio-loop/orchestrator/queue.sqlite3").exists()


def test_mapper_route_is_default_and_resolves_repo_scoped_store(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    calls = []

    class FakeOperations:
        def list_ready(self, *, limit):
            return {"schema": "mapper", "tasks": []}

    class FakeMapperQueue:
        def __init__(self, database, *, auto_create):
            calls.append((str(database), auto_create))
            self.database = database
            self.operations = FakeOperations()

        def status(self, task_id=None):
            return {"schema": "mapper", "task_id": task_id}

    monkeypatch.setattr("simplicio_loop.local_task_queue_cli.MapperQueue", FakeMapperQueue)
    assert cli_main(["--repo", str(tmp_path), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "mapper"
    assert calls == [(str(tmp_path / ".simplicio-loop/data/operations.sqlite"), False)]
    assert not (tmp_path / ".simplicio-loop/orchestrator/queue.sqlite3").exists()


def test_mapper_cli_rejects_legacy_only_actions(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert cli_main([
        "--repo", str(tmp_path), "--route", "mapper",
        "--mapper-db", str(tmp_path / "operations.sqlite"), "drain",
    ]) == 2
    value = json.loads(capsys.readouterr().out)
    assert value["code"] == "unavailable"
    assert "MAPPER_ROUTE_UNSUPPORTED" in value["reason"]


def test_benchmark_thresholds_are_enforced(monkeypatch, capsys):
    from bench import benchmark_local_task_queue_889 as benchmark

    assert benchmark.main([
        "--max-enqueue-us", "0", "--max-claim-us", "0", "--sizes", "1,10"
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["thresholds"] == {"claim": False, "enqueue": False}


def test_legacy_schema_constant_is_retained_only_for_external_migration(tmp_path):
    queue = LocalTaskQueue(tmp_path)
    assert LEGACY_SCHEMA != SCHEMA
    assert queue.migrate()["from_schema"] == SCHEMA
