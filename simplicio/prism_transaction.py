"""Envelope-bound EffectTransaction with fencing and exactly-once (#381)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplicio_mapper.mapper.file_lock import acquire_lock_at, release_lock_at

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
        self.store_dir = self.root / ".simplicio" / "mapper-store" / "prism-transactions"
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, tx_key: str) -> Path:
        return self.store_dir / f"{hashlib.sha256(tx_key.encode()).hexdigest()}.json"

    def _lock_path(self, tx_key: str) -> Path:
        return self.store_dir / f"{hashlib.sha256(tx_key.encode()).hexdigest()}.lock"

    def _read(self, tx_key: str) -> dict[str, Any] | None:
        path = self._record_path(tx_key)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EffectTransactionError("RECOVERY_REQUIRED") from exc
        if not isinstance(value, dict):
            raise EffectTransactionError("RECOVERY_REQUIRED")
        return value

    def _write(self, tx_key: str, value: dict[str, Any]) -> None:
        target = self._record_path(tx_key)
        temporary = target.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))

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
        row = self._read(tx_key)
        if row and row.get("state") == "COMMITTED" and row.get("receipt"):
            return dict(row["receipt"])
        if row and row.get("state") in _TERMINAL:
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
        lock = acquire_lock_at(str(self._lock_path(tx_key)), operation="prism-transaction")
        if lock is None:
            raise EffectTransactionError("RECOVERY_REQUIRED")
        try:
            row = self._read(tx_key) or {
                "tx_key": tx_key,
                "envelope_hash": envelope.envelope_hash(),
                "receipt": None,
            }
            row["state"] = state
            if receipt is not None:
                row["receipt"] = receipt
            self._write(tx_key, row)
        finally:
            release_lock_at(lock)
