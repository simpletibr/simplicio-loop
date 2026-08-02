"""Official ``simplicio.fast.changeset/v2`` execution adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .changeset_transaction import (
    ChangesetTransactionError,
    changeset_digest,
    execute_changeset_transaction,
    existing_transaction_result,
)
from .fast_contracts import FastEngineError, FastEngineSession, select_fast_engine
from .mechanical_edit import execute_plan

CHANGESET_SCHEMA = "simplicio.fast.changeset/v2"
BINARY_SCHEMA = "simplicio.fast.binary-changeset/v1"
BINARY_MAGIC = b"SFBCHG01"
RECEIPT_SCHEMA = "simplicio.fast.changeset-receipt/v2"
MECHANICAL_SCHEMA = "simplicio.mechanical-edit/v1"
_BINARY_IDENTITY_FIELDS = (
    "base_generation",
    "overlay_generation",
    "attempt",
    "worktree_id",
    "lease_id",
    "fencing_token",
)
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


def _validate_binary_identity(value: dict[str, Any]) -> None:
    """Validate causal bindings before handing the changeset to the executor."""

    for field in _BINARY_IDENTITY_FIELDS:
        identity = value.get(field)
        if not isinstance(identity, str) or not identity.strip():
            raise ChangesetError(
                "binary_authority_invalid",
                f"binary authority field {field!r} must be a non-empty string",
                field=field,
            )
    allowed_paths = value.get("allowed_paths")
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or not all(isinstance(path, str) and path.strip() for path in allowed_paths)
    ):
        raise ChangesetError(
            "binary_allowlist_invalid",
            "binary allowed_paths must be a non-empty list of non-empty strings",
        )


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
        if translated == "create_file":
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


def _refused_receipt(changeset: Any, error: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    source = changeset if isinstance(changeset, dict) else {}
    return {
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


def execute_changeset(
    changeset: dict[str, Any],
    *,
    root: str | Path = ".",
    apply: bool = False,
    current_generation: str | None = None,
    causal_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        mechanical = adapt_changeset(changeset, current_generation=current_generation)
    except ChangesetError as exc:
        return _refused_receipt(changeset, exc.row, apply=apply)

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
            }
        try:
            if result is None:
                result = execute_changeset_transaction(
                    mechanical,
                    root=root,
                    idempotency_key=key,
                    changeset_digest_value=digest,
                    causal_ids=causal_ids or _causal_ids(changeset),
                )
        except ChangesetTransactionError as exc:
            return _refused_receipt(
                changeset,
                {"code": exc.code, "message": str(exc), **exc.extra},
                apply=apply,
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
    }


def execute_changeset_json(
    text: str,
    *,
    root: str | Path = ".",
    apply: bool = False,
    current_generation: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return _refused_receipt(
            {},
            {"code": "invalid_json", "message": str(exc), "line": exc.lineno, "column": exc.colno},
            apply=apply,
        )
    if not isinstance(payload, dict):
        return _refused_receipt(
            {}, {"code": "invalid_json", "message": "changeset root must be an object"}, apply=apply
        )
    return execute_changeset(
        payload,
        root=root,
        apply=apply,
        current_generation=current_generation,
    )


def execute_changeset_bytes(
    payload: bytes,
    *,
    root: str | Path = ".",
    apply: bool = False,
    current_generation: str | None = None,
    fast_engine: str | None = None,
    refresh_fn: Callable[[tuple[str, ...]], Any] | None = None,
    refresh_producer: Callable[[Path, tuple[str, ...]], Any] | None = None,
    engine_session: FastEngineSession | None = None,
) -> dict[str, Any]:
    """Consume a sealed Fast binary changeset without decoding it as UTF-8/JSON."""
    if not isinstance(payload, bytes) or not payload.startswith(BINARY_MAGIC):
        return _refused_receipt(
            {},
            {"code": "binary_magic_invalid", "message": "payload is not a Fast binary changeset"},
            apply=apply,
        )
    root_path = Path(root).resolve()
    try:
        engine = (
            engine_session.select(fast_engine or "auto")
            if engine_session is not None
            else select_fast_engine(fast_engine or "auto")
        )
    except FastEngineError as exc:
        return _refused_receipt({}, {"code": exc.code, "message": str(exc)}, apply=apply)
    if engine.name == "none":
        return _refused_receipt(
            {},
            {
                "code": "binary_decoder_unavailable",
                "message": "install the simplicio-fast binary conformance decoder",
            },
            apply=apply,
        )
    try:
        value = engine.decode_binary(payload)
        if value.get("repository") != str(root_path):
            raise ChangesetError("binary_repository_mismatch", "binary repository does not match --root")
        changeset = _public_changeset_from_binary(value)
        _validate_binary_identity(value)
        required_identity = _BINARY_IDENTITY_FIELDS
        receipt = execute_changeset(
            changeset,
            root=root_path,
            apply=apply,
            current_generation=current_generation,
            causal_ids=_causal_ids(value),
        )
        refresh = None
        transaction = receipt.get("transaction")
        if apply and receipt.get("status") == "ok" and isinstance(transaction, dict):
            if transaction.get("state") == "COMMITTED" and not receipt.get("replayed"):
                refresh_callback = refresh_fn
                if refresh_callback is None and refresh_producer is not None:

                    def refresh_callback(paths: tuple[str, ...]) -> Any:
                        assert refresh_producer is not None
                        return refresh_producer(root_path, paths)

                refresh = engine.refresh(
                    engine.changed_paths(value),
                    refresh_fn=refresh_callback,
                )
        receipt.update(
            {
                "input_format": BINARY_SCHEMA,
                "binary_sha256": hashlib.sha256(payload).hexdigest(),
                "binary_changeset_id": value.get("changeset_id"),
                "fast_identity": {field: value.get(field) for field in required_identity},
                "fast_engine": engine.receipt(),
            }
        )
        if refresh is not None:
            receipt["refresh"] = refresh
        return receipt
    except ChangesetError as exc:
        return _refused_receipt(
            {},
            exc.row | {"input_format": BINARY_SCHEMA},
            apply=apply,
        )
    except FastEngineError as exc:
        return _refused_receipt(
            {}, {"code": exc.code, "message": str(exc), "input_format": BINARY_SCHEMA}, apply=apply
        )
    except Exception as exc:
        return _refused_receipt(
            {},
            {
                "code": "binary_decode_failed",
                "message": f"Fast binary decoder rejected the envelope: {type(exc).__name__}",
                "input_format": BINARY_SCHEMA,
            },
            apply=apply,
        )


def _public_changeset_from_binary(value: dict[str, Any]) -> dict[str, Any]:
    operations = []
    for index, raw in enumerate(value.get("operations", [])):
        if not isinstance(raw, dict):
            raise ChangesetError(
                "binary_operation_invalid", "binary operation must be an object", operation_index=index
            )
        operation = dict(raw)
        kind = operation.pop("op", None)
        mapped = {
            "replace-range": "replace_range",
            "create": "create",
            "delete": "delete",
            "rename": "move",
        }.get(kind)
        if mapped is None:
            raise ChangesetError(
                "binary_operation_unsupported",
                f"unsupported binary operation {kind!r}",
                operation_index=index,
            )
        operation["kind"] = mapped
        if "dest" in operation:
            operation["target"] = operation.pop("dest")
        if "line_map" in operation:
            line_map = operation.pop("line_map")
            if isinstance(line_map, dict):
                operation.update(
                    {key: line_map[key] for key in ("start_line", "end_line") if key in line_map}
                )
        if "content_b64" in operation and "content" not in operation:
            try:
                operation["content"] = base64.b64decode(operation.pop("content_b64"), validate=True).decode(
                    operation.get("encoding") or "utf-8"
                )
            except (ValueError, UnicodeDecodeError) as exc:
                raise ChangesetError("binary_content_invalid", "binary content is not valid text") from exc
        operations.append(operation)
    return {
        "schema": CHANGESET_SCHEMA,
        "changeset_id": value.get("changeset_id"),
        "generation": value.get("base_generation"),
        "allowlist": list(value.get("allowed_paths", [])),
        "operations": operations,
        "validation": [{"cmd": [command]} for command in value.get("verification_commands", [])],
    }


def benchmark_environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
