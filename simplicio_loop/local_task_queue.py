"""Local-task compatibility facade backed by MapperStore operations.

The historical implementation added ``local_*`` tables to a Loop-owned
SQLite queue.  The facade keeps the outcome/receipt API used by older callers,
but task, lease and fencing authority now lives in :class:`MapperRemoteQueue`.
Outcome projections are append-only Mapper operations events as well.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .mapper_remote_queue import (
    MapperRemoteQueue,
    build_mapper_completion_receipt,
)
from .remote_queue import Lease, QueueConflict, QueueUnavailable


SCHEMA = "simplicio.loop.local-task-queue/v2"
LEGACY_SCHEMA = "simplicio.loop.local-task-queue/v1"
EVENT_SCHEMA = "simplicio.loop.local-task-state-event/v1"
JOURNAL_PREFIX = "simplicio.loop.local-task-state:"
LOCAL_SLOT_ID = "local-task-queue"
LOCAL_SLOT_CAPACITY = 1024
OUTCOMES = frozenset({
    "never_started", "running", "unknown_outcome", "verified_success",
    "retryable_failure", "blocked", "dead_letter",
})


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _mapper_database(root: Path) -> Path:
    """Resolve the repo-scoped canonical operations store without creating it."""

    try:
        from simplicio_mapper.store import resolve_store_location
    except (ImportError, ModuleNotFoundError) as error:
        raise QueueUnavailable("MapperStore operations API is not installed") from error
    environ = dict(os.environ)
    environ.pop("SIMPLICIO_DATA_DIR", None)
    environ.pop("SIMPLICIO_HOME", None)
    environ["SIMPLICIO_STORE_SCOPE"] = "repo"
    try:
        location = resolve_store_location(environ=environ, repo_root=root)
        return Path(location.database("operations.sqlite"))
    except (OSError, ValueError) as error:
        raise QueueUnavailable(f"canonical MapperStore path unavailable: {error}") from error


class LocalTaskQueue:
    """MapperStore-backed local task lifecycle facade."""

    def __init__(self, root: str | Path, *, busy_timeout: float = 10.0,
                 allow_legacy: bool = False) -> None:
        del busy_timeout
        root = Path(root).resolve()
        if str(root).startswith("\\\\"):
            raise QueueUnavailable("network filesystem locking is not trusted")
        self.data_dir = root / ".simplicio-loop" / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = str(_mapper_database(root))
        self._queue = MapperRemoteQueue(
            self.path, auto_create=True, slot_id=LOCAL_SLOT_ID
        )
        self._queue.initialize()
        self._operations = self._queue.operations
        # The historical local queue allowed independent tasks to be leased
        # concurrently.  Preserve that API behavior through an explicit
        # Mapper-owned slot instead of a Loop-side capacity counter.
        self._operations.register_slot(LOCAL_SLOT_ID, LOCAL_SLOT_CAPACITY)
        self._journal_id = JOURNAL_PREFIX + self.path
        self._lock = threading.RLock()
        self._allow_legacy = allow_legacy

    @staticmethod
    def _last_seq(replay: Mapping[str, Any]) -> int:
        events = replay.get("events") or []
        if events:
            return int(events[-1]["seq"])
        compaction = replay.get("compaction")
        return int(compaction["through_seq"]) if compaction else 0

    def _replay(self) -> dict[str, Any]:
        replay = self._operations.replay(self._journal_id)
        if not replay.get("valid", False):
            raise QueueUnavailable("local task journal is invalid")
        return replay

    @staticmethod
    def _state(replay: Mapping[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = {
            "schema": SCHEMA, "stopped": False, "outcomes": {}, "transitions": [],
        }
        for journal_event in replay.get("events", []):
            payload = journal_event.get("payload")
            if not isinstance(payload, Mapping) or payload.get("schema") != EVENT_SCHEMA:
                raise QueueUnavailable("local task journal contains an unknown event")
            if payload.get("operation") != "snapshot":
                raise QueueUnavailable("local task journal contains an unknown operation")
            state = json.loads(json.dumps(payload.get("state") or state))
        return state

    @staticmethod
    def _is_conflict(error: BaseException) -> bool:
        return "JOURNAL_CONFLICT" in str(error) or getattr(error, "reason_code", "") == "JOURNAL_CONFLICT"

    def _commit(self, replay: Mapping[str, Any], state: Mapping[str, Any]) -> None:
        try:
            self._operations.append_event(
                self._journal_id,
                "local-task.snapshot",
                {"schema": EVENT_SCHEMA, "operation": "snapshot", "state": dict(state)},
                expected_seq=self._last_seq(replay),
            )
        except Exception as error:
            if self._is_conflict(error):
                raise QueueConflict("local task state changed concurrently") from error
            raise QueueUnavailable("local task state append failed: " + str(error)) from error

    def _mutate(self, mutator):
        with self._lock:
            for _ in range(32):
                replay = self._replay()
                state = self._state(replay)
                result = mutator(state)
                try:
                    self._commit(replay, state)
                    return result
                except QueueConflict:
                    continue
        raise QueueUnavailable("local task state remained contended")

    @staticmethod
    def _transition(state: dict[str, Any], task_id: str, old: str | None,
                    new: str, payload: Mapping[str, Any] | None = None) -> None:
        value = {"schema": SCHEMA, "task_id": task_id, "from": old,
                 "to": new, "payload": dict(payload or {}), "created_ns": time.time_ns()}
        state["transitions"].append({
            "seq": len(state["transitions"]) + 1,
            "task_id": task_id,
            "from_state": old,
            "to_state": new,
            "payload": json.dumps(value, sort_keys=True),
            "digest": _digest(value),
            "created_at": time.time(),
        })

    @staticmethod
    def _lease(value: Mapping[str, Any] | None) -> Lease | None:
        if not value:
            return None
        return Lease(
            task_id=str(value["task_id"]), agent_id=str(value["agent_id"]),
            lease_id=str(value["lease_id"]), fencing_token=value["fencing_token"],
            expires_at=float(value["expires_at"]), idempotency_key=str(value["idempotency_key"]),
            identity=value.get("identity"), capabilities=tuple(value.get("capabilities") or ()),
            cancelled=bool(value.get("cancelled", False)), attempt_id=str(value.get("attempt_id") or ""),
        )

    @staticmethod
    def _lease_dict(lease: Lease) -> dict[str, Any]:
        return dict(lease.__dict__)

    def submit(self, task_id: str, payload: Mapping[str, Any] | None = None,
               *, depends_on: Sequence[str] = ()) -> None:
        task_id = str(task_id).strip()
        if not task_id:
            raise ValueError("task_id is required")
        dependencies = sorted(set(map(str, depends_on)))
        task_payload = {**dict(payload or {}), "depends_on": dependencies}
        with self._lock:
            state = self._state(self._replay())
            if state["stopped"]:
                raise QueueConflict("queue is stopped")
            if task_id in state["outcomes"]:
                return
            self._queue.enqueue(task_id, task_payload, idempotency_key=f"local:task:{task_id}")
            state["outcomes"][task_id] = {
                "task_id": task_id, "outcome": "never_started", "intent": None,
                "receipt": None, "provenance": None, "lease": None, "updated_at": time.time(),
            }
            self._transition(state, task_id, None, "never_started")
            self._commit(self._replay(), state)

    def _require_outcome(self, state: Mapping[str, Any], task_id: str) -> dict[str, Any]:
        outcome = state["outcomes"].get(task_id)
        if outcome is None:
            raise KeyError(task_id)
        return outcome

    def claim_local(self, task_id: str, worker_id: str, *, idempotency_key: str,
                    ttl: float = 60.0) -> Lease:
        if ttl <= 0 or not worker_id or not idempotency_key:
            raise ValueError("worker_id, idempotency_key and positive ttl are required")
        with self._lock:
            state = self._state(self._replay())
            if state["stopped"]:
                raise QueueConflict("queue is stopped")
            outcome = self._require_outcome(state, task_id)
            task = self._queue.task(task_id)
            dependencies = (task.get("payload") or {}).get("depends_on", [])
            for dependency in dependencies:
                dependency_state = state["outcomes"].get(str(dependency), {})
                if dependency_state.get("outcome") != "verified_success":
                    raise QueueConflict("task dependencies are not verified")
            lease = self._queue.claim(
                task_id, worker_id, idempotency_key=idempotency_key, ttl=ttl,
                identity={"agent_id": worker_id},
            )
            old = outcome["outcome"]
            outcome.update({"outcome": "running", "lease": self._lease_dict(lease), "updated_at": time.time()})
            self._transition(state, task_id, old, "running", {"fence": lease.fencing_token})
            self._commit(self._replay(), state)
            return lease

    def persist_intent(self, lease: Lease, intent: Mapping[str, Any]) -> dict[str, Any]:
        value = {"schema": SCHEMA, "task_id": lease.task_id, "fence": lease.fencing_token,
                 "intent": dict(intent), "created_ns": time.time_ns()}
        value["digest"] = _digest(value)
        with self._lock:
            state = self._state(self._replay())
            self._queue.assert_active(lease)
            outcome = self._require_outcome(state, lease.task_id)
            outcome.update({"intent": value, "updated_at": time.time()})
            self._commit(self._replay(), state)
        return value

    def record_outcome(self, lease: Lease, outcome: str, *, receipt: Mapping[str, Any] | None = None,
                       provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if outcome not in OUTCOMES - {"never_started", "running"}:
            raise ValueError("unsafe outcome")
        if outcome == "verified_success" and receipt is None:
            raise QueueConflict("verified success requires receipt")
        if outcome == "retryable_failure" and not provenance:
            raise QueueConflict("retry requires idempotency provenance")
        value = {"schema": SCHEMA, "task_id": lease.task_id, "fence": lease.fencing_token,
                 "outcome": outcome, "receipt": dict(receipt or {}),
                 "provenance": dict(provenance or {}), "created_ns": time.time_ns()}
        value["digest"] = _digest(value)
        with self._lock:
            state = self._state(self._replay())
            self._queue.assert_active(lease)
            current = self._require_outcome(state, lease.task_id)
            if current["outcome"] in {"verified_success", "blocked", "dead_letter"}:
                raise QueueConflict("terminal outcome is immutable")
            old = current["outcome"]
            current.update({"outcome": outcome, "receipt": value,
                            "provenance": dict(provenance) if provenance else None,
                            "updated_at": time.time()})
            self._transition(state, lease.task_id, old, outcome, {"fence": lease.fencing_token})
            if outcome in {"verified_success", "dead_letter"}:
                supplied = build_mapper_completion_receipt(
                    task_id=lease.task_id, agent_id=lease.agent_id,
                    fencing_token=str(lease.fencing_token), receipt_ref=f"local:{lease.task_id}",
                    detail=receipt,
                )
                self._queue.complete(lease, receipt_ref=f"local:{lease.task_id}", receipt=supplied)
            elif outcome in {"blocked", "retryable_failure"}:
                self._queue.release(lease, reason=outcome)
            self._commit(self._replay(), state)
        return value

    def reconcile_unknown(self, task_id: str, *, verified: bool,
                          receipt: Mapping[str, Any] | None = None,
                          provenance: Mapping[str, Any] | None = None) -> None:
        target = "verified_success" if verified else "retryable_failure"
        if verified and receipt is None:
            raise QueueConflict("verified reconciliation requires receipt")
        if not verified and not provenance:
            raise QueueConflict("retry reconciliation requires idempotency provenance")
        with self._lock:
            state = self._state(self._replay())
            current = self._require_outcome(state, task_id)
            if current["outcome"] != "unknown_outcome":
                raise QueueConflict("task does not require reconciliation")
            if not verified:
                lease = self._lease(current.get("lease"))
                if lease is not None:
                    try:
                        if lease.expires_at > time.time():
                            self._queue.release(lease, reason="unknown-reconciled-for-retry")
                        else:
                            self._operations.reclaim_expired()
                    except QueueConflict:
                        self._operations.reclaim_expired()
            old = current["outcome"]
            current.update({"outcome": target, "receipt": dict(receipt) if receipt else None,
                            "provenance": dict(provenance) if provenance else None,
                            "updated_at": time.time()})
            self._transition(state, task_id, old, target)
            self._commit(self._replay(), state)

    def stop(self) -> None:
        with self._lock:
            state = self._state(self._replay())
            state["stopped"] = True
            for task_id, outcome in state["outcomes"].items():
                if outcome["outcome"] == "running":
                    try:
                        self._queue.request_cancel(task_id, reason="queue_stopped")
                    except (QueueConflict, KeyError):
                        pass
            self._commit(self._replay(), state)

    def cancel_local(self, task_id: str, *, reason: str = "operator_cancelled") -> dict[str, Any]:
        with self._lock:
            state = self._state(self._replay())
            current = self._require_outcome(state, task_id)
            if current["outcome"] in {"verified_success", "blocked", "dead_letter"}:
                raise QueueConflict("terminal outcome is immutable")
            lease = self._lease(current.get("lease"))
            if lease is not None and current["outcome"] == "running" and lease.expires_at > time.time():
                self._queue.request_cancel(task_id, reason=reason)
                return {"schema": SCHEMA, "task_id": task_id, "status": "cancelling"}
            old = current["outcome"]
            current.update({"outcome": "blocked", "updated_at": time.time()})
            self._transition(state, task_id, old, "blocked", {"reason": reason})
            self._commit(self._replay(), state)
            return {"schema": SCHEMA, "task_id": task_id, "status": "cancelled"}

    def reclaim_stale(self, *, now: float | None = None) -> list[str]:
        current_time = time.time() if now is None else float(now)
        reclaimed: list[str] = []
        with self._lock:
            state = self._state(self._replay())
            for task_id, outcome in state["outcomes"].items():
                lease = self._lease(outcome.get("lease"))
                if outcome["outcome"] != "running" or lease is None or lease.expires_at > current_time:
                    continue
                # The projection cannot reclaim capacity by itself.  Release
                # a still-live Mapper lease (important for deterministic
                # recovery tests that pass a synthetic ``now``), or let the
                # canonical operations store reclaim leases that have really
                # expired according to its own clock.
                try:
                    if lease.expires_at > time.time():
                        self._queue.release(lease, reason="lease_expired")
                    else:
                        self._operations.reclaim_expired()
                except QueueConflict:
                    self._operations.reclaim_expired()
                old = outcome["outcome"]
                outcome.update({"outcome": "unknown_outcome", "updated_at": current_time})
                self._transition(state, task_id, old, "unknown_outcome", {"reason": "lease_expired"})
                reclaimed.append(task_id)
            if reclaimed:
                self._commit(self._replay(), state)
        return sorted(reclaimed)

    def drain(self, *, timeout: float = 0.0) -> dict[str, Any]:
        self.stop()
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                state = self._state(self._replay())
                active = sum(
                    1 for item in state["outcomes"].values()
                    if item["outcome"] == "running"
                    and (self._lease(item.get("lease")) or Lease("", "", "", "", 0, "")).expires_at > time.time()
                )
            if active == 0 or time.monotonic() >= deadline:
                return {"schema": SCHEMA, "status": "drained" if active == 0 else "cancelling", "active": active}
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    def resume(self) -> None:
        with self._lock:
            state = self._state(self._replay())
            state["stopped"] = False
            self._commit(self._replay(), state)

    def status_local(self) -> dict[str, Any]:
        state = self._state(self._replay())
        counts: dict[str, int] = {}
        for item in state["outcomes"].values():
            counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
        return {"schema": SCHEMA, "stopped": bool(state["stopped"]), "outcomes": counts,
                "journal_mode": "mapper-store"}

    def top(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._queue.pull("operator", limit=limit)

    def inspect_local(self, task_id: str) -> dict[str, Any]:
        state = self._state(self._replay())
        outcome = self._require_outcome(state, task_id)
        return {"schema": SCHEMA, "task": self.task(task_id), "outcome": dict(outcome),
                "transitions": [dict(item) for item in state["transitions"] if item["task_id"] == task_id]}

    def doctor_local(self) -> dict[str, Any]:
        try:
            replay = self._replay()
            state = self._state(replay)
            corrupt: list[int] = []
            for item in state["transitions"]:
                value = json.loads(item["payload"])
                if (value.get("schema") != SCHEMA or value.get("task_id") != item["task_id"]
                        or value.get("from") != item["from_state"] or value.get("to") != item["to_state"]
                        or _digest(value) != item["digest"]):
                    corrupt.append(int(item["seq"]))
            return {"schema": SCHEMA, "healthy": bool(replay.get("valid")) and not corrupt,
                    "integrity": "mapper-store", "missing_outcomes": [],
                    "corrupt_transitions": corrupt, "corrupt_records": []}
        except (TypeError, ValueError, json.JSONDecodeError, QueueUnavailable) as error:
            return {"schema": SCHEMA, "healthy": False, "error": str(error)}

    def migrate(self, *, dry_run: bool = True) -> dict[str, Any]:
        return {"schema": SCHEMA, "dry_run": dry_run, "backup": None,
                "from_schema": SCHEMA, "migrated_records": 0, "migrated_provenance": 0}

    def task(self, task_id: str) -> dict[str, Any]:
        return self._queue.task(task_id)

    def gc_terminal(self, *, apply: bool = False) -> dict[str, Any]:
        state = self._state(self._replay())
        eligible = sorted(
            task_id for task_id, outcome in state["outcomes"].items()
            if outcome["outcome"] in {"verified_success", "dead_letter"}
        )
        if apply and eligible:
            with self._lock:
                state = self._state(self._replay())
                for task_id in eligible:
                    state["outcomes"].pop(task_id, None)
                    state["transitions"] = [item for item in state["transitions"] if item["task_id"] != task_id]
                self._commit(self._replay(), state)
        return {"schema": SCHEMA, "eligible": eligible, "removed": eligible if apply else []}
