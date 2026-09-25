"""Fail-closed Stage ABI mutation worker for MechanicalPlanV1."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplicio.store_adapter import MapperStoreAdapter, StoreAdapterError

SCHEMA = "simplicio.mechanical-plan/v1"
RECEIPT = "simplicio.mutation-receipt/v1"


class MutationBlocked(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    required = (
        "schema",
        "plan_id",
        "source_hash",
        "idempotency_key",
        "operations",
        "effect_set",
        "hookwall_pre",
    )
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
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise MutationBlocked("SYMLINK_ESCAPE") from exc
    normalized["plan_hash"] = digest({k: normalized[k] for k in normalized if k != "plan_hash"})
    if plan.get("plan_hash") and plan["plan_hash"] != normalized["plan_hash"]:
        raise MutationBlocked("PLAN_TAMPERED")
    return normalized


class MutationWorker:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.store = MapperStoreAdapter(self.root, "mutations")

    def _read(self, key: str) -> dict[str, Any] | None:
        try:
            return self.store.read(key)
        except StoreAdapterError as exc:
            raise MutationBlocked("RECOVERY_REQUIRED") from exc

    def _write(self, key: str, value: dict[str, Any]) -> None:
        try:
            self.store.write(key, value)
        except StoreAdapterError as exc:
            raise MutationBlocked("STORE_WRITE_FAILED") from exc

    def _locked(self, key: str):
        try:
            return self.store.acquire(key, operation="mutation-worker")
        except StoreAdapterError as exc:
            raise MutationBlocked("RECOVERY_REQUIRED") from exc

    def execute(
        self, plan: dict[str, Any], executor: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> dict[str, Any]:
        sealed = validate(plan, self.root)
        key = sealed["idempotency_key"]
        lock = self._locked(key)
        try:
            row = self._read(key)
            if row:
                if row.get("plan_hash") != sealed["plan_hash"]:
                    raise MutationBlocked("IDEMPOTENCY_LINEAGE_MISMATCH")
                if row.get("state") == "VERIFIED" and row.get("receipt"):
                    return dict(row["receipt"])
                raise MutationBlocked("RECOVERY_REQUIRED")
            self._write(
                key,
                {"key": key, "plan_hash": sealed["plan_hash"], "state": "RESERVED", "receipt": None},
            )
        finally:
            self.store.release(lock)
        try:
            result = executor(sealed)
        except BaseException:
            lock = self._locked(key)
            try:
                row = self._read(key) or {"key": key, "plan_hash": sealed["plan_hash"], "receipt": None}
                row["state"] = "UNCERTAIN"
                self._write(key, row)
            finally:
                self.store.release(lock)
            raise
        if result.get("status") != "ok" or not result.get("applied"):
            lock = self._locked(key)
            try:
                row = self._read(key) or {"key": key, "plan_hash": sealed["plan_hash"], "receipt": None}
                row["state"] = "ROLLED_BACK"
                self._write(key, row)
            finally:
                self.store.release(lock)
            raise MutationBlocked("EFFECT_NOT_COMMITTED")
        receipt = {
            "schema": RECEIPT,
            "plan_id": sealed["plan_id"],
            "plan_hash": sealed["plan_hash"],
            "idempotency_key": key,
            "before_hash": result["before_hash"],
            "after_hash": result["after_hash"],
            "status": "committed",
            "operations": result.get("operations", []),
        }
        receipt["receipt_hash"] = digest(receipt)
        lock = self._locked(key)
        try:
            row = self._read(key) or {"key": key, "plan_hash": sealed["plan_hash"]}
            row.update({"state": "VERIFIED", "receipt": receipt})
            self._write(key, row)
        finally:
            self.store.release(lock)
        return receipt
