"""Contract-tested deterministic plan/edit/receipt reconciliation slice."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .mapper_binding import (
    canonical_mapper_binding,
    mapper_binding_digest,
    validate_mapper_binding,
)
from .mechanical_edit import execute_plan
from .standalone_migration import load_effect_unknown_lock
from .utils.fs import write_text_atomic

PLAN_SCHEMA = "simplicio.dev-cli.plan/v1"
DRY_RUN_SCHEMA = "simplicio.dev-cli.dry-run/v1"
RECEIPT_SCHEMA = "simplicio.dev-cli.receipt/v1"
RECONCILE_SCHEMA = "simplicio.dev-cli.reconcile/v1"
_RECEIPT_LOCK_WAIT_SECONDS = 5.0
_RECEIPT_LOCK_POLL_SECONDS = 0.01


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalized_plan(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(plan)
    for key in ("touched_files", "files"):
        paths = normalized.get(key)
        if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
            normalized[key] = sorted(set(paths))
    operations = normalized.get("operations")
    if isinstance(operations, list) and all(isinstance(operation, dict) for operation in operations):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for operation in operations:
            grouped.setdefault(str(operation.get("path", "")), []).append(operation)
        ordered: list[dict[str, Any]] = []
        for path in sorted(grouped):
            group = grouped[path]
            if all(isinstance(operation.get("order"), int) for operation in group):
                ordered.extend(sorted(group, key=lambda item: item["order"]))
            else:

                def position(item: dict[str, Any]) -> int:
                    value = item.get("start_line", item.get("line", item.get("end_line", 0)))
                    return -value if isinstance(value, int) and not isinstance(value, bool) else 0

                ordered.extend(
                    sorted(
                        group,
                        key=position,
                    )
                )
        normalized["operations"] = ordered
    return normalized


def _path(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    portable_path = PurePosixPath(relative.replace("\\", "/"))
    if (
        not relative
        or "\0" in relative
        or relative in {".", ".."}
        or relative_path.is_absolute()
        or PureWindowsPath(relative).is_absolute()
        or portable_path.is_absolute()
        or ".." in portable_path.parts
    ):
        raise ValueError(f"unsafe path: {relative}")
    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise ValueError(f"unsafe path: {relative}")
    return candidate


def _preconditions(root: Path, plan: dict[str, Any]) -> dict[str, str | None]:
    declared = plan.get("touched_files", plan.get("files", []))
    paths = list(declared) if isinstance(declared, list) else []
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


def _diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "planned_diff": result.get("planned_diff", ""),
        "files": result.get("files", []),
        "errors": result.get("errors", []),
        "validation": result.get("validation", []),
    }


def _preview(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        return execute_plan(plan, root=root, apply=False, allow_native=False)
    except Exception as exc:  # noqa: BLE001 - convert any executor failure to a refusal
        return {
            "status": "refused",
            "planned_diff": "",
            "files": [],
            "errors": [{"code": "invalid_plan", "message": str(exc)}],
            "validation": [],
        }


def _invalid_path_diagnostics(relative: str) -> dict[str, Any]:
    return {
        "planned_diff": "",
        "files": [],
        "errors": [{"code": "unsafe_path", "message": f"unsafe path: {relative}", "path": relative}],
        "validation": [],
    }


def _validated_preview(
    plan_envelope: dict[str, Any], root: Path
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    plan = plan_envelope.get("plan")
    key = plan_envelope.get("idempotency_key")
    empty = _diagnostics({})
    if (
        plan_envelope.get("schema") != PLAN_SCHEMA
        or not isinstance(plan, dict)
        or not isinstance(key, str)
        or not key
    ):
        return empty, "invalid_plan_envelope", None
    if _digest(plan) != plan_envelope.get("plan_digest"):
        return empty, "plan_digest_mismatch", None
    if plan_envelope.get("effect_digest") != plan_envelope.get("plan_digest"):
        return empty, "effect_digest_mismatch", None
    mapper_binding = plan.get("mapper_binding")
    if mapper_binding is not None:
        binding_errors = validate_mapper_binding(mapper_binding)
        if binding_errors:
            return empty, "mapper_binding_invalid", {"errors": binding_errors}
    result = _preview(plan, root)
    diagnostics = _diagnostics(result)
    if result.get("status") != "ok":
        return diagnostics, "plan_invalid", None
    expected = plan_envelope.get("preconditions")
    if not isinstance(expected, dict):
        return diagnostics, "invalid_preconditions", None
    try:
        current = _preconditions(root, plan)
    except ValueError as exc:
        relative = str(exc).removeprefix("unsafe path: ")
        return _invalid_path_diagnostics(relative), "plan_invalid", None
    if current != expected:
        return diagnostics, "preconditions_failed", {"expected": expected, "actual": current}
    return diagnostics, None, None


def compile_plan(
    plan: dict[str, Any],
    *,
    root: str | Path,
    idempotency_key: str,
    mapper_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and bind a mechanical plan without writing or spawning."""
    root_path = Path(root).resolve()
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")  # noqa: TRY004 - public contract error
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    normalized = _normalized_plan(plan)
    supplied_binding = mapper_binding if mapper_binding is not None else normalized.get("mapper_binding")
    if supplied_binding is not None:
        binding_errors = validate_mapper_binding(supplied_binding)
        if binding_errors:
            return {
                "schema": PLAN_SCHEMA,
                "status": "blocked",
                "idempotency_key": idempotency_key,
                "reason": "mapper_binding_invalid",
                "errors": binding_errors,
            }
        normalized["mapper_binding"] = canonical_mapper_binding(supplied_binding)
    preview = _preview(normalized, root_path)
    digest = _digest(normalized)
    diagnostics = _diagnostics(preview)
    base: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "idempotency_key": idempotency_key,
        "plan_digest": digest,
        "effect_digest": digest,
        "preconditions": {},
        "diagnostics": diagnostics,
        "provenance": {"producer": "simplicio-dev-cli", "operator": "native-deterministic"},
    }
    if "mapper_binding" in normalized:
        base["mapper_binding"] = normalized["mapper_binding"]
        base["provenance"]["mapper_binding_digest"] = mapper_binding_digest(normalized["mapper_binding"])
    if preview.get("status") != "ok":
        return base | {"status": "blocked", "errors": preview.get("errors", [])}
    try:
        preconditions = _preconditions(root_path, normalized)
    except ValueError as exc:
        relative = str(exc).removeprefix("unsafe path: ")
        diagnostics = _invalid_path_diagnostics(relative)
        return base | {"status": "blocked", "diagnostics": diagnostics, "errors": diagnostics["errors"]}
    return base | {"status": "planned", "plan": normalized, "preconditions": preconditions}


