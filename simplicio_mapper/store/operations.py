"""Durable MapperStore operations primitives with leases and fencing.

The operations namespace persists queue state, attempts, leases, slots, a
hash-chained journal, checkpoints, and effect intents.  It does not own DAG
planning or worker execution; callers retain that authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connection import StoreConnection, StoreError, WriterIdentity
from .locks import StoreFileLock
from .profiles import StoreProfile
from .transactions import transaction

OPERATIONS_SCHEMA = "simplicio.mapper-store.operations/v1"
OPERATIONS_API_SCHEMA = "simplicio.mapper-store.operations-api/v1"
_GENESIS = "GENESIS"
_MAX_JSON_CHARS = 200_000
_AGENT_SLOT_SCHEMA = "simplicio.mapper-store.agent-slots/v1"
_AGENT_SLOT_RECEIPT_SCHEMA = "simplicio.mapper-store.agent-slot-receipt/v1"
_AGENT_SLOT_STATES = ("pending", "running", "completed", "shutdown", "reclaimable")
_AGENT_SLOT_ACTIVE = frozenset(("pending", "running"))
_AGENT_SLOT_TERMINAL = frozenset(("completed", "shutdown"))


class OperationsStoreError(StoreError):
    """Typed operations-store failure with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clock() -> float:
    return datetime.now(timezone.utc).timestamp()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json_payload(value: Mapping[str, Any] | None, name: str) -> str:
    try:
        payload = _canonical(dict(value or {}))
    except (TypeError, ValueError) as error:
        raise OperationsStoreError("PAYLOAD_INVALID", name) from error
    if len(payload) > _MAX_JSON_CHARS:
        raise OperationsStoreError("PAYLOAD_LIMIT", name)
    return payload


