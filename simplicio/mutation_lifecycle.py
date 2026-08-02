"""Recovery, verification and rollback lifecycle for the Stage ABI worker."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


from .mutation_worker import RECEIPT, MutationBlocked, MutationWorker, digest

MUTABLE_ENTRYPOINTS = {
    "index",
    "task",
    "run",
    "cache.clear",
    "init",
    "env-export",
    "mechanical-edit",
    "changeset",
    "edit",
    "test.run",
    "prototype.apply",
    "prototype.scaffold",
    "prototype.plan",
    "prototype.promote",
    "prototype.reject",
    "prototype.batch",
    "memory.init",
    "memory.store",
    "memory.handoff",
    "token.context-cache.put",
    "token.context-cache.invalidate",
}


def verify_receipt(receipt: dict[str, Any]) -> bool:
    if receipt.get("schema") != RECEIPT:
        return False
    supplied = receipt.get("receipt_hash")
    return isinstance(supplied, str) and supplied == digest(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )


def recover(worker: MutationWorker, key: str, observer: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    row = worker._read(key)
    if not row or row.get("state") not in {"RESERVED", "UNCERTAIN"}:
        raise MutationBlocked("RECOVERY_NOT_REQUIRED")
    observed = observer()
    if observed.get("status") == "committed":
        receipt = {
            "schema": RECEIPT,
            "plan_id": observed["plan_id"],
            "plan_hash": row["plan_hash"],
            "idempotency_key": key,
            "before_hash": observed["before_hash"],
            "after_hash": observed["after_hash"],
            "status": "committed",
            "operations": observed.get("operations", []),
        }
        receipt["receipt_hash"] = digest(receipt)
        lock = worker._locked(key)
        try:
            current = worker._read(key) or {"key": key, "plan_hash": row["plan_hash"]}
            current.update({"state": "VERIFIED", "receipt": receipt})
            worker._write(key, current)
        finally:
            worker.store.release(lock)
        return receipt
    raise MutationBlocked("RECOVERY_OBSERVATION_INSUFFICIENT")


def rollback(
    worker: MutationWorker, key: str, restorer: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any]:
    row = worker._read(key)
    if not row or row.get("state") not in {"VERIFIED", "UNCERTAIN"}:
        raise MutationBlocked("ROLLBACK_NOT_ALLOWED")
    prior = row.get("receipt") or {}
    result = restorer(prior)
    if result.get("status") != "restored":
        raise MutationBlocked("ROLLBACK_UNVERIFIED")
    receipt = {
        "schema": "simplicio.rollback-receipt/v1",
        "idempotency_key": key,
        "mutation_receipt_hash": prior.get("receipt_hash"),
        "restored_hash": result["restored_hash"],
        "status": "restored",
    }
    receipt["receipt_hash"] = digest(receipt)
    lock = worker._locked(key)
    try:
        current = worker._read(key) or {"key": key, "plan_hash": row.get("plan_hash", "")}
        current.update({"state": "ROLLED_BACK", "receipt": receipt})
        worker._write(key, current)
    finally:
        worker.store.release(lock)
    return receipt