def dry_run(plan_envelope: dict[str, Any], *, root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    diagnostics, reason, preconditions = _validated_preview(plan_envelope, root_path)
    payload = {
        "schema": DRY_RUN_SCHEMA,
        "status": "blocked" if reason else "dry_run",
        "applied": False,
        "idempotency_key": plan_envelope.get("idempotency_key"),
        "plan_digest": plan_envelope.get("plan_digest"),
        "effect_digest": plan_envelope.get("effect_digest", plan_envelope.get("plan_digest")),
        "preconditions": plan_envelope.get("preconditions", {}),
        "planned_diff": diagnostics["planned_diff"],
        "files": diagnostics["files"],
        "errors": diagnostics["errors"],
        "diagnostics": diagnostics,
        "provenance": plan_envelope.get("provenance", {}),
    }
    if isinstance(plan_envelope.get("mapper_binding"), dict):
        payload["mapper_binding"] = plan_envelope["mapper_binding"]
    if reason:
        payload["reason"] = reason
    if preconditions is not None:
        payload["precondition_diagnostics"] = preconditions
    return payload


def _receipt_path(root: Path, key: str) -> Path:
    root_resolved = root.resolve()
    state_dir = root_resolved / ".simplicio-loop"
    if state_dir.exists() and not state_dir.resolve().is_relative_to(root_resolved):
        raise ValueError("unsafe receipt path")
    receipt_dir = state_dir / "dev-cli-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir = receipt_dir.resolve()
    if not receipt_dir.is_relative_to(root_resolved):
        raise ValueError("unsafe receipt path")
    candidate = receipt_dir / f"{_digest(key)[:32]}.json"
    if candidate.is_symlink() and not candidate.resolve().is_relative_to(root_resolved):
        raise ValueError("unsafe receipt path")
    return candidate


def _receipt_digest(receipt: dict[str, Any]) -> str:
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    return _digest(body)


def _read_receipt(path: Path) -> dict[str, Any] | None:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("receipt_digest") != _receipt_digest(receipt)
    ):
        return None
    return receipt