class OperationsStore:
    """SQLite-backed operational primitives without worker/DAG ownership."""

    def __init__(
        self,
        database: str | Path,
        *,
        writer: WriterIdentity | None = None,
        auto_create: bool = True,
    ) -> None:
        self.database = Path(database).expanduser().absolute()
        self.writer = writer or WriterIdentity.create("simplicio_mapper.operations_store")
        self.auto_create = auto_create
        self.lock_path = self.database.with_name(self.database.name + ".operations.lock")

    def _open(self, *, read_only: bool = False) -> StoreConnection:
        if not self.auto_create and not self.database.is_file():
            raise OperationsStoreError("STORE_NOT_INITIALIZED")
        if read_only:
            return StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False)
        return StoreConnection.open(
            self.database,
            StoreProfile.read_write(create=self.auto_create),
            writer_identity=self.writer,
        )

    @contextmanager
    def _write_lock(self):
        with StoreFileLock(
            self.lock_path,
            owner=f"{self.writer.component}:{self.writer.instance_id}",
            blocking=True,
        ):
            yield

    def _ensure_schema(self, store: StoreConnection) -> None:
        with transaction(store, "EXCLUSIVE") as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS operations_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_tasks (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('queued','running','completed','cancelled','failed')),
                    priority INTEGER NOT NULL DEFAULT 0,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancellation_requested IN (0,1)),
                    terminal_verified INTEGER NOT NULL DEFAULT 0 CHECK(terminal_verified IN (0,1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES ops_tasks(task_id),
                    worker_id TEXT NOT NULL,
                    fence_token TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('running','released','expired','completed','failed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_leases (
                    lease_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL UNIQUE REFERENCES ops_attempts(attempt_id),
                    worker_id TEXT NOT NULL,
                    fence_token TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('active','released','expired','completed')),
                    heartbeat_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_slots (
                    slot_id TEXT PRIMARY KEY,
                    capacity INTEGER NOT NULL CHECK(capacity > 0),
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_agent_slots (
                    agent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','shutdown','reclaimable')),
                    attempt INTEGER NOT NULL CHECK(attempt > 0),
                    worktree TEXT,
                    lease_id TEXT,
                    descendants INTEGER NOT NULL CHECK(descendants >= 0),
                    worktree_active INTEGER NOT NULL CHECK(worktree_active IN (0,1)),
                    lease_active INTEGER NOT NULL CHECK(lease_active IN (0,1)),
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_checkpoints (
                    attempt_id TEXT PRIMARY KEY REFERENCES ops_attempts(attempt_id),
                    cursor INTEGER NOT NULL CHECK(cursor >= 0),
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_events (
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL CHECK(seq > 0),
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, seq)
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_effects (
                    effect_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('prepared','committed','unknown','reconciled','failed')),
                    payload_json TEXT NOT NULL,
                    receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS ops_compactions (
                    run_id TEXT PRIMARY KEY,
                    through_seq INTEGER NOT NULL,
                    boundary_hash TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                "INSERT OR REPLACE INTO operations_meta(key, value) VALUES ('schema', ?)",
                (OPERATIONS_SCHEMA,),
            )
            tx.execute(
                "INSERT OR IGNORE INTO ops_slots(slot_id, capacity, updated_at) VALUES ('default', 1, ?)",
                (_now(),),
            )
            tx.execute(
                "INSERT OR IGNORE INTO operations_meta(key, value) VALUES ('agent_slot_capacity', '6')"
            )

    def initialize(self) -> dict[str, Any]:
        if not self.auto_create:
            raise OperationsStoreError("STORE_READ_ONLY")
        with self._write_lock():
            with self._open() as store:
                self._validate_existing_schema(store)
                self._ensure_schema(store)
        return {"schema": OPERATIONS_API_SCHEMA, "status": "ready", "capabilities": self.capabilities()}

    @staticmethod
    def _validate_existing_schema(store: StoreConnection) -> None:
        try:
            row = store.execute("SELECT value FROM operations_meta WHERE key='schema'").fetchone()
        except sqlite3.Error:
            return
        if row and row[0] != OPERATIONS_SCHEMA:
            raise OperationsStoreError("OPERATIONS_SCHEMA_INVALID")

    def _ensure_ready(self, store: StoreConnection) -> None:
        if self.auto_create:
            self._validate_existing_schema(store)
            self._ensure_schema(store)
            return
        try:
            row = store.execute("SELECT value FROM operations_meta WHERE key='schema'").fetchone()
        except sqlite3.Error as error:
            raise OperationsStoreError("STORE_NOT_INITIALIZED") from error
        if not row or row[0] != OPERATIONS_SCHEMA:
            raise OperationsStoreError("OPERATIONS_SCHEMA_INVALID")

    def capabilities(self) -> dict[str, Any]:
        with self._open(read_only=True) as store:
            modules = {
                str(row[0]).casefold()
                for row in store.connection.execute("SELECT name FROM pragma_module_list")
            }
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "capabilities": {
                "sqlite": True,
                "wal": True,
                "fencing": True,
                "hash_chained_journal": True,
                "effect_ledger": True,
                "module_count": len(modules),
            },
        }

    @staticmethod
    def _lease(tx: Any, attempt_id: str, fence_token: str) -> tuple[Any, ...]:
        row = tx.execute(
            """SELECT l.lease_id, l.worker_id, l.slot_id, l.state, l.expires_at, a.task_id, a.state
               FROM ops_leases l JOIN ops_attempts a ON a.attempt_id=l.attempt_id
               WHERE l.attempt_id=? AND l.fence_token=?""",
            (attempt_id, fence_token),
        ).fetchone()
        if not row:
            raise OperationsStoreError("STALE_FENCE", attempt_id)
        if row[3] != "active":
            raise OperationsStoreError("LEASE_NOT_ACTIVE", attempt_id)
        if float(row[4]) <= _clock():
            raise OperationsStoreError("LEASE_EXPIRED", attempt_id)
        return row

    @staticmethod
    def _event_tx(tx: Any, run_id: str, event_type: str, payload_json: str) -> dict[str, Any]:
        last = tx.execute(
            "SELECT seq, event_hash FROM ops_events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)
        ).fetchone()
        compacted = tx.execute(
            "SELECT through_seq, boundary_hash FROM ops_compactions WHERE run_id=?", (run_id,)
        ).fetchone()
        seq = int(last[0]) + 1 if last else int(compacted[0]) + 1 if compacted else 1
        previous = str(last[1]) if last else str(compacted[1]) if compacted else _GENESIS
        created_at = _now()
        event_id = uuid.uuid4().hex
        event_hash = _sha(
            {
                "run_id": run_id,
                "seq": seq,
                "event_id": event_id,
                "event_type": event_type,
                "payload_json": payload_json,
                "prev_hash": previous,
                "created_at": created_at,
            }
        )
        tx.execute(
            "INSERT INTO ops_events(run_id, seq, event_id, event_type, payload_json, prev_hash, event_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, seq, event_id, event_type, payload_json, previous, event_hash, created_at),
        )
        return {"run_id": run_id, "seq": seq, "event_id": event_id, "event_hash": event_hash}

    def register_slot(self, slot_id: str, capacity: int) -> dict[str, Any]:
        if not isinstance(slot_id, str) or not slot_id.strip() or capacity < 1:
            raise OperationsStoreError("SLOT_INVALID")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    tx.execute(
                        "INSERT INTO ops_slots(slot_id, capacity, updated_at) VALUES (?, ?, ?) ON CONFLICT(slot_id) DO UPDATE SET capacity=excluded.capacity, updated_at=excluded.updated_at",
                        (slot_id, capacity, _now()),
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": "registered",
            "slot_id": slot_id,
            "capacity": capacity,
        }

    @staticmethod
    def _agent_id(agent_id: str) -> str:
        if not isinstance(agent_id, str) or not agent_id or agent_id != agent_id.strip() or len(agent_id) > 256:
            raise OperationsStoreError("AGENT_ID_INVALID")
        if any(ord(char) < 32 or ord(char) == 127 for char in agent_id):
            raise OperationsStoreError("AGENT_ID_INVALID")
        return agent_id

    @staticmethod
    def _agent_record(row: Any) -> dict[str, Any]:
        columns = ("agent_id", "status", "attempt", "worktree", "lease_id", "descendants",
                   "worktree_active", "lease_active", "reason", "created_at", "updated_at")
        record = dict(zip(columns, tuple(row)))
        for key in ("descendants", "attempt"):
            record[key] = int(record[key])
        for key in ("worktree_active", "lease_active"):
            record[key] = bool(record[key])
        record["reclaimable"] = (
            record["status"] in _AGENT_SLOT_TERMINAL | frozenset(("reclaimable",))
            and not OperationsStore._agent_blockers(record)
        )
        return record

    @staticmethod
    def _agent_blockers(record: Mapping[str, Any]) -> list[str]:
        blockers = []
        if int(record.get("descendants", 0)) > 0:
            blockers.append("descendants")
        if bool(record.get("worktree_active", False)):
            blockers.append("worktree")
        if bool(record.get("lease_active", False)):
            blockers.append("lease")
        return blockers

    @staticmethod
    def _agent_capacity(tx: Any) -> int:
        row = tx.execute("SELECT value FROM operations_meta WHERE key='agent_slot_capacity'").fetchone()
        return int(row[0]) if row else 6

    @classmethod
    def _agent_snapshot(cls, tx: Any) -> dict[str, Any]:
        rows = [cls._agent_record(row) for row in tx.execute("SELECT * FROM ops_agent_slots ORDER BY agent_id")]
        counts = {state: 0 for state in _AGENT_SLOT_STATES}
        for record in rows:
            counts[record["status"]] += 1
        counts["reclaimable"] = sum(1 for record in rows if record["reclaimable"])
        active = sum(counts[state] for state in _AGENT_SLOT_ACTIVE)
        diagnostics = [
            {"agent_id": record["agent_id"], "status": record["status"], "blockers": cls._agent_blockers(record)}
            for record in rows if cls._agent_blockers(record)
        ]
        capacity = cls._agent_capacity(tx)
        return {
            "schema": _AGENT_SLOT_SCHEMA,
            "capacity": capacity,
            "active_slots": active,
            "available_slots": capacity - active,
            "counts": counts,
            "records": rows,
            "diagnostics": diagnostics,
            "capacity_holders": [record["agent_id"] for record in rows if record["status"] in _AGENT_SLOT_ACTIVE],
            "local_llm": False,
        }

    @classmethod
    def _agent_receipt(cls, operation: str, *, accepted: bool, reason_code: str,
                       agent_id: str = "", status: str | None = None,
                       attempt: int | None = None, diagnostics: Mapping[str, Any] | None = None,
                       active_slots: int | None = None, capacity: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": _AGENT_SLOT_RECEIPT_SCHEMA,
            "contract": _AGENT_SLOT_SCHEMA,
            "operation": operation,
            "accepted": accepted,
            "reason_code": reason_code,
            "agent_id": agent_id,
            "status": status,
            "attempt": attempt,
            "diagnostics": dict(diagnostics or {}),
            "active_slots": active_slots,
            "capacity": capacity,
            "local_llm": False,
        }
        payload["receipt_hash"] = _sha(payload)
        return payload

    def configure_agent_slots(self, capacity: int) -> dict[str, Any]:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise OperationsStoreError("AGENT_SLOT_CAPACITY_INVALID")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    active = tx.execute(
                        "SELECT COUNT(*) FROM ops_agent_slots WHERE status IN ('pending','running')"
                    ).fetchone()[0]
                    if int(active) > capacity:
                        raise OperationsStoreError("AGENT_SLOT_CAPACITY_BELOW_ACTIVE")
                    tx.execute(
                        "INSERT INTO operations_meta(key,value) VALUES ('agent_slot_capacity',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(capacity),),
                    )
        return {"schema": _AGENT_SLOT_SCHEMA, "status": "configured", "capacity": capacity, "local_llm": False}

    def agent_slot_status(self) -> dict[str, Any]:
        if not self.database.is_file():
            raise OperationsStoreError("STORE_NOT_INITIALIZED")
        with self._open(read_only=True) as store:
            self._read_ready(store)
            return self._agent_snapshot(store)

    def agent_slot_acquire(self, agent_id: str, *, worktree: str | None = None,
                           lease_id: str | None = None) -> dict[str, Any]:
        agent_id = self._agent_id(agent_id)
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    existing = tx.execute("SELECT * FROM ops_agent_slots WHERE agent_id=?", (agent_id,)).fetchone()
                    snapshot = self._agent_snapshot(tx)
                    if existing:
                        record = self._agent_record(existing)
                        return self._agent_receipt("acquire", accepted=False, reason_code="duplicate_agent",
                                                   agent_id=agent_id, status=record["status"], attempt=record["attempt"],
                                                   diagnostics={"existing": record, "snapshot": snapshot},
                                                   active_slots=snapshot["active_slots"], capacity=snapshot["capacity"])
                    if snapshot["active_slots"] >= snapshot["capacity"]:
                        return self._agent_receipt("acquire", accepted=False, reason_code="slot_capacity_exhausted",
                                                   agent_id=agent_id, diagnostics={"snapshot": snapshot},
                                                   active_slots=snapshot["active_slots"], capacity=snapshot["capacity"])
                    now = _now()
                    tx.execute(
                        "INSERT INTO ops_agent_slots(agent_id,status,attempt,worktree,lease_id,descendants,worktree_active,lease_active,reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (agent_id, "pending", 1, worktree, lease_id, 0, 0, 0, None, now, now),
                    )
                    return self._agent_receipt("acquire", accepted=True, reason_code="slot_acquired",
                                               agent_id=agent_id, status="pending", attempt=1,
                                               active_slots=snapshot["active_slots"] + 1, capacity=snapshot["capacity"])

    def agent_slot_transition(self, agent_id: str, target: str, *, reason: str = "") -> dict[str, Any]:
        agent_id = self._agent_id(agent_id)
        if target not in _AGENT_SLOT_STATES or target == "reclaimable":
            raise OperationsStoreError("AGENT_SLOT_TRANSITION_INVALID")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    row = tx.execute("SELECT * FROM ops_agent_slots WHERE agent_id=?", (agent_id,)).fetchone()
                    if not row:
                        return self._agent_receipt("transition", accepted=False, reason_code="unknown_agent", agent_id=agent_id)
                    record = self._agent_record(row)
                    snapshot = self._agent_snapshot(tx)
                    if record["status"] == target:
                        return self._agent_receipt("transition", accepted=False, reason_code="idempotent", agent_id=agent_id,
                                                   status=target, attempt=record["attempt"], active_slots=snapshot["active_slots"], capacity=snapshot["capacity"])
                    allowed = (record["status"] == "pending" and target == "running") or (
                        record["status"] in _AGENT_SLOT_ACTIVE and target in _AGENT_SLOT_TERMINAL
                    )
                    if not allowed:
                        return self._agent_receipt("transition", accepted=False, reason_code="invalid_transition",
                                                   agent_id=agent_id, status=record["status"], attempt=record["attempt"],
                                                   diagnostics={"target": target}, active_slots=snapshot["active_slots"], capacity=snapshot["capacity"])
                    tx.execute("UPDATE ops_agent_slots SET status=?,reason=?,updated_at=? WHERE agent_id=?",
                               (target, reason or "agent_terminal", _now(), agent_id))
                    updated = self._agent_snapshot(tx)
                    return self._agent_receipt("transition", accepted=True, reason_code=reason or "agent_terminal",
                                               agent_id=agent_id, status=target, attempt=record["attempt"],
                                               active_slots=updated["active_slots"], capacity=updated["capacity"],
                                               diagnostics={"capacity_released": target in _AGENT_SLOT_TERMINAL})

    def agent_slot_update_blockers(self, agent_id: str, *, descendants: int = 0,
                                   worktree_active: bool = False, lease_active: bool = False) -> dict[str, Any]:
        agent_id = self._agent_id(agent_id)
        if not isinstance(descendants, int) or isinstance(descendants, bool) or descendants < 0:
            raise OperationsStoreError("AGENT_SLOT_BLOCKERS_INVALID")
        if not isinstance(worktree_active, bool) or not isinstance(lease_active, bool):
            raise OperationsStoreError("AGENT_SLOT_BLOCKERS_INVALID")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    row = tx.execute("SELECT * FROM ops_agent_slots WHERE agent_id=?", (agent_id,)).fetchone()
                    if not row:
                        return self._agent_receipt("update_blockers", accepted=False, reason_code="unknown_agent", agent_id=agent_id)
                    tx.execute("UPDATE ops_agent_slots SET descendants=?,worktree_active=?,lease_active=?,updated_at=? WHERE agent_id=?",
                               (descendants, int(worktree_active), int(lease_active), _now(), agent_id))
                    snapshot = self._agent_snapshot(tx)
                    blockers = self._agent_blockers({"descendants": descendants, "worktree_active": worktree_active, "lease_active": lease_active})
                    return self._agent_receipt("update_blockers", accepted=True, reason_code="blockers_updated",
                                               agent_id=agent_id, status=row[1], attempt=int(row[2]),
                                               diagnostics={"blockers": blockers}, active_slots=snapshot["active_slots"], capacity=snapshot["capacity"])

    def agent_slot_reclaim(self, agent_id: str | None = None) -> dict[str, Any]:
        selected = self._agent_id(agent_id) if agent_id is not None else None
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    query = "SELECT * FROM ops_agent_slots WHERE status IN ('completed','shutdown','reclaimable')"
                    params: tuple[Any, ...] = ()
                    if selected is not None:
                        query += " AND agent_id=?"
                        params = (selected,)
                    rows = [self._agent_record(row) for row in tx.execute(query, params)]
                    reclaimed = [record["agent_id"] for record in rows if not self._agent_blockers(record)]
                    blocked = [{"agent_id": record["agent_id"], "status": record["status"], "blockers": self._agent_blockers(record)}
                               for record in rows if self._agent_blockers(record)]
                    snapshot = self._agent_snapshot(tx)
                    return self._agent_receipt("reclaim", accepted=not blocked,
                                               reason_code="slots_reclaimed" if not blocked else "reclaim_blocked",
                                               agent_id=selected or "", diagnostics={"reclaimed": reclaimed, "blocked": blocked,
                                                                                       "available_slots": snapshot["available_slots"]},
                                               active_slots=snapshot["active_slots"], capacity=snapshot["capacity"])

    def enqueue(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        if (
            not isinstance(task_id, str)
            or not isinstance(idempotency_key, str)
            or not task_id.strip()
            or not idempotency_key.strip()
        ):
            raise OperationsStoreError("TASK_IDENTITY_INVALID")
        payload_json = _json_payload(payload, "task")
        now = _now()
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    existing = tx.execute(
                        "SELECT task_id, payload_json, state FROM ops_tasks WHERE idempotency_key=?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing:
                        if existing[1] != payload_json or existing[0] != task_id:
                            raise OperationsStoreError("IDEMPOTENCY_CONFLICT", idempotency_key)
                        return {
                            "schema": OPERATIONS_API_SCHEMA,
                            "status": "unchanged",
                            "task_id": task_id,
                            "state": existing[2],
                        }
                    tx.execute(
                        "INSERT INTO ops_tasks(task_id, idempotency_key, payload_json, state, priority, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                        (task_id, idempotency_key, payload_json, priority, now, now),
                    )
        return {"schema": OPERATIONS_API_SCHEMA, "status": "queued", "task_id": task_id, "state": "queued"}

    def import_task(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        state: str = "queued",
        priority: int = 0,
    ) -> dict[str, Any]:
        """Import a task without synthesizing an attempt or lease.

        Queued imports may be claimed normally. Terminal imports preserve
        history with ``terminal_verified=1``; active legacy leases are not
        representable here and must be reconciled by a caller first.
        """
        if (
            not isinstance(task_id, str)
            or not isinstance(idempotency_key, str)
            or not task_id.strip()
            or not idempotency_key.strip()
        ):
            raise OperationsStoreError("TASK_IDENTITY_INVALID")
        if state not in {"queued", "completed", "cancelled", "failed"}:
            raise OperationsStoreError("IMPORT_STATE_UNSUPPORTED")
        payload_json = _json_payload(payload, "imported_task")
        terminal = state in {"completed", "cancelled", "failed"}
        now = _now()
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    existing = tx.execute(
                        "SELECT task_id,idempotency_key,payload_json,state FROM ops_tasks WHERE idempotency_key=? OR task_id=?",
                        (idempotency_key, task_id),
                    ).fetchone()
                    if existing:
                        if existing[0] != task_id or existing[1] != idempotency_key or existing[2] != payload_json:
                            raise OperationsStoreError("IDEMPOTENCY_CONFLICT", idempotency_key)
                        return {
                            "schema": OPERATIONS_API_SCHEMA,
                            "status": "unchanged",
                            "task_id": task_id,
                            "state": existing[3],
                            "imported": True,
                        }
                    tx.execute(
                        "INSERT INTO ops_tasks(task_id,idempotency_key,payload_json,state,priority,cancellation_requested,terminal_verified,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (task_id, idempotency_key, payload_json, state, priority, int(state == "cancelled"), int(terminal), now, now),
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": "imported",
            "task_id": task_id,
            "state": state,
            "imported": True,
            "terminal_verified": terminal,
        }

    def claim(
        self,
        worker_id: str,
        *,
        slot_id: str = "default",
        lease_seconds: float = 30.0,
        task_id: str | None = None,
    ) -> dict[str, Any] | None:
        if (
            not isinstance(worker_id, str)
            or not worker_id.strip()
            or not isinstance(slot_id, str)
            or not slot_id.strip()
            or lease_seconds <= 0
            or (task_id is not None and (not isinstance(task_id, str) or not task_id.strip()))
        ):
            raise OperationsStoreError("CLAIM_INVALID")
        now = _clock()
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    slot = tx.execute("SELECT capacity FROM ops_slots WHERE slot_id=?", (slot_id,)).fetchone()
                    if not slot:
                        raise OperationsStoreError("SLOT_NOT_FOUND", slot_id)
                    active = tx.execute(
                        "SELECT COUNT(*) FROM ops_leases WHERE slot_id=? AND state='active' AND expires_at>?",
                        (slot_id, now),
                    ).fetchone()[0]
                    if int(active) >= int(slot[0]):
                        raise OperationsStoreError("SLOT_CAPACITY")
                    task_query = (
                        "SELECT task_id, payload_json, priority FROM ops_tasks "
                        "WHERE state='queued' AND terminal_verified=0 AND cancellation_requested=0"
                    )
                    task_params: tuple[Any, ...] = ()
                    if task_id is not None:
                        task_query += " AND task_id=?"
                        task_params = (task_id,)
                    task_query += " ORDER BY priority DESC, created_at, task_id LIMIT 1"
                    task = tx.execute(task_query, task_params).fetchone()
                    if not task:
                        if task_id is not None:
                            exists = tx.execute(
                                "SELECT task_id FROM ops_tasks WHERE task_id=?", (task_id,)
                            ).fetchone()
                            if not exists:
                                raise OperationsStoreError("TASK_NOT_FOUND", task_id)
                        return None
                    attempt_id = uuid.uuid4().hex
                    token = uuid.uuid4().hex
                    lease_id = uuid.uuid4().hex
                    created = _now()
                    tx.execute(
                        "INSERT INTO ops_attempts(attempt_id, task_id, worker_id, fence_token, state, created_at, updated_at) VALUES (?, ?, ?, ?, 'running', ?, ?)",
                        (attempt_id, task[0], worker_id, token, created, created),
                    )
                    tx.execute(
                        "INSERT INTO ops_leases(lease_id, attempt_id, worker_id, fence_token, slot_id, state, heartbeat_at, expires_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                        (lease_id, attempt_id, worker_id, token, slot_id, now, now + lease_seconds),
                    )
                    tx.execute(
                        "UPDATE ops_tasks SET state='running', updated_at=? WHERE task_id=?",
                        (created, task[0]),
                    )
                    return {
                        "schema": OPERATIONS_API_SCHEMA,
                        "status": "claimed",
                        "task_id": task[0],
                        "attempt_id": attempt_id,
                        "fence_token": token,
                        "lease_id": lease_id,
                        "worker_id": worker_id,
                        "payload": json.loads(task[1]),
                        "expires_at": now + lease_seconds,
                        "cancelled": False,
                    }

    def claim_task(
        self,
        task_id: str,
        worker_id: str,
        *,
        slot_id: str = "default",
        lease_seconds: float = 30.0,
    ) -> dict[str, Any] | None:
        """Claim one named queued task without duplicating lease semantics."""
        return self.claim(
            worker_id,
            slot_id=slot_id,
            lease_seconds=lease_seconds,
            task_id=task_id,
        )

    def list_ready(self, *, limit: int = 20) -> dict[str, Any]:
        """Return bounded ready-task summaries for consumer discovery."""
        if not isinstance(limit, int) or limit < 1:
            raise OperationsStoreError("LIST_INVALID")
        if not self.database.is_file():
            raise OperationsStoreError("STORE_NOT_INITIALIZED")
        with self._open(read_only=True) as store:
            try:
                self._read_ready(store)
                rows = store.execute(
                    """SELECT task_id, state, payload_json, priority, created_at, updated_at
                       FROM ops_tasks
                       WHERE state='queued' AND terminal_verified=0 AND cancellation_requested=0
                       ORDER BY priority DESC, created_at, task_id LIMIT ?""",
                    (limit,),
                ).fetchall()
            except sqlite3.Error as error:
                raise OperationsStoreError("STORE_NOT_INITIALIZED") from error
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "tasks": [
                {
                    "task_id": row[0],
                    "state": row[1],
                    "payload": json.loads(row[2]),
                    "priority": int(row[3]),
                    "created_at": row[4],
                    "updated_at": row[5],
                }
                for row in rows
            ],
        }

    def heartbeat(self, attempt_id: str, fence_token: str, *, lease_seconds: float = 30.0) -> dict[str, Any]:
        if lease_seconds <= 0:
            raise OperationsStoreError("HEARTBEAT_INVALID")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    self._lease(tx, attempt_id, fence_token)
                    now = _clock()
                    cancellation = tx.execute(
                        "SELECT t.cancellation_requested FROM ops_tasks t "
                        "JOIN ops_attempts a ON a.task_id=t.task_id WHERE a.attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                    tx.execute(
                        "UPDATE ops_leases SET heartbeat_at=?, expires_at=? WHERE attempt_id=?",
                        (now, now + lease_seconds, attempt_id),
                    )
                    tx.execute(
                        "UPDATE ops_attempts SET updated_at=? WHERE attempt_id=?", (_now(), attempt_id)
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": "heartbeated",
            "attempt_id": attempt_id,
            "expires_at": now + lease_seconds,
            "cancelled": bool(cancellation[0]) if cancellation else False,
        }

    def assert_active(self, attempt_id: str, fence_token: str) -> dict[str, Any]:
        """Check a lease without extending it or writing a heartbeat."""
        if not isinstance(attempt_id, str) or not attempt_id.strip() or not isinstance(fence_token, str):
            raise OperationsStoreError("CLAIM_INVALID")
        if not self.database.is_file():
            raise OperationsStoreError("STORE_NOT_INITIALIZED")
        with self._open(read_only=True) as store:
            try:
                self._read_ready(store)
                row = store.execute(
                    "SELECT state, expires_at FROM ops_leases WHERE attempt_id=? AND fence_token=?",
                    (attempt_id, fence_token),
                ).fetchone()
            except sqlite3.Error as error:
                raise OperationsStoreError("STORE_NOT_INITIALIZED") from error
        if not row:
            raise OperationsStoreError("STALE_FENCE", attempt_id)
        if row[0] != "active":
            raise OperationsStoreError("LEASE_NOT_ACTIVE", attempt_id)
        if float(row[1]) <= _clock():
            raise OperationsStoreError("LEASE_EXPIRED", attempt_id)
        return {"schema": OPERATIONS_API_SCHEMA, "status": "active", "attempt_id": attempt_id}

    def release(self, attempt_id: str, fence_token: str) -> dict[str, Any]:
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    lease = self._lease(tx, attempt_id, fence_token)
                    now = _now()
                    tx.execute("UPDATE ops_leases SET state='released' WHERE attempt_id=?", (attempt_id,))
                    tx.execute(
                        "UPDATE ops_attempts SET state='released', updated_at=? WHERE attempt_id=?",
                        (now, attempt_id),
                    )
                    tx.execute(
                        "UPDATE ops_tasks SET state='queued', updated_at=? WHERE task_id=? AND terminal_verified=0",
                        (now, lease[5]),
                    )
        return {"schema": OPERATIONS_API_SCHEMA, "status": "released", "attempt_id": attempt_id}

    def complete(
        self,
        attempt_id: str,
        fence_token: str,
        *,
        status: str = "completed",
        receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in {"completed", "failed"}:
            raise OperationsStoreError("TERMINAL_STATE_INVALID")
        receipt_json = _json_payload(receipt, "receipt")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    lease = self._lease(tx, attempt_id, fence_token)
                    if status == "completed" and not receipt:
                        raise OperationsStoreError("RECEIPT_REQUIRED")
                    pending = tx.execute(
                        "SELECT COUNT(*) FROM ops_effects WHERE attempt_id=? AND state IN ('prepared', 'unknown')",
                        (attempt_id,),
                    ).fetchone()[0]
                    if pending:
                        raise OperationsStoreError("EFFECT_RECONCILIATION_PENDING", attempt_id)
                    now = _now()
                    tx.execute(
                        "UPDATE ops_leases SET state=? WHERE attempt_id=?",
                        ("completed" if status == "completed" else "released", attempt_id),
                    )
                    tx.execute(
                        "UPDATE ops_attempts SET state=?, updated_at=? WHERE attempt_id=?",
                        (status, now, attempt_id),
                    )
                    tx.execute(
                        "UPDATE ops_tasks SET state=?, terminal_verified=?, updated_at=? WHERE task_id=?",
                        (status, 1 if status == "completed" else 0, now, lease[5]),
                    )
                    tx.execute(
                        "INSERT OR REPLACE INTO operations_meta(key, value) VALUES (?, ?)",
                        (f"receipt:{attempt_id}", receipt_json),
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": status,
            "attempt_id": attempt_id,
            "terminal_verified": status == "completed",
        }

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    row = tx.execute(
                        "SELECT state, terminal_verified FROM ops_tasks WHERE task_id=?", (task_id,)
                    ).fetchone()
                    if not row:
                        raise OperationsStoreError("TASK_NOT_FOUND", task_id)
                    if row[1] or row[0] in {"cancelled", "completed", "failed"}:
                        return {
                            "schema": OPERATIONS_API_SCHEMA,
                            "status": "unchanged",
                            "task_id": task_id,
                            "state": row[0],
                        }
                    state = "cancelled" if row[0] == "queued" else row[0]
                    tx.execute(
                        "UPDATE ops_tasks SET state=?, cancellation_requested=1, updated_at=? WHERE task_id=?",
                        (state, _now(), task_id),
                    )
        return {"schema": OPERATIONS_API_SCHEMA, "status": "cancelled", "task_id": task_id, "state": state}

    def request_cancel(self, task_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
        """Request cooperative cancellation while retaining the current lease."""
        result = self.cancel(task_id)
        if result.get("state") == "running":
            result["cancel_requested"] = True
            result["reason"] = str(reason)
        return result

    def reclaim_expired(self) -> dict[str, Any]:
        recovered = 0
        now = _clock()
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    rows = tx.execute(
                        """SELECT l.attempt_id, a.task_id, t.cancellation_requested FROM ops_leases l
                           JOIN ops_attempts a ON a.attempt_id=l.attempt_id
                           JOIN ops_tasks t ON t.task_id=a.task_id
                           WHERE l.state='active' AND l.expires_at<=?""",
                        (now,),
                    ).fetchall()
                    for attempt_id, task_id, cancellation_requested in rows:
                        tx.execute("UPDATE ops_leases SET state='expired' WHERE attempt_id=?", (attempt_id,))
                        tx.execute(
                            "UPDATE ops_attempts SET state='expired', updated_at=? WHERE attempt_id=?",
                            (_now(), attempt_id),
                        )
                        tx.execute(
                            "UPDATE ops_tasks SET state=?, updated_at=? WHERE task_id=? AND terminal_verified=0",
                            ("cancelled" if cancellation_requested else "queued", _now(), task_id),
                        )
                        recovered += 1
        return {"schema": OPERATIONS_API_SCHEMA, "status": "reclaimed", "recovered": recovered}

    def checkpoint(
        self, attempt_id: str, fence_token: str, cursor: int, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        if cursor < 0:
            raise OperationsStoreError("CHECKPOINT_INVALID")
        payload_json = _json_payload(payload, "checkpoint")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    self._lease(tx, attempt_id, fence_token)
                    previous = tx.execute(
                        "SELECT cursor FROM ops_checkpoints WHERE attempt_id=?", (attempt_id,)
                    ).fetchone()
                    if previous and cursor < int(previous[0]):
                        raise OperationsStoreError("CHECKPOINT_REGRESSION", attempt_id)
                    tx.execute(
                        "INSERT INTO ops_checkpoints(attempt_id, cursor, payload_json, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(attempt_id) DO UPDATE SET cursor=excluded.cursor, payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                        (attempt_id, cursor, payload_json, _now()),
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": "checkpointed",
            "attempt_id": attempt_id,
            "cursor": cursor,
        }

    def prepare_effect(
        self,
        attempt_id: str,
        fence_token: str,
        effect_id: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            not isinstance(effect_id, str)
            or not isinstance(idempotency_key, str)
            or not effect_id.strip()
            or not idempotency_key.strip()
        ):
            raise OperationsStoreError("EFFECT_IDENTITY_INVALID")
        payload_json = _json_payload(payload, "effect")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    lease = self._lease(tx, attempt_id, fence_token)
                    existing = tx.execute(
                        "SELECT effect_id, state, payload_json, task_id FROM ops_effects WHERE idempotency_key=?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing:
                        if existing[0] != effect_id or existing[2] != payload_json or existing[3] != lease[5]:
                            raise OperationsStoreError("IDEMPOTENCY_CONFLICT", idempotency_key)
                        old_attempt = tx.execute(
                            "SELECT state FROM ops_attempts WHERE attempt_id=(SELECT attempt_id FROM ops_effects WHERE effect_id=?)",
                            (effect_id,),
                        ).fetchone()
                        if (
                            existing[1] in {"prepared", "unknown"}
                            and old_attempt
                            and old_attempt[0] != "running"
                        ):
                            tx.execute(
                                "UPDATE ops_effects SET attempt_id=?, task_id=?, updated_at=? WHERE effect_id=?",
                                (attempt_id, lease[5], _now(), effect_id),
                            )
                            return {
                                "schema": OPERATIONS_API_SCHEMA,
                                "status": "adopted",
                                "effect_id": effect_id,
                                "state": existing[1],
                            }
                        return {
                            "schema": OPERATIONS_API_SCHEMA,
                            "status": "unchanged",
                            "effect_id": effect_id,
                            "state": existing[1],
                        }
                    tx.execute(
                        "INSERT INTO ops_effects(effect_id, idempotency_key, task_id, attempt_id, state, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'prepared', ?, ?, ?)",
                        (effect_id, idempotency_key, lease[5], attempt_id, payload_json, _now(), _now()),
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": "prepared",
            "effect_id": effect_id,
            "state": "prepared",
        }

    def _effect_transition(
        self,
        effect_id: str,
        attempt_id: str,
        fence_token: str | None,
        target: str,
        receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt_json = _json_payload(receipt, "receipt") if receipt is not None else None
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    if fence_token is not None:
                        self._lease(tx, attempt_id, fence_token)
                    elif target not in {"reconciled", "failed"}:
                        raise OperationsStoreError("STALE_FENCE", attempt_id)
                    row = tx.execute(
                        "SELECT state, attempt_id, receipt_json FROM ops_effects WHERE effect_id=?",
                        (effect_id,),
                    ).fetchone()
                    if not row or row[1] != attempt_id:
                        raise OperationsStoreError("EFFECT_NOT_FOUND", effect_id)
                    if target == "committed" and row[0] == "committed":
                        if row[2] == receipt_json:
                            return {
                                "schema": OPERATIONS_API_SCHEMA,
                                "status": "unchanged",
                                "effect_id": effect_id,
                                "state": "committed",
                            }
                        raise OperationsStoreError("EFFECT_IDEMPOTENCY_CONFLICT", effect_id)
                    if target == "unknown" and row[0] != "prepared":
                        raise OperationsStoreError("EFFECT_STATE_INVALID", row[0])
                    if target == "committed" and row[0] != "prepared":
                        raise OperationsStoreError("RECONCILIATION_REQUIRED", effect_id)
                    if target in {"reconciled", "failed"} and row[0] != "unknown":
                        raise OperationsStoreError("RECONCILIATION_REQUIRED", effect_id)
                    tx.execute(
                        "UPDATE ops_effects SET state=?, receipt_json=?, updated_at=? WHERE effect_id=?",
                        (target, receipt_json, _now(), effect_id),
                    )
        return {"schema": OPERATIONS_API_SCHEMA, "status": target, "effect_id": effect_id, "state": target}

    def commit_effect(
        self, effect_id: str, attempt_id: str, fence_token: str, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._effect_transition(effect_id, attempt_id, fence_token, "committed", receipt)

    def mark_effect_unknown(self, effect_id: str, attempt_id: str, fence_token: str) -> dict[str, Any]:
        return self._effect_transition(effect_id, attempt_id, fence_token, "unknown")

    def reconcile_effect(
        self,
        effect_id: str,
        attempt_id: str,
        fence_token: str | None,
        *,
        outcome: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        if outcome not in {"committed", "failed"}:
            raise OperationsStoreError("RECONCILIATION_INVALID")
        return self._effect_transition(
            effect_id, attempt_id, fence_token, "reconciled" if outcome == "committed" else "failed", receipt
        )

    def append_event(
        self, run_id: str, event_type: str, payload: Mapping[str, Any], *, expected_seq: int | None = None
    ) -> dict[str, Any]:
        if (
            not isinstance(run_id, str)
            or not isinstance(event_type, str)
            or not run_id.strip()
            or not event_type.strip()
        ):
            raise OperationsStoreError("EVENT_INVALID")
        payload_json = _json_payload(payload, "event")
        with self._write_lock():
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    row = tx.execute(
                        "SELECT seq FROM ops_events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)
                    ).fetchone()
                    compacted = tx.execute(
                        "SELECT through_seq FROM ops_compactions WHERE run_id=?", (run_id,)
                    ).fetchone()
                    current = int(row[0]) if row else int(compacted[0]) if compacted else 0
                    if expected_seq is not None and expected_seq != current:
                        raise OperationsStoreError(
                            "JOURNAL_CONFLICT", f"expected {expected_seq}, actual {current}"
                        )
                    receipt = self._event_tx(tx, run_id, event_type, payload_json)
        return {"schema": OPERATIONS_API_SCHEMA, "status": "appended", **receipt}

    def replay(self, run_id: str) -> dict[str, Any]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise OperationsStoreError("EVENT_INVALID")
        if not self.database.is_file():
            raise OperationsStoreError("STORE_NOT_INITIALIZED")
        with self._open(read_only=True) as store:
            try:
                self._read_ready(store)
                compaction = store.execute(
                    "SELECT through_seq, boundary_hash, snapshot_hash, snapshot_json FROM ops_compactions WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            except sqlite3.Error as error:
                raise OperationsStoreError("STORE_NOT_INITIALIZED") from error
            rows = store.execute(
                "SELECT seq, event_id, event_type, payload_json, prev_hash, event_hash, created_at FROM ops_events WHERE run_id=? ORDER BY seq",
                (run_id,),
            ).fetchall()
        if compaction and _sha(json.loads(compaction[3])) != compaction[2]:
            raise OperationsStoreError("JOURNAL_TAMPERED", run_id)
        start_seq = int(compaction[0]) + 1 if compaction else 1
        previous = str(compaction[1]) if compaction else _GENESIS
        events: list[dict[str, Any]] = []
        for expected, row in enumerate(rows, start_seq):
            if int(row[0]) != expected or row[4] != previous:
                raise OperationsStoreError("JOURNAL_OUT_OF_ORDER", run_id)
            computed = _sha(
                {
                    "run_id": run_id,
                    "seq": row[0],
                    "event_id": row[1],
                    "event_type": row[2],
                    "payload_json": row[3],
                    "prev_hash": row[4],
                    "created_at": row[6],
                }
            )
            if computed != row[5]:
                raise OperationsStoreError("JOURNAL_TAMPERED", run_id)
            events.append(
                {
                    "seq": row[0],
                    "event_id": row[1],
                    "event_type": row[2],
                    "payload": json.loads(row[3]),
                    "event_hash": row[5],
                    "created_at": row[6],
                }
            )
            previous = row[5]
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "valid": True,
            "run_id": run_id,
            "events": events,
            "last_hash": previous,
            "compaction": (
                {
                    "through_seq": int(compaction[0]),
                    "boundary_hash": compaction[1],
                    "snapshot_hash": compaction[2],
                    "snapshot": json.loads(compaction[3]),
                }
                if compaction
                else None
            ),
        }

    def compact(self, run_id: str, through_seq: int, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if through_seq < 1:
            raise OperationsStoreError("COMPACTION_INVALID")
        snapshot_json = _json_payload(snapshot, "snapshot")
        with self._write_lock():
            replayed = self.replay(run_id)
            boundary = next((row for row in replayed["events"] if row["seq"] == through_seq), None)
            if boundary is None:
                raise OperationsStoreError("COMPACTION_BOUNDARY_MISSING")
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    tx.execute(
                        "DELETE FROM ops_events WHERE run_id=? AND seq<=?",
                        (run_id, through_seq),
                    )
                    tx.execute(
                        "INSERT INTO ops_compactions(run_id, through_seq, boundary_hash, snapshot_hash, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET through_seq=excluded.through_seq, boundary_hash=excluded.boundary_hash, snapshot_hash=excluded.snapshot_hash, snapshot_json=excluded.snapshot_json, created_at=excluded.created_at",
                        (run_id, through_seq, boundary["event_hash"], _sha(snapshot), snapshot_json, _now()),
                    )
        return {
            "schema": OPERATIONS_API_SCHEMA,
            "status": "compacted",
            "run_id": run_id,
            "through_seq": through_seq,
            "boundary_hash": boundary["event_hash"],
            "events_retained": max(0, len(replayed["events"]) - through_seq),
        }

    def status(self, task_id: str | None = None) -> dict[str, Any]:
        if not self.database.is_file():
            raise OperationsStoreError("STORE_NOT_INITIALIZED")
        with self._open(read_only=True) as store:
            try:
                self._read_ready(store)
            except sqlite3.Error as error:
                raise OperationsStoreError("STORE_NOT_INITIALIZED") from error
            if task_id:
                task = store.execute(
                    "SELECT task_id, state, cancellation_requested, terminal_verified, payload_json FROM ops_tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if not task:
                    raise OperationsStoreError("TASK_NOT_FOUND", task_id)
                attempts = store.execute(
                    "SELECT attempt_id, worker_id, state, created_at, updated_at FROM ops_attempts WHERE task_id=? ORDER BY created_at",
                    (task_id,),
                ).fetchall()
                return {
                    "schema": OPERATIONS_API_SCHEMA,
                    "task_id": task[0],
                    "state": task[1],
                    "cancellation_requested": bool(task[2]),
                    "terminal_verified": bool(task[3]),
                    "payload": json.loads(task[4]),
                    "attempts": [
                        dict(
                            attempt_id=row[0],
                            worker_id=row[1],
                            state=row[2],
                            created_at=row[3],
                            updated_at=row[4],
                        )
                        for row in attempts
                    ],
                }
            rows = store.execute("SELECT state, COUNT(*) FROM ops_tasks GROUP BY state").fetchall()
        counts = {state: 0 for state in ("queued", "running", "completed", "cancelled", "failed")}
        counts.update({str(row[0]): int(row[1]) for row in rows})
        return {"schema": OPERATIONS_API_SCHEMA, "counts": counts}

    @staticmethod
    def _read_ready(store: StoreConnection) -> None:
        row = store.execute("SELECT value FROM operations_meta WHERE key='schema'").fetchone()
        if not row or row[0] != OPERATIONS_SCHEMA:
            raise OperationsStoreError("OPERATIONS_SCHEMA_INVALID")


__all__ = ["OPERATIONS_API_SCHEMA", "OPERATIONS_SCHEMA", "OperationsStore", "OperationsStoreError"]
