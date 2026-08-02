"""Recoverable, idempotent execution boundary for ChangeSet/v1."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplicio.plan_compiler import ChangeSet, canonical_hash
from simplicio.store_adapter import MapperStoreAdapter, StoreAdapterError

EFFECT_RECEIPT_SCHEMA = "simplicio.effect-receipt/v1"
_TERMINAL = frozenset({"COMMITTED", "ROLLED_BACK", "FAILED_BEFORE_WRITE"})
_LOCK_RETRIES = 100
_LOCK_RETRY_DELAY_SECONDS = 0.01


class EffectTransactionError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class EffectTransaction:
    """Journal one gate -> checkpoint -> edit -> validate -> receipt transaction."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.store = MapperStoreAdapter(self.root, "effect-transactions")
        self._execution_locks: dict[str, threading.Lock] = {}
        self._execution_locks_guard = threading.Lock()

    def _execution_lock(self, key: str) -> threading.Lock:
        with self._execution_locks_guard:
            return self._execution_locks.setdefault(key, threading.Lock())

    def _read_record(self, key: str) -> dict[str, Any] | None:
        try:
            return self.store.read(key)
        except StoreAdapterError as exc:
            raise EffectTransactionError("RECOVERY_REQUIRED") from exc

    def _write_record(self, key: str, record: dict[str, Any]) -> None:
        try:
            self.store.write(key, record)
        except StoreAdapterError as exc:
            raise EffectTransactionError("STORE_WRITE_FAILED") from exc

    def _locked(self, key: str, *, retry: bool = True):
        attempts = _LOCK_RETRIES if retry else 1
        for attempt in range(attempts):
            try:
                return self.store.acquire(key, operation="effect-transaction")
            except StoreAdapterError as exc:
                if str(exc) != "STORE_LOCKED" or attempt == attempts - 1:
                    raise EffectTransactionError("RECOVERY_REQUIRED") from exc
                time.sleep(_LOCK_RETRY_DELAY_SECONDS)
        raise EffectTransactionError("RECOVERY_REQUIRED")

    def _transition(self, key: str, state: str, receipt: dict[str, Any] | None = None) -> None:
        lock = self._locked(key)
        try:
            record = self._read_record(key)
            if record is None:
                raise EffectTransactionError("RECOVERY_REQUIRED")
            record["state"] = state
            if receipt is not None:
                record["receipt"] = receipt
            record.setdefault("transitions", []).append({"state": state, "observed_ns": time.time_ns()})
            self._write_record(key, record)
        finally:
            self.store.release(lock)

    def transitions(self, key: str) -> list[str]:
        record = self._read_record(key)
        if record is None:
            return []
        return [str(item["state"]) for item in record.get("transitions", [])]

    def _reserve(self, change_set: ChangeSet) -> dict[str, Any] | None:
        key = change_set.idempotency_key
        digest = change_set.canonical_hash()
        lock = self._locked(key, retry=False)
        try:
            row = self._read_record(key)
            if row:
                if row.get("change_set_hash") != digest:
                    raise EffectTransactionError("IDEMPOTENCY_LINEAGE_MISMATCH")
                if row.get("state") == "COMMITTED" and row.get("receipt"):
                    return dict(row["receipt"])
                raise EffectTransactionError(
                    "TRANSACTION_TERMINAL" if row.get("state") in _TERMINAL else "RECOVERY_REQUIRED"
                )
            self._write_record(
                key,
                {
                    "idempotency_key": key,
                    "change_set_hash": digest,
                    "state": "GATED",
                    "receipt": None,
                    "transitions": [{"state": "GATED", "observed_ns": time.time_ns()}],
                },
            )
        finally:
            self.store.release(lock)
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
        with self._execution_lock(change_set.idempotency_key):
            return self._execute(
                change_set,
                checkpoint=checkpoint,
                apply=apply,
                verify=verify,
                rollback=rollback,
            )

    def _execute(
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
