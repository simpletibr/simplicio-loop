"""Contract-tested deterministic plan/edit/receipt reconciliation slice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .mechanical_edit import execute_plan
from .standalone_migration import load_effect_unknown_lock

PLAN_SCHEMA = "simplicio.dev-cli.plan/v1"
DRY_RUN_SCHEMA = "simplicio.dev-cli.dry-run/v1"
RECEIPT_SCHEMA = "simplicio.dev-cli.receipt/v1"
RECONCILE_SCHEMA = "simplicio.dev-cli.reconcile/v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"unsafe path: {relative}")
    return candidate


def _preconditions(root: Path, plan: dict[str, Any]) -> dict[str, str | None]:
    paths = list(plan.get("touched_files", plan.get("files", [])))
    for operation in plan.get("operations", []):
        if isinstance(operation, dict):
            for key in ("path", "dest"):
                if isinstance(operation.get(key), str):
                    paths.append(operation[key])
    result: dict[str, str | None] = {}
    for relative in sorted({str(path) for path in paths}):
        target = _path(root, relative)
        result[relative] = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
    return result


def compile_plan(plan: dict[str, Any], *, root: str | Path, idempotency_key: str) -> dict[str, Any]:
    """Validate and bind a mechanical plan without writing or spawning."""
    root_path = Path(root).resolve()
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    preview = execute_plan(plan, root=root_path, apply=False, allow_native=False)
    digest = _digest(plan)
    base = {
        "schema": PLAN_SCHEMA,
        "idempotency_key": idempotency_key,
        "plan_digest": digest,
        "effect_digest": digest,
        "preconditions": _preconditions(root_path, plan),
        "provenance": {"producer": "simplicio-dev-cli", "operator": "native-deterministic"},
    }
    if preview.get("status") != "ok":
        return base | {"status": "blocked", "errors": preview.get("errors", [])}
    return base | {"status": "planned", "plan": plan}


def dry_run(plan_envelope: dict[str, Any], *, root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    plan = plan_envelope.get("plan")
    if not isinstance(plan, dict) or plan_envelope.get("schema") != PLAN_SCHEMA:
        return {"schema": DRY_RUN_SCHEMA, "status": "blocked", "reason": "invalid_plan_envelope"}
    result = execute_plan(plan, root=root_path, apply=False, allow_native=False)
    return {
        "schema": DRY_RUN_SCHEMA,
        "status": "dry_run" if result.get("status") == "ok" else "blocked",
        "applied": False,
        "idempotency_key": plan_envelope.get("idempotency_key"),
        "plan_digest": plan_envelope.get("plan_digest"),
        "effect_digest": plan_envelope.get("effect_digest", plan_envelope.get("plan_digest")),
        "preconditions": plan_envelope.get("preconditions", {}),
        "planned_diff": result.get("planned_diff", ""),
        "files": result.get("files", []),
        "errors": result.get("errors", []),
        "provenance": plan_envelope.get("provenance", {}),
    }


def _receipt_path(root: Path, key: str) -> Path:
    return root / ".simplicio" / "dev-cli-receipts" / f"{_digest(key)[:32]}.json"


def apply(plan_envelope: dict[str, Any], *, root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    plan = plan_envelope.get("plan")
    key = str(plan_envelope.get("idempotency_key", ""))
    if plan_envelope.get("schema") != PLAN_SCHEMA or not isinstance(plan, dict) or not key:
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "invalid_plan_envelope"}
    if _digest(plan) != plan_envelope.get("plan_digest"):
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "plan_digest_mismatch"}
    receipt_path = _receipt_path(root_path, key)
    if receipt_path.is_file():
        prior = json.loads(receipt_path.read_text(encoding="utf-8"))
        if prior.get("plan_digest") != plan_envelope.get("plan_digest"):
            return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "idempotency_lineage_mismatch"}
        prior["replayed"] = True
        return prior
    expected = plan_envelope.get("preconditions", {})
    current = _preconditions(root_path, plan)
    if current != expected:
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "blocked",
            "reason": "preconditions_failed",
            "preconditions": {"expected": expected, "actual": current},
        }
    result = execute_plan(plan, root=root_path, apply=True, allow_native=False)
    status = "committed" if result.get("applied") else "failed"
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": status,
        "replayed": False,
        "idempotency_key": key,
        "plan_digest": plan_envelope.get("plan_digest"),
        "effect_digest": plan_envelope.get("effect_digest", plan_envelope.get("plan_digest")),
        "preconditions": expected,
        "files": result.get("files", []),
        "errors": result.get("errors", []),
        "provenance": plan_envelope.get("provenance", {}),
        "recovery_locator": str(receipt_path.relative_to(root_path)),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(_canonical(receipt) + "\n", encoding="utf-8")
    return receipt


def reconcile(*, root: str | Path, idempotency_key: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    path = _receipt_path(root_path, idempotency_key)
    if path.is_file():
        receipt = json.loads(path.read_text(encoding="utf-8"))
        return {
            "schema": RECONCILE_SCHEMA,
            "status": "reconciled",
            "outcome": receipt.get("status"),
            "receipt": receipt,
        }
    lock = load_effect_unknown_lock(str(root_path))
    if lock and lock.get("idempotency_key") == idempotency_key:
        return {
            "schema": RECONCILE_SCHEMA,
            "status": "unknown",
            "outcome": "effect_unknown",
            "recovery_locator": lock.get("evidence_file"),
        }
    return {"schema": RECONCILE_SCHEMA, "status": "failed", "outcome": "receipt_not_found"}