def _acquire_receipt_lock(receipt_path: Path) -> Path | None:
    lock_path = receipt_path.parent / "apply.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _RECEIPT_LOCK_WAIT_SECONDS
    while True:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()}\n")
            return lock_path
        except (FileExistsError, PermissionError):
            if time.monotonic() >= deadline:
                return None
            time.sleep(_RECEIPT_LOCK_POLL_SECONDS)


def apply(plan_envelope: dict[str, Any], *, root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    plan = plan_envelope.get("plan")
    raw_key = plan_envelope.get("idempotency_key")
    if (
        plan_envelope.get("schema") != PLAN_SCHEMA
        or not isinstance(plan, dict)
        or not isinstance(raw_key, str)
        or not raw_key
    ):
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "invalid_plan_envelope"}
    key = raw_key
    if _digest(plan) != plan_envelope.get("plan_digest"):
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "plan_digest_mismatch"}
    if plan_envelope.get("effect_digest") != plan_envelope.get("plan_digest"):
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "effect_digest_mismatch"}
    try:
        receipt_path = _receipt_path(root_path, key)
    except ValueError:
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "receipt_path_unsafe"}
    lock_path = _acquire_receipt_lock(receipt_path)
    if lock_path is None:
        return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "concurrent_apply"}
    try:
        prior = _read_receipt(receipt_path) if receipt_path.is_file() else None
        if receipt_path.is_file() and prior is None:
            return {"schema": RECEIPT_SCHEMA, "status": "blocked", "reason": "receipt_invalid"}
        if prior is not None:
            if prior.get("plan_digest") != plan_envelope.get("plan_digest"):
                return {
                    "schema": RECEIPT_SCHEMA,
                    "status": "blocked",
                    "reason": "idempotency_lineage_mismatch",
                }
            replay = dict(prior)
            replay["replayed"] = True
            return replay
        diagnostics, reason, precondition_diagnostics = _validated_preview(plan_envelope, root_path)
        if reason:
            payload = {
                "schema": RECEIPT_SCHEMA,
                "status": "blocked",
                "reason": reason,
                "diagnostics": diagnostics,
            }
            if precondition_diagnostics is not None:
                payload["preconditions"] = precondition_diagnostics
            return payload
        result = execute_plan(plan, root=root_path, apply=True, allow_native=False)
        status = "committed" if result.get("status") == "ok" else "failed"
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": status,
            "applied": bool(result.get("applied")),
            "idempotency_key": key,
            "plan_digest": plan_envelope.get("plan_digest"),
            "effect_digest": plan_envelope.get("effect_digest", plan_envelope.get("plan_digest")),
            "preconditions": plan_envelope.get("preconditions", {}),
            "files": result.get("files", []),
            "errors": result.get("errors", []),
            "validation": result.get("validation", []),
            "diagnostics": diagnostics,
            "provenance": plan_envelope.get("provenance", {}),
            "recovery_locator": str(receipt_path.relative_to(root_path)),
        }
        if isinstance(plan_envelope.get("mapper_binding"), dict):
            receipt["mapper_binding"] = plan_envelope["mapper_binding"]
            receipt["mapper_binding_digest"] = mapper_binding_digest(plan_envelope["mapper_binding"])
        receipt["receipt_digest"] = _receipt_digest(receipt)
        write_text_atomic(receipt_path, _canonical(receipt) + "\n")
        return receipt | {"replayed": False}
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def reconcile(*, root: str | Path, idempotency_key: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    try:
        path = _receipt_path(root_path, idempotency_key)
    except ValueError:
        return {"schema": RECONCILE_SCHEMA, "status": "failed", "outcome": "receipt_path_unsafe"}
    if path.is_file():
        receipt = _read_receipt(path)
        if receipt is None:
            return {"schema": RECONCILE_SCHEMA, "status": "failed", "outcome": "receipt_invalid"}
        return {
            "schema": RECONCILE_SCHEMA,
            "status": "reconciled",
            "outcome": receipt.get("status"),
            "receipt": receipt | {"replayed": False},
            "receipt_digest_valid": True,
        }
    lock = load_effect_unknown_lock(str(root_path))
    if lock and lock.get("idempotency_key") == idempotency_key:
        return {
            "schema": RECONCILE_SCHEMA,
            "status": "unknown",
            "outcome": "effect_unknown",
            "recovery_locator": lock.get("evidence_file"),
        }
    return {"schema": RECONCILE_SCHEMA, "status": "not-found", "outcome": "not-found"}
