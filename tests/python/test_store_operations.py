"""State-machine and contract tests for MapperStore operational primitives (#477)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from simplicio_mapper.contract import validate_instance
from simplicio_mapper.store import OperationsStore, OperationsStoreError


def _schema(name: str) -> dict:
    root = Path(__file__).parents[2] / "contracts/mapper-store/v1/schemas"
    return json.loads((root / name).read_text(encoding="utf-8"))


def _store(tmp_path: Path) -> OperationsStore:
    store = OperationsStore(tmp_path / "operations.sqlite")
    store.initialize()
    return store


def _claim(store: OperationsStore, task_id: str = "task") -> dict:
    store.enqueue(task_id, {"task": task_id}, idempotency_key=f"key:{task_id}")
    claimed = store.claim("worker")
    assert claimed is not None
    return claimed


def test_initialize_capabilities_and_status_contract(tmp_path: Path) -> None:
    store = _store(tmp_path)
    status = store.status()
    assert status["counts"] == {"queued": 0, "running": 0, "completed": 0, "cancelled": 0, "failed": 0}
    assert validate_instance(status, _schema("operations-status.schema.json")) == []
    assert store.capabilities()["capabilities"]["fencing"] is True


def test_enqueue_is_idempotent_and_conflict_is_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.enqueue("task", {"x": 1}, idempotency_key="same")
    second = store.enqueue("task", {"x": 1}, idempotency_key="same")
    assert first["status"] == "queued"
    assert second["status"] == "unchanged"
    with pytest.raises(OperationsStoreError, match="IDEMPOTENCY_CONFLICT"):
        store.enqueue("other", {"x": 2}, idempotency_key="same")


def test_claim_capacity_and_release_requeues_without_duplicate_active_lease(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue("one", {"n": 1}, idempotency_key="one")
    store.enqueue("two", {"n": 2}, idempotency_key="two")
    first = store.claim("worker")
    assert first is not None
    assert validate_instance(first, _schema("operations-claim.schema.json")) == []
    with pytest.raises(OperationsStoreError, match="SLOT_CAPACITY"):
        store.claim("other")
    store.release(first["attempt_id"], first["fence_token"])
    second = store.claim("other")
    assert second is not None
    assert second["task_id"] == "one"


def test_stale_fence_cannot_heartbeat_complete_or_write_checkpoint(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    store.release(claimed["attempt_id"], claimed["fence_token"])
    with pytest.raises(OperationsStoreError, match="STALE_FENCE|LEASE_NOT_ACTIVE"):
        store.heartbeat(claimed["attempt_id"], claimed["fence_token"])
    with pytest.raises(OperationsStoreError, match="STALE_FENCE|LEASE_NOT_ACTIVE"):
        store.complete(claimed["attempt_id"], claimed["fence_token"])
    with pytest.raises(OperationsStoreError, match="STALE_FENCE|LEASE_NOT_ACTIVE"):
        store.checkpoint(claimed["attempt_id"], claimed["fence_token"], 1, {"x": 1})


def test_expired_lease_is_reclaimed_and_old_worker_is_fenced(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    time.sleep(0.02)
    store.heartbeat(claimed["attempt_id"], claimed["fence_token"], lease_seconds=0.001)
    time.sleep(0.02)
    assert store.reclaim_expired()["recovered"] == 1
    with pytest.raises(OperationsStoreError, match="LEASE_EXPIRED|LEASE_NOT_ACTIVE"):
        store.heartbeat(claimed["attempt_id"], claimed["fence_token"])
    replacement = store.claim("replacement")
    assert replacement is not None
    assert replacement["task_id"] == "task"
    assert replacement["fence_token"] != claimed["fence_token"]


def test_terminal_verified_task_is_never_redispatched(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    result = store.complete(claimed["attempt_id"], claimed["fence_token"], receipt={"verified": True})
    assert result["terminal_verified"] is True
    assert store.claim("worker") is None
    assert store.status("task")["terminal_verified"] is True
    assert validate_instance(store.status("task"), _schema("operations-task.schema.json")) == []


def test_cancel_queued_and_running_task_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue("queued", {}, idempotency_key="queued")
    assert store.cancel("queued")["state"] == "cancelled"
    assert store.cancel("queued")["status"] == "unchanged"
    running = _claim(store, "running")
    cancelled = store.cancel("running")
    assert cancelled["state"] == "running"
    assert store.status("running")["cancellation_requested"] is True
    store.complete(running["attempt_id"], running["fence_token"], status="failed")


def test_cancelled_running_task_is_not_requeued_after_expiry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    running = _claim(store)
    store.cancel("task")
    store.heartbeat(running["attempt_id"], running["fence_token"], lease_seconds=0.001)
    time.sleep(0.01)
    store.reclaim_expired()
    assert store.status("task")["state"] == "cancelled"
    assert store.claim("worker") is None


def test_checkpoint_and_effect_ledger_require_explicit_reconciliation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    assert (
        store.checkpoint(claimed["attempt_id"], claimed["fence_token"], 3, {"cursor": "x"})["status"]
        == "checkpointed"
    )
    prepared = store.prepare_effect(
        claimed["attempt_id"], claimed["fence_token"], "effect", "effect-key", {"action": "write"}
    )
    assert prepared["state"] == "prepared"
    assert validate_instance({**prepared}, _schema("operations-effect.schema.json")) == []
    with pytest.raises(OperationsStoreError, match="EFFECT_RECONCILIATION_PENDING"):
        store.complete(claimed["attempt_id"], claimed["fence_token"], receipt={"verified": True})
    assert (
        store.mark_effect_unknown("effect", claimed["attempt_id"], claimed["fence_token"])["state"]
        == "unknown"
    )
    with pytest.raises(OperationsStoreError, match="RECONCILIATION_INVALID"):
        store.reconcile_effect(
            "effect", claimed["attempt_id"], claimed["fence_token"], outcome="success", receipt={}
        )
    reconciled = store.reconcile_effect(
        "effect",
        claimed["attempt_id"],
        claimed["fence_token"],
        outcome="committed",
        receipt={"remote_id": "r1"},
    )
    assert reconciled["state"] == "reconciled"
    with pytest.raises(OperationsStoreError, match="RECONCILIATION_REQUIRED"):
        store.commit_effect("effect", claimed["attempt_id"], claimed["fence_token"], {"late": True})
    with pytest.raises(OperationsStoreError, match="EFFECT_STATE_INVALID"):
        store.mark_effect_unknown("effect", claimed["attempt_id"], claimed["fence_token"])
    with pytest.raises(OperationsStoreError, match="EFFECT_NOT_FOUND"):
        store.mark_effect_unknown("missing-effect", claimed["attempt_id"], claimed["fence_token"])


def test_effect_prepare_and_commit_are_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    first = store.prepare_effect(claimed["attempt_id"], claimed["fence_token"], "effect", "key", {"x": 1})
    second = store.prepare_effect(claimed["attempt_id"], claimed["fence_token"], "effect", "key", {"x": 1})
    assert first["status"] == "prepared"
    assert second["status"] == "unchanged"
    assert (
        store.commit_effect("effect", claimed["attempt_id"], claimed["fence_token"], {"receipt": "ok"})[
            "state"
        ]
        == "committed"
    )
    assert (
        store.commit_effect("effect", claimed["attempt_id"], claimed["fence_token"], {"receipt": "ok"})[
            "status"
        ]
        == "unchanged"
    )
    with pytest.raises(OperationsStoreError, match="EFFECT_IDEMPOTENCY_CONFLICT"):
        store.commit_effect("effect", claimed["attempt_id"], claimed["fence_token"], {"receipt": "changed"})
    with pytest.raises(OperationsStoreError, match="RECEIPT_REQUIRED"):
        store.complete(claimed["attempt_id"], claimed["fence_token"])
    with pytest.raises(OperationsStoreError, match="IDEMPOTENCY_CONFLICT"):
        store.prepare_effect(claimed["attempt_id"], claimed["fence_token"], "other", "key", {"x": 2})
    with pytest.raises(OperationsStoreError, match="EFFECT_IDENTITY_INVALID"):
        store.prepare_effect(claimed["attempt_id"], claimed["fence_token"], "", "", {})


def test_hash_chained_journal_replay_conflict_tamper_and_compaction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.append_event("run", "started", {"n": 1}, expected_seq=0)
    assert validate_instance(first, _schema("operations-journal.schema.json")) == []
    second = store.append_event("run", "progress", {"n": 2}, expected_seq=1)
    assert second["seq"] == 2
    with pytest.raises(OperationsStoreError, match="JOURNAL_CONFLICT"):
        store.append_event("run", "bad", {}, expected_seq=0)
    replay = store.replay("run")
    assert replay["valid"] is True
    assert validate_instance(replay, _schema("operations-replay.schema.json")) == []
    compacted = store.compact("run", 1, {"last": 1})
    assert validate_instance(compacted, _schema("operations-compaction.schema.json")) == []
    assert compacted["events_retained"] == 1
    assert store.replay("run")["compaction"]["through_seq"] == 1
    with sqlite3.connect(tmp_path / "operations.sqlite") as connection:
        connection.execute("UPDATE ops_events SET event_hash='tampered' WHERE run_id='run' AND seq=2")
    with pytest.raises(OperationsStoreError, match="JOURNAL_TAMPERED"):
        store.replay("run")
    assert first["event_hash"] != second["event_hash"]


def test_payload_and_identity_limits_are_typed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(OperationsStoreError, match="TASK_IDENTITY_INVALID"):
        store.enqueue("", {}, idempotency_key="x")
    with pytest.raises(OperationsStoreError, match="PAYLOAD_LIMIT"):
        store.enqueue("big", {"x": "a" * 200_001}, idempotency_key="big")
    with pytest.raises(OperationsStoreError, match="SLOT_INVALID"):
        store.register_slot("", 1)
    with pytest.raises(OperationsStoreError, match="SLOT_INVALID"):
        store.register_slot("bad", 0)
    assert store.register_slot("extra", 2)["status"] == "registered"
    with pytest.raises(OperationsStoreError, match="PAYLOAD_INVALID"):
        store.enqueue("bad-payload", {"x": {1, 2}}, idempotency_key="bad-payload")
    with pytest.raises(OperationsStoreError, match="PAYLOAD_INVALID"):
        store.enqueue("nan-payload", {"n": float("nan")}, idempotency_key="nan-payload")
    with pytest.raises(OperationsStoreError, match="CLAIM_INVALID"):
        store.claim("")
    with pytest.raises(OperationsStoreError, match="CLAIM_INVALID"):
        store.claim(None)  # type: ignore[arg-type]
    with pytest.raises(OperationsStoreError, match="CLAIM_INVALID"):
        store.claim("worker", lease_seconds=0)
    with pytest.raises(OperationsStoreError, match="SLOT_NOT_FOUND"):
        store.claim("worker", slot_id="missing")
    with pytest.raises(OperationsStoreError, match="HEARTBEAT_INVALID"):
        store.heartbeat("missing", "fence", lease_seconds=0)
    with pytest.raises(OperationsStoreError, match="TERMINAL_STATE_INVALID"):
        store.complete("missing", "fence", status="done")
    with pytest.raises(OperationsStoreError, match="CHECKPOINT_INVALID"):
        store.checkpoint("missing", "fence", -1, {})
    with pytest.raises(OperationsStoreError, match="TASK_NOT_FOUND"):
        store.cancel("missing")
    with pytest.raises(OperationsStoreError, match="EVENT_INVALID"):
        store.append_event("", "event", {})
    with pytest.raises(OperationsStoreError, match="COMPACTION_INVALID"):
        store.compact("run", 0, {})
    with pytest.raises(OperationsStoreError, match="COMPACTION_BOUNDARY_MISSING"):
        store.compact("run", 1, {})
    with pytest.raises(OperationsStoreError, match="TASK_NOT_FOUND"):
        store.status("missing")


def test_missing_store_in_read_only_mode_fails_without_creation(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite"
    with pytest.raises(OperationsStoreError, match="STORE_READ_ONLY"):
        OperationsStore(database, auto_create=False).initialize()
    with pytest.raises(OperationsStoreError, match="STORE_NOT_INITIALIZED"):
        OperationsStore(database, auto_create=False).enqueue("x", {}, idempotency_key="x")
    with pytest.raises(OperationsStoreError, match="STORE_NOT_INITIALIZED"):
        OperationsStore(database).status()
    with pytest.raises(OperationsStoreError, match="STORE_NOT_INITIALIZED"):
        OperationsStore(database).replay("run")
    assert not database.exists()

    sqlite3.connect(database).close()
    with pytest.raises(OperationsStoreError, match="STORE_NOT_INITIALIZED"):
        OperationsStore(database, auto_create=False).enqueue("x", {}, idempotency_key="x")


def test_expired_and_out_of_order_journal_states_have_reason_codes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    time.sleep(0.01)
    store.heartbeat(claimed["attempt_id"], claimed["fence_token"], lease_seconds=0.001)
    time.sleep(0.01)
    with pytest.raises(OperationsStoreError, match="LEASE_EXPIRED"):
        store.heartbeat(claimed["attempt_id"], claimed["fence_token"])
    store.reclaim_expired()
    store.append_event("out-of-order", "one", {})
    with sqlite3.connect(tmp_path / "operations.sqlite") as connection:
        connection.execute("UPDATE ops_events SET seq=3 WHERE run_id='out-of-order'")
    with pytest.raises(OperationsStoreError, match="JOURNAL_OUT_OF_ORDER"):
        store.replay("out-of-order")
    with pytest.raises(OperationsStoreError, match="EVENT_INVALID"):
        store.replay("")


def test_schema_and_fence_validation_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "invalid.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE operations_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO operations_meta(key, value) VALUES ('schema', 'wrong')")
    with pytest.raises(OperationsStoreError, match="OPERATIONS_SCHEMA_INVALID"):
        OperationsStore(database, auto_create=False).enqueue("x", {}, idempotency_key="x")
    with pytest.raises(OperationsStoreError, match="OPERATIONS_SCHEMA_INVALID"):
        OperationsStore(database).initialize()
    with pytest.raises(OperationsStoreError, match="OPERATIONS_SCHEMA_INVALID"):
        OperationsStore(database).status()

    store = _store(tmp_path / "fence")
    claimed = _claim(store)
    with pytest.raises(OperationsStoreError, match="STALE_FENCE"):
        store.heartbeat(claimed["attempt_id"], "wrong-fence")

    partial = tmp_path / "partial.sqlite"
    with sqlite3.connect(partial) as connection:
        connection.execute("CREATE TABLE operations_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO operations_meta(key, value) VALUES ('schema', ?)",
            ("simplicio.mapper-store.operations/v1",),
        )
    with pytest.raises(OperationsStoreError, match="STORE_NOT_INITIALIZED"):
        OperationsStore(partial).replay("run")


def test_unknown_effect_can_be_reconciled_by_explicit_recovery_authority(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    store.prepare_effect(claimed["attempt_id"], claimed["fence_token"], "effect", "key", {"x": 1})
    store.mark_effect_unknown("effect", claimed["attempt_id"], claimed["fence_token"])
    store.heartbeat(claimed["attempt_id"], claimed["fence_token"], lease_seconds=0.001)
    time.sleep(0.01)
    store.reclaim_expired()
    with pytest.raises(OperationsStoreError, match="STALE_FENCE|LEASE_NOT_ACTIVE"):
        store.reconcile_effect(
            "effect",
            claimed["attempt_id"],
            claimed["fence_token"],
            outcome="committed",
            receipt={"stale": True},
        )
    result = store.reconcile_effect(
        "effect", claimed["attempt_id"], None, outcome="committed", receipt={"remote": "confirmed"}
    )
    assert result["state"] == "reconciled"


def test_compaction_snapshot_tampering_is_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_event("run", "started", {})
    store.compact("run", 1, {"projection": "real"})
    with sqlite3.connect(tmp_path / "operations.sqlite") as connection:
        connection.execute(
            "UPDATE ops_compactions SET snapshot_json=? WHERE run_id='run'",
            ('{"projection":"fake"}',),
        )
    with pytest.raises(OperationsStoreError, match="JOURNAL_TAMPERED"):
        store.replay("run")


def test_checkpoint_cursor_never_regresses(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claimed = _claim(store)
    store.checkpoint(claimed["attempt_id"], claimed["fence_token"], 10, {"cursor": 10})
    with pytest.raises(OperationsStoreError, match="CHECKPOINT_REGRESSION"):
        store.checkpoint(claimed["attempt_id"], claimed["fence_token"], 3, {"cursor": 3})


def test_replacement_attempt_adopts_prepared_effect_by_task_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = _claim(store)
    store.prepare_effect(old["attempt_id"], old["fence_token"], "effect", "key", {"x": 1})
    store.heartbeat(old["attempt_id"], old["fence_token"], lease_seconds=0.001)
    time.sleep(0.01)
    store.reclaim_expired()
    replacement = store.claim("replacement")
    assert replacement is not None
    adopted = store.prepare_effect(
        replacement["attempt_id"], replacement["fence_token"], "effect", "key", {"x": 1}
    )
    assert adopted["status"] == "adopted"
    assert (
        store.commit_effect(
            "effect", replacement["attempt_id"], replacement["fence_token"], {"receipt": "ok"}
        )["state"]
        == "committed"
    )


def test_operations_fixture_is_accepted(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).parents[2] / "contracts/mapper-store/v1/fixtures/operations/golden.json").read_text()
    )
    store = _store(tmp_path)
    result = store.enqueue(**fixture["request"])
    assert result == fixture["response"]
