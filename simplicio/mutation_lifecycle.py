"""Recovery, verification and rollback lifecycle for the Stage ABI worker."""
from __future__ import annotations
import json
from typing import Any, Callable
from .mutation_worker import MutationBlocked, MutationWorker, RECEIPT, digest

MUTABLE_ENTRYPOINTS = {
    "index", "task", "run", "cache.clear", "init", "env-export", "mechanical-edit",
    "changeset", "edit", "test.run", "prototype.apply", "prototype.scaffold",
    "prototype.plan", "prototype.promote", "prototype.reject", "prototype.batch",
    "memory.init", "memory.store", "memory.handoff",
    "token.context-cache.put", "token.context-cache.invalidate",
}

def verify_receipt(receipt: dict[str, Any]) -> bool:
    if receipt.get("schema") != RECEIPT:
        return False
    supplied = receipt.get("receipt_hash")
    return isinstance(supplied, str) and supplied == digest(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )

def recover(worker: MutationWorker, key: str, observer: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    with worker._db() as db:
        row = db.execute("SELECT plan_hash,state,receipt FROM mutations WHERE key=?", (key,)).fetchone()
    if not row or row[1] not in {"RESERVED", "UNCERTAIN"}:
        raise MutationBlocked("RECOVERY_NOT_REQUIRED")
    observed = observer()
    if observed.get("status") == "committed":
        receipt = {"schema": RECEIPT, "plan_id": observed["plan_id"], "plan_hash": row[0],
                   "idempotency_key": key, "before_hash": observed["before_hash"],
                   "after_hash": observed["after_hash"], "status": "committed",
                   "operations": observed.get("operations", [])}
        receipt["receipt_hash"] = digest(receipt)
        with worker._db() as db:
            db.execute("UPDATE mutations SET state='VERIFIED',receipt=? WHERE key=?",
                       (json.dumps(receipt, sort_keys=True), key))
        return receipt
    raise MutationBlocked("RECOVERY_OBSERVATION_INSUFFICIENT")

def rollback(worker: MutationWorker, key: str,
             restorer: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    with worker._db() as db:
        row = db.execute("SELECT state,receipt FROM mutations WHERE key=?", (key,)).fetchone()
    if not row or row[0] not in {"VERIFIED", "UNCERTAIN"}:
        raise MutationBlocked("ROLLBACK_NOT_ALLOWED")
    prior = json.loads(row[1]) if row[1] else {}
    result = restorer(prior)
    if result.get("status") != "restored":
        raise MutationBlocked("ROLLBACK_UNVERIFIED")
    receipt = {"schema": "simplicio.rollback-receipt/v1", "idempotency_key": key,
               "mutation_receipt_hash": prior.get("receipt_hash"),
               "restored_hash": result["restored_hash"], "status": "restored"}
    receipt["receipt_hash"] = digest(receipt)
    with worker._db() as db:
        db.execute("UPDATE mutations SET state='ROLLED_BACK',receipt=? WHERE key=?",
                   (json.dumps(receipt, sort_keys=True), key))
    return receipt
