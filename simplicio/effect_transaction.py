"""Recoverable, idempotent execution boundary for ChangeSet/v1."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplicio.plan_compiler import ChangeSet, canonical_hash

EFFECT_RECEIPT_SCHEMA = "simplicio.effect-receipt/v1"
_TERMINAL = frozenset({"COMMITTED", "ROLLED_BACK", "FAILED_BEFORE_WRITE"})


class EffectTransactionError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class EffectTransaction:
    """Journal one gate -> checkpoint -> edit -> validate -> receipt transaction."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        state_dir = self.root / ".simplicio"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "effect-transactions.sqlite3"
        with self._db() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS transactions(
                    idempotency_key TEXT PRIMARY KEY,
                    change_set_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    receipt TEXT
                );
                CREATE TABLE IF NOT EXISTS transitions(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    observed_ns INTEGER NOT NULL
                );
                """
            )

    def _db(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=FULL")
        return database

    def _transition(self, key: str, state: str, receipt: dict[str, Any] | None = None) -> None:
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")) if receipt else None
        with self._db() as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "UPDATE transactions SET state=?, receipt=COALESCE(?, receipt) WHERE idempotency_key=?",
                (state, encoded, key),
            )
            database.execute(
                "INSERT INTO transitions(idempotency_key,state,observed_ns) VALUES(?,?,?)",
                (key, state, time.time_ns()),
            )
            database.execute("COMMIT")

    def transitions(self, key: str) -> list[str]:
        with self._db() as database:
            rows = database.execute(
                "SELECT state FROM transitions WHERE idempotency_key=? ORDER BY sequence",
                (key,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def _reserve(self, change_set: ChangeSet) -> dict[str, Any] | None:
        key = change_set.idempotency_key
        digest = change_set.canonical_hash()
        with self._db() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT change_set_hash,state,receipt FROM transactions WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if row:
                database.execute("COMMIT")
                if row[0] != digest:
                    raise EffectTransactionError("IDEMPOTENCY_LINEAGE_MISMATCH")
                if row[1] == "COMMITTED" and row[2]:
                    return dict(json.loads(row[2]))
                raise EffectTransactionError(
                    "TRANSACTION_TERMINAL" if row[1] in _TERMINAL else "RECOVERY_REQUIRED"
                )
            database.execute(
                "INSERT INTO transactions VALUES(?,?,?,NULL)",
                (key, digest, "GATED"),
            )
            database.execute(
                "INSERT INTO transitions(idempotency_key,state,observed_ns) VALUES(?,?,?)",
                (key, "GATED", time.time_ns()),
            )
            database.execute("COMMIT")
        return None

    def execute(
        self,
        change_set: ChangeSet,
        *,
        checkpoint: Callable[[ChangeSet], dict[str, Any]],
        apply: Callable[[ChangeSet], dict[str, Any]],
        verify: Callable[[ChangeSet, dict[str, Any]], dict[str, Any]],
        rollback: Callable[[ChangeSet, dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute once; every non-success after write attempts verified rollback."""
        change_set.validate()
        replay = self._reserve(change_set)
        if replay is not None:
            return replay
        key = change_set.idempotency_key

        try:
            checkpoint_receipt = checkpoint(change_set)
        except BaseException:
            self._transition(key, "FAILED_BEFORE_WRITE")
            raise
        if not checkpoint_receipt.get("checkpoint_hash"):
            self._transition(key, "FAILED_BEFORE_WRITE")
            raise EffectTransactionError("CHECKPOINT_UNVERIFIED")
        self._transition(key, "CHECKPOINTED")

        try:
            effect = apply(change_set)
            self._transition(key, "EFFECT_OBSERVED")
            if effect.get("status") != "applied":
                raise EffectTransactionError("EFFECT_UNKNOWN")
            verification = verify(change_set, effect)
            self._transition(key, "VALIDATED")
            if verification.get("status") != "passed":
                raise EffectTransactionError("VERIFICATION_FAILED")
        except BaseException as error:
            self._transition(key, "ROLLBACK_PENDING")
            restored = rollback(change_set, checkpoint_receipt)
            if restored.get("status") != "restored":
                self._transition(key, "RECOVERY_REQUIRED")
                raise EffectTransactionError("ROLLBACK_UNVERIFIED") from error
            self._transition(key, "ROLLED_BACK")
            raise EffectTransactionError("EFFECT_FAILED_ROLLED_BACK") from error

        receipt: dict[str, Any] = {
            "schema": EFFECT_RECEIPT_SCHEMA,
            "idempotency_key": key,
            "change_set_hash": change_set.canonical_hash(),
            "checkpoint_hash": str(checkpoint_receipt["checkpoint_hash"]),
            "before_hash": effect.get("before_hash"),
            "after_hash": effect.get("after_hash"),
            "verification": verification,
            "status": "committed",
            "transitions": [*self.transitions(key), "COMMITTED"],
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        self._transition(key, "COMMITTED", receipt)
        return receipt
