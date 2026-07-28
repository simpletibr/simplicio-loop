"""Fail-closed Stage ABI mutation worker for MechanicalPlanV1."""
from __future__ import annotations
import hashlib, json, os, sqlite3
from pathlib import Path
from typing import Any, Callable

SCHEMA = "simplicio.mechanical-plan/v1"
RECEIPT = "simplicio.mutation-receipt/v1"

class MutationBlocked(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def validate(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    required = ("schema", "plan_id", "source_hash", "idempotency_key", "operations",
                "effect_set", "hookwall_pre")
    if any(not plan.get(key) for key in required) or plan["schema"] != SCHEMA:
        raise MutationBlocked("MECHANICAL_PLAN_INVALID")
    pre = plan["hookwall_pre"]
    if pre.get("verdict") != "proceed" or pre.get("plan_id") != plan["plan_id"]:
        raise MutationBlocked(pre.get("reason_code") or "HOOKWALL_PRE_REQUIRED")
    normalized = dict(plan)
    for operation in plan["operations"]:
        value = operation.get("path")
        if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
            raise MutationBlocked("PATH_ESCAPE")
        candidate = (root.resolve() / value).resolve()
        try: candidate.relative_to(root.resolve())
        except ValueError as exc: raise MutationBlocked("SYMLINK_ESCAPE") from exc
    normalized["plan_hash"] = digest({k: normalized[k] for k in normalized if k != "plan_hash"})
    if plan.get("plan_hash") and plan["plan_hash"] != normalized["plan_hash"]:
        raise MutationBlocked("PLAN_TAMPERED")
    return normalized

class MutationWorker:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.db_path = self.root / ".simplicio" / "mutation-worker.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS mutations(key TEXT PRIMARY KEY, plan_hash TEXT, state TEXT, receipt TEXT)")
    def _db(self):
        db = sqlite3.connect(self.db_path, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL")
        return db
    def execute(self, plan: dict[str, Any], executor: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        sealed = validate(plan, self.root); key = sealed["idempotency_key"]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT plan_hash,state,receipt FROM mutations WHERE key=?", (key,)).fetchone()
            if row:
                db.execute("COMMIT")
                if row[0] != sealed["plan_hash"]: raise MutationBlocked("IDEMPOTENCY_LINEAGE_MISMATCH")
                if row[1] == "VERIFIED": return json.loads(row[2])
                raise MutationBlocked("RECOVERY_REQUIRED")
            db.execute("INSERT INTO mutations VALUES(?,?,?,NULL)", (key, sealed["plan_hash"], "RESERVED"))
            db.execute("COMMIT")
        try:
            result = executor(sealed)
        except BaseException:
            with self._db() as db: db.execute("UPDATE mutations SET state='UNCERTAIN' WHERE key=?", (key,))
            raise
        if result.get("status") != "ok" or not result.get("applied"):
            with self._db() as db: db.execute("UPDATE mutations SET state='ROLLED_BACK' WHERE key=?", (key,))
            raise MutationBlocked("EFFECT_NOT_COMMITTED")
        receipt = {"schema": RECEIPT, "plan_id": sealed["plan_id"], "plan_hash": sealed["plan_hash"],
                   "idempotency_key": key, "before_hash": result["before_hash"],
                   "after_hash": result["after_hash"], "status": "committed",
                   "operations": result.get("operations", [])}
        receipt["receipt_hash"] = digest(receipt)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE mutations SET state='VERIFIED',receipt=? WHERE key=?", (json.dumps(receipt, sort_keys=True), key))
            db.execute("COMMIT")
        return receipt
