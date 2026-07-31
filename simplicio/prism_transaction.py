"""Envelope-bound EffectTransaction with fencing and exactly-once (#381)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplicio.effect_transaction import EffectTransaction, EffectTransactionError
from simplicio.plan_compiler import ChangeSet, canonical_hash
from simplicio.prism_envelope import PrismExecutionEnvelope
from simplicio.write_set_lock import LockError, WriteSetLockManager

_TERMINAL = frozenset({"COMMITTED", "ROLLED_BACK", "FAILED_BEFORE_WRITE", "FENCE_LOST", "CONFLICT_BLOCKED"})


class PrismTransaction:
    """Exactly-once task execution under a PrismExecutionEnvelope."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.locks = WriteSetLockManager(self.root)
        self.inner = EffectTransaction(self.root)
        state = self.root / ".simplicio"
        state.mkdir(parents=True, exist_ok=True)
        self.db_path = state / "prism-transactions.sqlite3"
        with self._db() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS prism_tx(
                    tx_key TEXT PRIMARY KEY,
                    envelope_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    receipt TEXT
                );
                """
            )

    def _db(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        database.execute("PRAGMA journal_mode=WAL")
        return database

    def _tx_key(self, envelope: PrismExecutionEnvelope) -> str:
        return canonical_hash(
            {
                "envelope_hash": envelope.envelope_hash(),
                "lease_id": envelope.lease_id,
                "fence_token": envelope.fence_token,
                "task_id": envelope.task_id,
                "attempt_id": envelope.attempt_id,
            }
        )

    def execute(
        self,
        envelope: PrismExecutionEnvelope,
        change_set: ChangeSet,
        *,
        active_fence: str,
        checkpoint: Callable[[ChangeSet], dict[str, Any]],
        apply: Callable[[ChangeSet], dict[str, Any]],
        verify: Callable[[ChangeSet, dict[str, Any]], dict[str, Any]],
        rollback: Callable[[ChangeSet, dict[str, Any]], dict[str, Any]],
        now_ns: int | None = None,
    ) -> dict[str, Any]:
        envelope.validate(now_ns=now_ns)
        change_set.validate()
        if not envelope.binds_change_set(change_set.canonical_hash()):
            raise EffectTransactionError("ENVELOPE_CHANGESET_MISMATCH")
        if active_fence != envelope.fence_token:
            self._store(envelope, "FENCE_LOST", None)
            raise EffectTransactionError("FENCE_LOST")

        tx_key = self._tx_key(envelope)
        with self._db() as database:
            row = database.execute(
                "SELECT state,receipt FROM prism_tx WHERE tx_key=?",
                (tx_key,),
            ).fetchone()
            if row and row[0] == "COMMITTED" and row[1]:
                return dict(json.loads(row[1]))
            if row and row[0] in _TERMINAL:
                raise EffectTransactionError("TRANSACTION_TERMINAL")

        try:
            self.locks.acquire(
                change_set.write_set,
                owner=envelope.owner_agent_id,
                lease_id=envelope.lease_id,
                fencing_token=envelope.fence_token,
                active_fence=active_fence,
            )
        except LockError as exc:
            self._store(envelope, "CONFLICT_BLOCKED", {"reason": exc.reason_code})
            raise EffectTransactionError(exc.reason_code) from exc

        def gated_checkpoint(cs: ChangeSet) -> dict[str, Any]:
            self.locks.validate_fence(active_fence, expected=envelope.fence_token)
            return checkpoint(cs)

        def gated_apply(cs: ChangeSet) -> dict[str, Any]:
            self.locks.validate_fence(active_fence, expected=envelope.fence_token)
            return apply(cs)

        def gated_verify(cs: ChangeSet, effect: dict[str, Any]) -> dict[str, Any]:
            self.locks.validate_fence(active_fence, expected=envelope.fence_token)
            return verify(cs, effect)

        try:
            receipt = self.inner.execute(
                change_set,
                checkpoint=gated_checkpoint,
                apply=gated_apply,
                verify=gated_verify,
                rollback=rollback,
            )
        except LockError as exc:
            self._store(envelope, "FENCE_LOST", {"reason": exc.reason_code})
            raise EffectTransactionError("FENCE_LOST") from exc
        finally:
            self.locks.release(owner=envelope.owner_agent_id, lease_id=envelope.lease_id)

        enriched = {
            **receipt,
            "schema": "simplicio.prism-effect-receipt/v1",
            "envelope_hash": envelope.envelope_hash(),
            "prism_id": envelope.prism_id,
            "slot_id": envelope.slot_id,
            "task_id": envelope.task_id,
            "owner_agent_id": envelope.owner_agent_id,
            "attempt_id": envelope.attempt_id,
            "lease_id": envelope.lease_id,
            "fence_token": envelope.fence_token,
            "task_facts_digest": envelope.task_facts_digest,
            "context_graph_digest": envelope.context_graph_digest,
            "trace_id": envelope.trace_id,
        }
        enriched["receipt_hash"] = canonical_hash(enriched)
        self._store(envelope, "COMMITTED", enriched)
        return enriched

    def _store(
        self,
        envelope: PrismExecutionEnvelope,
        state: str,
        receipt: dict[str, Any] | None,
    ) -> None:
        tx_key = self._tx_key(envelope)
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")) if receipt else None
        with self._db() as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "INSERT INTO prism_tx(tx_key,envelope_hash,state,receipt) VALUES(?,?,?,?) "
                "ON CONFLICT(tx_key) DO UPDATE SET state=excluded.state, "
                "receipt=COALESCE(excluded.receipt, prism_tx.receipt)",
                (tx_key, envelope.envelope_hash(), state, encoded),
            )
            database.execute("COMMIT")
