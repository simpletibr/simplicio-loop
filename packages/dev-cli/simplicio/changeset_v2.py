"""Dev CLI ``simplicio.fast.changeset/v2`` JSON execution adapter."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

from .changeset_transaction import (
    ChangesetTransactionError,
    changeset_digest,
    execute_changeset_transaction,
    existing_transaction_result,
)
from .mechanical_edit import execute_plan
from .standalone_migration import MutationRouteAdmission

CHANGESET_SCHEMA = "simplicio.fast.changeset/v2"
RECEIPT_SCHEMA = "simplicio.fast.changeset-receipt/v2"
MECHANICAL_SCHEMA = "simplicio.mechanical-edit/v1"
_CAUSAL_ID_FIELDS = (
    "changeset_id",
    "correlation_id",
    "generation",
    "base_generation",
    "overlay_generation",
    "attempt",
    "worktree_id",
    "lease_id",
    "fencing_token",
)
OPERATION_MAP = {
    "replace_range": "replace_range",
    "create": "create_file",
    "create_file": "create_file",
    "delete": "delete_file",
    "delete_file": "delete_file",
    "move": "move_file",
    "move_file": "move_file",
    "json_patch": "json_patch",
    "ast_patch": "ast_patch",
}


class ChangesetError(ValueError):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.row = {"code": code, "message": message, **extra}


def _causal_ids(source: dict[str, Any]) -> dict[str, str]:
    result = {
        field: value for field in _CAUSAL_ID_FIELDS if isinstance(value := source.get(field), str) and value
    }
    if "generation" not in result and isinstance(source.get("base_generation"), str):
        result["generation"] = source["base_generation"]
    return result


def adapt_changeset(changeset: dict[str, Any], *, current_generation: str | None = None) -> dict[str, Any]:
    if changeset.get("schema") != CHANGESET_SCHEMA:
        raise ChangesetError(
            "incompatible_schema",
            f"schema must be {CHANGESET_SCHEMA}; binary input requires the bytes adapter",
        )
    generation = changeset.get("generation")
    if not isinstance(generation, str) or not generation:
        raise ChangesetError("invalid_generation", "generation must be a non-empty string")
    effective_generation = current_generation or changeset.get("current_generation")
    if effective_generation is not None and str(effective_generation) != generation:
        raise ChangesetError(
            "stale_generation",
            "changeset generation does not match the current generation",
            expected=str(effective_generation),
            actual=generation,
        )
    allowlist = changeset.get("allowlist")
    if (
        not isinstance(allowlist, list)
        or not allowlist
        or not all(isinstance(path, str) for path in allowlist)
    ):
        raise ChangesetError("invalid_allowlist", "allowlist must be a non-empty list[str]")
    raw_operations = changeset.get("operations")
    if not isinstance(raw_operations, list):
        raise ChangesetError("invalid_schema", "operations must be a list")

    operations: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_operations):
        if not isinstance(raw, dict):
            raise ChangesetError("invalid_schema", "operation must be an object", operation_index=index)
        kind = raw.get("kind", raw.get("op"))
        translated = OPERATION_MAP.get(str(kind))
        if translated is None:
            raise ChangesetError(
                "unsupported_operation",
                f"unsupported changeset operation {kind!r}",
                operation_index=index,
            )
        operation = dict(raw)
        operation.pop("kind", None)
        operation["op"] = translated
        if translated in {"create_file", "replace_range"}:
            operation["text"] = operation.pop("content", operation.get("text", ""))
        if translated == "move_file":
            operation["path"] = operation.pop("source", operation.get("path"))
            operation["dest"] = operation.pop("target", operation.get("dest"))
        if "before_sha256" in operation and "file_sha256" not in operation:
            operation["file_sha256"] = operation.pop("before_sha256")
        operations.append(operation)

    validation = changeset.get("validation", [])
    return {
        "schema": MECHANICAL_SCHEMA,
        "touched_files": list(allowlist),
        "operations": operations,
        "validation": validation,
    }


def _refused_receipt(
    changeset: Any,
    error: dict[str, Any],
    *,
    apply: bool,
    route_admission: MutationRouteAdmission | None = None,
) -> dict[str, Any]:
    source = changeset if isinstance(changeset, dict) else {}
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "changeset_id": source.get("changeset_id"),
        "generation": source.get("generation"),
        "correlation_id": source.get("correlation_id", source.get("changeset_id")),
        "status": "refused",
        "applied": False,
        "dry_run": not apply,
        "effects": [],
        "errors": [error],
        "rollback": {"attempted": False, "succeeded": None, "reason": "no-effects-started"},
        "effect_unknown": False,
    }
    if route_admission is not None:
        receipt["execution_route"] = route_admission.to_dict()
    return receipt


def _execution_route(
    result: dict[str, Any],
    fallback: MutationRouteAdmission,
) -> dict[str, Any]:
    transaction = result.get("transaction")
    if isinstance(transaction, dict):
        recorded = transaction.get("route_admission")
        if isinstance(recorded, dict):
            return dict(recorded)
    return fallback.to_dict()


def execute_changeset(
    changeset: dict[str, Any],
    *,
    root: str | Path = ".",
    apply: bool = False,
    current_generation: str | None = None,
    causal_ids: dict[str, str] | None = None,
    route_admission: MutationRouteAdmission | None = None,
) -> dict[str, Any]:
    admission = route_admission or MutationRouteAdmission("standalone", "standalone")
    execution_admission = admission
    try:
        mechanical = adapt_changeset(changeset, current_generation=current_generation)
    except ChangesetError as exc:
        return _refused_receipt(changeset, exc.row, apply=apply, route_admission=admission)

    if apply:
        key = str(
            changeset.get("correlation_id") or changeset.get("changeset_id") or changeset_digest(changeset)
        )
        digest = changeset_digest(changeset)
        try:
            result = existing_transaction_result(
                root,
                idempotency_key=key,
                changeset_digest_value=digest,
            )
        except ChangesetTransactionError as exc:
            return _refused_receipt(
                changeset,
                {"code": exc.code, "message": str(exc), **exc.extra},
                apply=apply,
                route_admission=execution_admission,
            )
        preflight = (
            None
            if result is not None
            else execute_plan(mechanical, root=root, apply=False, allow_native=False)
        )
        if preflight is not None and preflight.get("status") != "ok":
            validation_failed = any(
                error.get("code") == "validation_failed" for error in preflight.get("errors", [])
            )
            return {
                "schema": RECEIPT_SCHEMA,
                "changeset_id": changeset.get("changeset_id"),
                "generation": changeset.get("generation"),
                "correlation_id": changeset.get("correlation_id", changeset.get("changeset_id")),
                "status": preflight["status"],
                "applied": False,
                "dry_run": False,
                "noop": False,
                "planned_diff": preflight.get("planned_diff", ""),
                "effects": [],
                "errors": preflight.get("errors", []),
                "validation": preflight.get("validation", []),
                "rollback": {
                    "attempted": validation_failed,
                    "succeeded": True if validation_failed else None,
                    "reason": "validation-failed" if validation_failed else "no-effects-started",
                },
                "effect_unknown": preflight.get("status") == "effect_unknown",
                "transaction": None,
                "replayed": False,
                "execution_route": admission.to_dict(),
            }
        try:
            if result is None:
                execution_admission = admission.admit()
                result = execute_changeset_transaction(
                    mechanical,
                    root=root,
                    idempotency_key=key,
                    changeset_digest_value=digest,
                    causal_ids=causal_ids or _causal_ids(changeset),
                    route_admission=execution_admission.to_dict(),
                )
        except ChangesetTransactionError as exc:
            return _refused_receipt(
                changeset,
                {"code": exc.code, "message": str(exc), **exc.extra},
                apply=apply,
                route_admission=execution_admission,
            )
    else:
        result = execute_plan(mechanical, root=root, apply=False)
    validation_failed = any(error.get("code") == "validation_failed" for error in result.get("errors", []))
    effects = [
        {
            "path": row["path"],
            "before_sha256": row.get("before_sha256"),
            "after_sha256": row.get("after_sha256"),
            "changed": row.get("before_sha256") != row.get("after_sha256"),
        }
        for row in result.get("files", [])
    ]
    return {
        "schema": RECEIPT_SCHEMA,
        "changeset_id": changeset.get("changeset_id"),
        "generation": changeset.get("generation"),
        "correlation_id": changeset.get("correlation_id", changeset.get("changeset_id")),
        "status": result["status"],
        "applied": result["applied"],
        "dry_run": not apply,
        "noop": result.get("noop", False),
        "planned_diff": result.get("planned_diff", ""),
        "effects": effects,
        "errors": result.get("errors", []),
        "validation": result.get("validation", []),
        "rollback": {
            "attempted": validation_failed,
            "succeeded": True if validation_failed else None,
            "reason": "validation-failed" if validation_failed else "not-required",
        },
        "effect_unknown": result.get("status") == "effect_unknown",
        "transaction": result.get("transaction"),
        "replayed": result.get("replayed", False),
        "execution_route": _execution_route(result, execution_admission),
    }


def execute_changeset_json(
    text: str | bytes,
    *,
    root: str | Path = ".",
    apply: bool = False,
    current_generation: str | None = None,
    route_admission: MutationRouteAdmission | None = None,
) -> dict[str, Any]:
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            return _refused_receipt(
                {},
                {"code": "invalid_encoding", "message": f"changeset is not UTF-8 JSON: {exc.reason}"},
                apply=apply,
                route_admission=route_admission,
            )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return _refused_receipt(
            {},
            {"code": "invalid_json", "message": str(exc), "line": exc.lineno, "column": exc.colno},
            apply=apply,
            route_admission=route_admission,
        )
    if not isinstance(payload, dict):
        return _refused_receipt(
            {},
            {"code": "invalid_json", "message": "changeset root must be an object"},
            apply=apply,
            route_admission=route_admission,
        )
    return execute_changeset(
        payload,
        root=root,
        apply=apply,
        current_generation=current_generation,
        route_admission=route_admission,
    )


def benchmark_environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
