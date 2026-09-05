"""Deterministic mechanical edit executor for Simplicio contract v1."""

from __future__ import annotations

import difflib
import io
import json
import os
import shutil
import subprocess
import tempfile
import tokenize
from copy import deepcopy
from itertools import pairwise
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .mapper_binding import (
    mapper_binding_digest,
    validate_mapper_binding,
    verify_mapper_sources,
)
from .standalone_migration import (
    effect_unknown_details,
    effect_unknown_pending,
    record_effect_unknown,
)
from .token_primitives import sha256_text, summarize_log
from .utils.fs import write_bytes_atomic

PLAN_SCHEMA = "simplicio.mechanical-edit/v1"
RESULT_SCHEMA = "simplicio.mechanical-edit-result/v1"
TEXT_OPS = {"replace_range", "insert_before", "insert_after", "delete_range"}
ALLOWED_OPS = {
    *TEXT_OPS,
    "create_file",
    "json_patch",
    "ast_patch",
    "move_file",
    "delete_file",
}
TEXT_OP_REQUIRED_FIELDS = {
    "replace_range": ("start_line", "end_line", "text"),
    "delete_range": ("start_line", "end_line"),
    "insert_before": ("text",),
    "insert_after": ("text",),
}
TEXT_OP_ACCEPTED_FIELDS = {
    "replace_range": ("start_line", "end_line", "text"),
    "delete_range": ("start_line", "end_line"),
    "insert_before": ("line", "start_line", "text"),
    "insert_after": ("line", "end_line", "text"),
}
UNKNOWN_SELECTOR_FIELDS = frozenset(
    {
        "old",
        "new",
        "from",
        "to",
        "search",
        "replace",
        "pattern",
        "anchor",
        "selector",
        "match",
        "before",
        "after",
    }
)


def execute_plan_json(
    plan_text: str,
    *,
    root: str | Path = ".",
    apply: bool = False,
    allow_native: bool = True,
) -> dict[str, Any]:
    try:
        plan = json.loads(plan_text)
    except json.JSONDecodeError as exc:
        return _refused(
            [
                {
                    "code": "invalid_json",
                    "message": str(exc),
                    "line": exc.lineno,
                    "column": exc.colno,
                }
            ],
            root=root,
        )
    if not isinstance(plan, dict):
        return _refused(
            [{"code": "invalid_json", "message": "plan root must be a JSON object"}],
            root=root,
        )
    return execute_plan(plan, root=root, apply=apply, allow_native=allow_native)


def execute_plan(
    plan: dict[str, Any],
    *,
    root: str | Path = ".",
    apply: bool = False,
    allow_native: bool = True,
) -> dict[str, Any]:
    root_path = Path(root)

    errors = _validate_shape(plan)
    operations = plan.get("operations") if isinstance(plan.get("operations"), list) else []
    touched_files = _declared_touched_files(plan, operations)
    errors.extend(_validate_paths(root_path, operations, touched_files))
    errors.extend(_validate_overlaps(operations))
    if errors:
        return _refused(errors, root=root_path)
    if apply and effect_unknown_pending(str(root_path)):
        return _refused(
            [
                {
                    "code": "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED",
                    "message": "reconcile the prior native effect before another mutation",
                }
            ],
            root=root_path,
        )

    native_result = _try_native_edit(plan, root_path, apply=apply) if allow_native else None
    if native_result is not None:
        return native_result

    before = _snapshot(root_path, operations)
    mapper_binding = plan.get("mapper_binding")
    if mapper_binding is not None:
        binding_errors = validate_mapper_binding(mapper_binding)
        if binding_errors:
            return _refused(
                [{"code": "mapper_binding_invalid", "message": error} for error in binding_errors],
                root=root_path,
            )
        observed_hashes = {
            path: None if raw is None else _contract_hash(raw)
            for path, raw in before.items()
        }
        source_errors = verify_mapper_sources(mapper_binding, observed_hashes)
        if source_errors:
            return _refused(source_errors, root=root_path)
    try:
        after = _apply_operations_to_snapshot(root_path, before, operations)
    except MechanicalEditError as exc:
        return _refused([exc.to_dict()], root=root_path)

    diff = _build_diff(before, after)
    noop = diff == ""
    result = _base_result(root_path)
    result.update(
        {
            "status": "ok",
            "applied": False,
            "noop": noop,
            "planned_diff": diff,
            "files": _file_hash_rows(before, after),
            "operation_count": len(operations),
            "errors": [],
            "validation": [],
        }
    )
    if mapper_binding is not None:
        result["mapper_binding"] = mapper_binding
        result["mapper_binding_digest"] = mapper_binding_digest(mapper_binding)
    if not apply or noop:
        return result

    backups = _backup_existing(root_path, before)
    try:
        _write_snapshot(root_path, after)
        validation = _run_validation(plan.get("validation", []), root_path)
        result["validation"] = validation
        failed = [row for row in validation if not row["passed"] and not row.get("advisory")]
        if failed:
            _restore(root_path, backups)
            return _refused(
                [
                    {
                        "code": "validation_failed",
                        "message": "validation command failed",
                        "validation": failed,
                    }
                ],
                root=root_path,
                planned_diff=diff,
                files=_file_hash_rows(before, after),
                validation=validation,
            )
    except Exception:
        _restore(root_path, backups)
        raise

    result["applied"] = True
    return result


class MechanicalEditError(ValueError):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


# Timeout for delegating a plan to the native ``simplicio`` Rust binary.
# Matches the precedent in commands/file_read.py's RUNTIME_DELEGATION_TIMEOUT_S
# — generous enough for a real edit, short enough to never hang the caller
# when the binary exists but misbehaves.
_NATIVE_EDIT_TIMEOUT_S = 30.0
_VALIDATION_DEFAULT_TIMEOUT_S = 120
_VALIDATION_MAX_TIMEOUT_S = 300
_VALIDATION_MAX_ARGV_ITEMS = 128
_VALIDATION_MAX_ARGV_CHARS = 65_536
_VALIDATION_MAX_OUTPUT_BYTES = 65_536


def _native_edit_binary() -> str | None:
    """Locate the native ``simplicio`` binary, honoring the dev-cli kill-switch.

    Mirrors ``simplicio.commands.edit._runtime_edit_binary`` without importing
    that module: ``commands/edit.py`` imports this module lazily (inside
    ``run_mechanical_edit``), so a module-level import back here would invert
    that dependency.
    """
    binary = shutil.which("simplicio")
    if os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
        return None
    return binary


def _try_native_edit(
    plan: dict[str, Any],
    root_path: Path,
    *,
    apply: bool,
) -> dict[str, Any] | None:
    """Attempt to delegate *plan* to the native ``simplicio edit`` binary.

    Returns the translated result dict on a clean, schema-matching success.
    Returns ``None`` only when no native effect was admitted, allowing the
    caller to use the pure-Python implementation. Once an apply subprocess
    has been admitted, every ambiguous outcome becomes ``effect_unknown`` and
    persists a reconciliation lock; falling through would risk double apply.
    """
    binary = _native_edit_binary()
    if binary is None:
        return None

    try:
        plan_text = json.dumps(plan)
    except (TypeError, ValueError):
        return None

    tmp_path: str | None = None
    try:
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="simplicio-edit-plan-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(plan_text)
        except OSError:
            return None

        cmd = [binary, "edit", "--plan", tmp_path, "--repo", str(root_path), "--json"]
        if not apply:
            cmd.append("--dry-run")
        try:
            completed = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                cwd=root_path.resolve(),
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=_NATIVE_EDIT_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if not apply:
                return None
            return _native_effect_unknown(
                plan,
                root_path,
                reason=f"native edit outcome is unknown: {type(exc).__name__}",
            )

        try:
            payload = json.loads(getattr(completed, "stdout", ""))
        except (json.JSONDecodeError, ValueError) as exc:
            if not apply:
                return None
            return _native_effect_unknown(
                plan,
                root_path,
                reason=f"native edit returned invalid JSON: {type(exc).__name__}",
            )

        translated = _translate_native_result(payload, root_path)
        if translated is not None:
            return translated
        if not apply:
            return None
        return _native_effect_unknown(
            plan,
            root_path,
            reason="native edit returned an ambiguous or incompatible result",
        )
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# The native binary's *actual* `simplicio edit --json` output schema today —
# confirmed by running it live. It does NOT match this module's own
# RESULT_SCHEMA ("simplicio.mechanical-edit-result/v1"): the field shapes are
# genuinely different (`changed`/`file`/`operations_applied` vs this module's
# `noop`/`files`/`operation_count`), not just a schema-string typo. Translated
# below rather than requiring the runtime to change its established contract.
NATIVE_EDIT_RESULT_SCHEMA = "simplicio.edit-result/v1"


def _translate_native_result(payload: Any, root_path: Path) -> dict[str, Any] | None:
    """Translate the native `simplicio edit --json` payload into this
    module's own result shape (same keys ``execute_plan`` always returns).

    Returns ``None`` on any shape mismatch OR on `native_status ==
    "checks_failed"` — a missing/renamed field is treated the same as "the
    binary can't help here" rather than trusted partially. The
    "checks_failed" exclusion is a real semantic gap, not caution for its own
    sake: on a failed post-edit validation phase, the native binary has
    already written the file and does NOT roll it back, while this module's
    own Python path restores the pre-edit content on the same failure
    (`_restore(root_path, backups)` in `execute_plan`). Translating that case
    as a normal "refused" result would silently misrepresent the file as
    unchanged when it is not — falling through to the Python path instead
    preserves the rollback guarantee callers rely on.
    """
    if not isinstance(payload, dict) or payload.get("schema") != NATIVE_EDIT_RESULT_SCHEMA:
        return None
    native_status = payload.get("status")
    if native_status != "ok":
        return None
    file_abs = payload.get("file")
    changed = payload.get("changed")
    dry_run = payload.get("dry_run")
    operations_applied = payload.get("operations_applied")
    before_sha = payload.get("before_sha256")
    after_sha = payload.get("after_sha256")
    if (
        not isinstance(native_status, str)
        or not isinstance(file_abs, str)
        or not isinstance(changed, bool)
        or not isinstance(dry_run, bool)
        or not isinstance(operations_applied, int)
        or not isinstance(before_sha, str)
        or not isinstance(after_sha, str)
    ):
        return None

    try:
        rel_path = str(Path(file_abs).resolve().relative_to(root_path.resolve()))
    except ValueError:
        # Native binary reported a path outside root — untranslatable, not a
        # crash; the Python path applies its own root-escape checks anyway.
        return None

    files = (
        []
        if before_sha == after_sha
        else [{"path": rel_path, "before_sha256": before_sha, "after_sha256": after_sha}]
    )
    result = _base_result(root_path)
    result.update(
        {
            "status": "ok",
            "applied": bool(not dry_run),
            "noop": not changed,
            # The native binary's --json output does not currently include a
            # unified diff string (only prints one to the console in
            # --review/--dry-run mode, not part of this JSON payload) — an
            # empty string is the honest "not available" value here, not a
            # claim that nothing changed (see `files`/`noop` for that).
            "planned_diff": "",
            "files": files,
            "operation_count": operations_applied,
            "errors": [],
            "validation": [],
        }
    )
    return result


def _native_effect_unknown(
    plan: dict[str, Any],
    root_path: Path,
    *,
    reason: str,
) -> dict[str, Any]:
    details = effect_unknown_details(str(root_path), plan=plan)
    record_effect_unknown(str(root_path), details)
    result = _base_result(root_path)
    result.update(
        {
            "status": "effect_unknown",
            "effect_unknown": True,
            "applied": False,
            "noop": False,
            "planned_diff": "",
            "files": [],
            "operation_count": len(plan.get("operations", [])),
            "errors": [
                {
                    "code": "NATIVE_EFFECT_UNKNOWN",
                    "message": reason,
                    "recovery_command": details["recovery_command"],
                    "idempotency_key": details["idempotency_key"],
                }
            ],
            "validation": [],
            "effect_unknown_lock": ".simplicio/effect-unknown.lock",
        }
    )
    return result


def _validate_shape(plan: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    if plan.get("schema") != PLAN_SCHEMA:
        errors.append(
            {
                "code": "missing_schema",
                "message": f"schema must be {PLAN_SCHEMA}",
            }
        )
    operations = plan.get("operations")
    if not isinstance(operations, list):
        errors.append({"code": "invalid_schema", "message": "operations must be a list"})
        return errors
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            errors.append(
                {
                    "code": "invalid_schema",
                    "message": "operation must be an object",
                    "operation_index": index,
                }
            )
            continue
        name = op.get("op")
        if name not in ALLOWED_OPS:
            errors.append(
                {
                    "code": "unknown_operation",
                    "message": f"unknown operation {name!r}",
                    "operation_index": index,
                }
            )
            continue
        errors.extend(_validate_text_operation_fields(op, index))
    validation = plan.get("validation", [])
    if not isinstance(validation, list):
        errors.append(
            {
                "code": "invalid_validation",
                "message": "validation must be a list",
            }
        )
        return errors
    for index, item in enumerate(validation):
        if not isinstance(item, dict):
            errors.append(
                {
                    "code": "invalid_validation",
                    "message": "validation entry must be an object",
                    "validation_index": index,
                }
            )
            continue
        cmd = item.get("cmd")
        if (
            not isinstance(cmd, list)
            or not cmd
            or len(cmd) > _VALIDATION_MAX_ARGV_ITEMS
            or not all(isinstance(part, str) for part in cmd)
            or not cmd[0]
            or any("\0" in part for part in cmd)
            or sum(len(part) for part in cmd) > _VALIDATION_MAX_ARGV_CHARS
        ):
            errors.append(
                {
                    "code": "invalid_validation",
                    "message": "validation cmd must be a bounded non-empty list[str]",
                    "validation_index": index,
                }
            )
        timeout = item.get("timeout", _VALIDATION_DEFAULT_TIMEOUT_S)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= _VALIDATION_MAX_TIMEOUT_S
        ):
            errors.append(
                {
                    "code": "invalid_validation",
                    "message": f"validation timeout must be an integer from 1 to {_VALIDATION_MAX_TIMEOUT_S}",
                    "validation_index": index,
                }
            )
        if "cwd" in item or "shell" in item:
            errors.append(
                {
                    "code": "invalid_validation",
                    "message": "validation cwd and shell are fixed by the executor",
                    "validation_index": index,
                }
            )
    return errors


def _positive_line_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _schema_error(message: str, index: int, *, accepted_fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        "code": "invalid_schema",
        "message": f"{message} (schema {PLAN_SCHEMA})",
        "operation_index": index,
        "schema": PLAN_SCHEMA,
        "accepted_fields": list(accepted_fields),
    }


def _validate_text_operation_fields(operation: dict[str, Any], index: int) -> list[dict[str, Any]]:
    name = operation.get("op")
    if name not in TEXT_OPS:
        return []
    errors: list[dict[str, Any]] = []
    accepted = TEXT_OP_ACCEPTED_FIELDS[name]
    unknown = sorted(UNKNOWN_SELECTOR_FIELDS.intersection(operation))
    if unknown:
        errors.append(
            {
                "code": "unknown_selector",
                "message": (
                    f"{name} rejects mutation selector fields {', '.join(unknown)}; "
                    f"accepted fields are {', '.join(accepted)} (schema {PLAN_SCHEMA})"
                ),
                "operation_index": index,
                "schema": PLAN_SCHEMA,
                "accepted_fields": list(accepted),
                "unknown_fields": unknown,
            }
        )
    for field_name in TEXT_OP_REQUIRED_FIELDS[name]:
        if field_name not in operation:
            errors.append(
                _schema_error(
                    f"{name} requires {field_name}",
                    index,
                    accepted_fields=accepted,
                )
            )
    if name in {"insert_before", "insert_after"}:
        line_key = "start_line" if name == "insert_before" else "end_line"
        if "line" not in operation and line_key not in operation:
            errors.append(
                _schema_error(
                    f"{name} requires line or {line_key}",
                    index,
                    accepted_fields=accepted,
                )
            )
        for key in ("line", line_key):
            if key in operation and not _positive_line_number(operation[key]):
                errors.append(
                    _schema_error(
                        f"{name} {key} must be a positive integer",
                        index,
                        accepted_fields=accepted,
                    )
                )
    if name in {"replace_range", "delete_range"}:
        for key in ("start_line", "end_line"):
            if key in operation and not _positive_line_number(operation[key]):
                errors.append(
                    _schema_error(
                        f"{name} {key} must be a positive integer",
                        index,
                        accepted_fields=accepted,
                    )
                )
        start = operation.get("start_line")
        end = operation.get("end_line")
        if _positive_line_number(start) and _positive_line_number(end) and end < start:
            errors.append(
                _schema_error(
                    f"{name} end_line must be >= start_line",
                    index,
                    accepted_fields=accepted,
                )
            )
    if name != "delete_range" and "text" in operation and not isinstance(operation["text"], str):
        errors.append(
            _schema_error(
                f"{name} text must be a string",
                index,
                accepted_fields=accepted,
            )
        )
    return errors


def _declared_touched_files(
    plan: dict[str, Any],
    operations: list[dict[str, Any]],
) -> set[str]:
    raw = plan.get("touched_files", plan.get("files"))
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return set(raw)
    files = set()
    for operation in operations:
        for key in ("path", "dest"):
            value = operation.get(key)
            if isinstance(value, str):
                files.add(value)
    return files


def _validate_paths(
    root: Path,
    operations: list[dict[str, Any]],
    touched_files: set[str],
) -> list[dict[str, Any]]:
    errors = []
    for index, operation in enumerate(operations):
        for key in ("path", "dest"):
            value = operation.get(key)
            if not isinstance(value, str):
                if key == "path" or operation.get("op") == "move_file":
                    errors.append(
                        {
                            "code": "invalid_schema",
                            "message": f"{key} must be present",
                            "operation_index": index,
                        }
                    )
                continue
            try:
                _safe_path(root, value)
            except MechanicalEditError as exc:
                row = exc.to_dict()
                row["operation_index"] = index
                errors.append(row)
                continue
            if value not in touched_files:
                errors.append(
                    {
                        "code": "path_not_allowed",
                        "message": f"{value} is outside touched_files",
                        "operation_index": index,
                        "path": value,
                    }
                )
    return errors


def _validate_overlaps(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges: dict[str, list[tuple[int, int, int, bool]]] = {}
    for index, operation in enumerate(operations):
        if operation.get("op") not in TEXT_OPS:
            continue
        path = str(operation.get("path", ""))
        start_value = operation.get("start_line", operation.get("line"))
        end_value = operation.get("end_line", start_value)
        if operation.get("op") == "insert_after":
            start_value = end_value = operation.get("line", operation.get("end_line", start_value))
        if operation.get("op") == "insert_before":
            start_value = end_value = operation.get("line", operation.get("start_line", start_value))
        if not _positive_line_number(start_value) or not _positive_line_number(end_value):
            continue
        start = int(start_value)
        end = int(end_value)
        ranges.setdefault(path, []).append((start, end, index, isinstance(operation.get("order"), int)))
    for path, rows in ranges.items():
        rows = sorted(rows)
        for left, right in pairwise(rows):
            if left[1] >= right[0] and not (left[3] and right[3]):
                return [
                    {
                        "code": "overlapping_operations",
                        "message": f"overlap in {path}",
                        "operation_indexes": [left[2], right[2]],
                    }
                ]
    return []


def _snapshot(root: Path, operations: list[dict[str, Any]]) -> dict[str, bytes | None]:
    paths = set()
    for operation in operations:
        for key in ("path", "dest"):
            value = operation.get(key)
            if isinstance(value, str):
                paths.add(value)
    snapshot: dict[str, bytes | None] = {}
    for rel in paths:
        path = _safe_path(root, rel)
        snapshot[rel] = path.read_bytes() if path.exists() else None
    return snapshot


def _apply_operations_to_snapshot(
    root: Path,
    before: dict[str, bytes | None],
    operations: list[dict[str, Any]],
) -> dict[str, bytes | None]:
    after = deepcopy(before)
    for operation in _operation_order(operations):
        name = operation["op"]
        if name in TEXT_OPS:
            _check_text_preconditions(root, after, operation)
            _apply_text_operation(after, operation)
        elif name == "create_file":
            rel = operation["path"]
            if after.get(rel) is not None:
                raise MechanicalEditError("file_exists", f"{rel} already exists", path=rel)
            after[rel] = str(operation.get("text", "")).encode("utf-8")
        elif name == "delete_file":
            rel = operation["path"]
            _check_file_hash(after, operation)
            after[rel] = None
        elif name == "move_file":
            rel = operation["path"]
            dest = operation["dest"]
            _check_file_hash(after, operation)
            if after.get(dest) is not None:
                raise MechanicalEditError("file_exists", f"{dest} already exists", path=dest)
            after[dest] = after.get(rel)
            after[rel] = None
        elif name == "json_patch":
            _check_text_preconditions(root, after, operation)
            _apply_json_patch(after, operation)
        elif name == "ast_patch":
            _check_text_preconditions(root, after, operation)
            _apply_ast_patch(after, operation)
    return after


def _operation_order(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order operations for application, honoring explicit ``order`` per file.

    ``_validate_overlaps`` permits two operations on the SAME path to overlap
    only when *both* declare an integer ``order`` — it reasons per path, not
    across the whole plan. This function must apply that same per-path
    reasoning, or the two contracts diverge: a plan with an explicitly
    ordered, dependent pair of edits on file A (line numbers in the second op
    computed against the state AFTER the first) could pass validation, yet
    silently be applied out of order — and therefore against the WRONG line
    numbers — the moment the plan also contains any unrelated operation on a
    different file (or of a type with no ``order``, e.g. ``create_file``)
    that itself lacks an ``order`` key. That previously collapsed the
    fallback to line-based sorting for the *entire* plan, corrupting file A
    even though its own two operations were correctly, explicitly ordered.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for operation in operations:
        grouped.setdefault(str(operation.get("path", "")), []).append(operation)

    ordered: list[dict[str, Any]] = []
    for path in sorted(grouped):
        group = grouped[path]
        if all(isinstance(operation.get("order"), int) for operation in group):
            ordered.extend(sorted(group, key=lambda item: item["order"]))
        else:
            ordered.extend(
                sorted(
                    group,
                    key=lambda item: (
                        -int(item.get("start_line", item.get("line", item.get("end_line", 0))) or 0)
                    ),
                )
            )
    return ordered


def _check_text_preconditions(
    root: Path,
    snapshot: dict[str, bytes | None],
    operation: dict[str, Any],
) -> None:
    rel = operation["path"]
    raw = snapshot.get(rel)
    if raw is None:
        raise MechanicalEditError("file_missing", f"{rel} does not exist", path=rel)
    if b"\0" in raw:
        raise MechanicalEditError("binary_file", f"{rel} appears to be binary", path=rel)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MechanicalEditError("binary_file", f"{rel} is not UTF-8 text", path=rel) from exc
    _check_file_hash(snapshot, operation)
    expected = operation.get("range_sha256")
    if expected:
        selected = _selected_range(text, operation)
        actual = _contract_hash(selected)
        if actual != expected:
            raise MechanicalEditError(
                "range_hash_mismatch",
                f"{rel} range hash mismatch",
                path=rel,
                expected=expected,
                actual=actual,
            )
    _safe_path(root, rel)


def _check_file_hash(snapshot: dict[str, bytes | None], operation: dict[str, Any]) -> None:
    expected = operation.get("file_sha256")
    if not expected:
        return
    rel = operation["path"]
    raw = snapshot.get(rel)
    actual = None if raw is None else _contract_hash(raw)
    if actual != expected:
        raise MechanicalEditError(
            "file_hash_mismatch",
            f"{rel} file hash mismatch",
            path=rel,
            expected=expected,
            actual=actual,
        )


def _apply_text_operation(snapshot: dict[str, bytes | None], operation: dict[str, Any]) -> None:
    rel = operation["path"]
    raw = snapshot[rel]
    assert raw is not None
    source_text = raw.decode("utf-8")
    lines = source_text.splitlines(keepends=True)
    name = operation["op"]
    if name != "delete_range" and "text" not in operation:
        raise MechanicalEditError(
            "invalid_schema",
            f"{name} requires text (schema {PLAN_SCHEMA})",
            path=rel,
            schema=PLAN_SCHEMA,
        )
    text = _normalize_patch_text(str(operation.get("text", "")), source_text)
    if name == "insert_after":
        start_value = operation.get("line", operation.get("end_line", operation.get("start_line")))
    elif name == "insert_before":
        start_value = operation.get("line", operation.get("start_line", operation.get("end_line")))
    else:
        start_value = operation.get("start_line", operation.get("line"))
    if not _positive_line_number(start_value):
        raise MechanicalEditError(
            "invalid_schema",
            f"{name} requires a positive start_line or line (schema {PLAN_SCHEMA})",
            path=rel,
            schema=PLAN_SCHEMA,
        )
    start = int(start_value)
    end_value = operation.get("end_line", start)
    if not _positive_line_number(end_value):
        raise MechanicalEditError(
            "invalid_schema",
            f"{name} requires a positive end_line (schema {PLAN_SCHEMA})",
            path=rel,
            schema=PLAN_SCHEMA,
        )
    end = int(end_value)
    if start < 1 or end < start or end > max(len(lines), 1):
        raise MechanicalEditError("invalid_range", f"invalid line range for {rel}", path=rel)
    if name == "replace_range":
        selected = "".join(lines[start - 1 : end])
        text = _preserve_range_terminal_newline(text, selected)
    text_lines = text.splitlines(keepends=True)
    if name == "replace_range":
        lines[start - 1 : end] = text_lines
    elif name == "delete_range":
        lines[start - 1 : end] = []
    elif name == "insert_before":
        lines[start - 1 : start - 1] = text_lines
    elif name == "insert_after":
        line = int(operation.get("line", operation.get("end_line", end)))
        lines[line:line] = text_lines
    snapshot[rel] = "".join(lines).encode("utf-8")


def _apply_json_patch(snapshot: dict[str, bytes | None], operation: dict[str, Any]) -> None:
    rel = operation["path"]
    raw = snapshot[rel]
    assert raw is not None
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MechanicalEditError("invalid_json_file", str(exc), path=rel) from exc
    patch = operation.get("patch")
    if not isinstance(patch, list):
        raise MechanicalEditError("invalid_schema", "json_patch.patch must be a list", path=rel)
    for row in patch:
        if not isinstance(row, dict):
            raise MechanicalEditError("invalid_schema", "json_patch row must be object", path=rel)
        _apply_json_patch_row(data, row)
    snapshot[rel] = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _apply_json_patch_row(data: Any, row: dict[str, Any]) -> None:
    op = row.get("op")
    path = row.get("path")
    if op not in {"add", "replace", "remove"} or not isinstance(path, str):
        raise MechanicalEditError("invalid_schema", "invalid json patch row")
    parent, key = _json_pointer_parent(data, path)
    if isinstance(parent, list):
        index = len(parent) if key == "-" else int(key)
        if op == "remove":
            parent.pop(index)
        elif op == "replace":
            parent[index] = row.get("value")
        else:
            parent.insert(index, row.get("value"))
        return
    if op == "remove":
        parent.pop(key, None)
    else:
        parent[key] = row.get("value")


def _json_pointer_parent(data: Any, path: str) -> tuple[Any, str]:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path.strip("/").split("/") if part]
    if not parts:
        raise MechanicalEditError("invalid_schema", "root JSON pointer is not supported")
    parent = data
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    return parent, parts[-1]


def _apply_ast_patch(snapshot: dict[str, bytes | None], operation: dict[str, Any]) -> None:
    patch = operation.get("patch")
    if not isinstance(patch, dict) or patch.get("action") != "rename_identifier":
        raise MechanicalEditError(
            "unsupported_ast_patch",
            "only Python rename_identifier ast_patch is supported in v1",
            path=operation["path"],
        )
    old = patch.get("from")
    new = patch.get("to")
    if not isinstance(old, str) or not isinstance(new, str):
        raise MechanicalEditError("invalid_schema", "rename_identifier needs from/to")
    rel = operation["path"]
    raw = snapshot[rel]
    assert raw is not None
    tokens = []
    stream = io.BytesIO(raw).readline
    try:
        for token in tokenize.tokenize(stream):
            if token.type == tokenize.NAME and token.string == old:
                token = token._replace(string=new)
            tokens.append(token)
        snapshot[rel] = tokenize.untokenize(tokens)
    except tokenize.TokenError as exc:
        raise MechanicalEditError("ast_patch_failed", str(exc), path=rel) from exc


def _selected_range(text: str, operation: dict[str, Any]) -> str:
    lines = text.splitlines(keepends=True)
    start = int(operation.get("start_line", operation.get("line", 1)))
    end = int(operation.get("end_line", start))
    return "".join(lines[start - 1 : end])


def _build_diff(before: dict[str, bytes | None], after: dict[str, bytes | None]) -> str:
    chunks = []
    for rel in sorted(set(before) | set(after)):
        old = _decode_for_diff(before.get(rel))
        new = _decode_for_diff(after.get(rel))
        if old == new:
            continue
        chunks.extend(
            difflib.unified_diff(
                [] if old is None else old.splitlines(keepends=True),
                [] if new is None else new.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
    return "".join(chunks)


def _decode_for_diff(raw: bytes | None) -> str | None:
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return "<binary>\n"


def _backup_existing(root: Path, before: dict[str, bytes | None]) -> dict[str, bytes | None]:
    backups = {}
    for rel in before:
        path = _safe_path(root, rel)
        backups[rel] = path.read_bytes() if path.exists() else None
    return backups


def _write_snapshot(root: Path, after: dict[str, bytes | None]) -> None:
    for rel, raw in after.items():
        path = _safe_path(root, rel)
        if raw is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, raw)


def _restore(root: Path, backups: dict[str, bytes | None]) -> None:
    for rel, raw in backups.items():
        path = _safe_path(root, rel)
        if raw is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, raw)


def _run_validation(raw: Any, root: Path) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cmd = item.get("cmd")
        advisory = bool(item.get("advisory", False))
        timeout = item.get("timeout", _VALIDATION_DEFAULT_TIMEOUT_S)
        if not isinstance(cmd, list) or not all(isinstance(part, str) for part in cmd):
            rows.append(
                {
                    "cmd": cmd,
                    "passed": False,
                    "returncode": None,
                    "advisory": advisory,
                    "error": "cmd must be list[str]",
                }
            )
            continue
        try:
            with tempfile.TemporaryFile() as output:
                proc = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    cwd=root.resolve(),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    check=False,
                    timeout=timeout,
                )
                output.seek(0)
                captured = output.read(_VALIDATION_MAX_OUTPUT_BYTES + 1)
            truncated = len(captured) > _VALIDATION_MAX_OUTPUT_BYTES
            log = captured[:_VALIDATION_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            if truncated:
                log += "\n[validation output truncated]\n"
            rows.append(
                {
                    "cmd": cmd,
                    "passed": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "advisory": advisory,
                    "log_summary": summarize_log(log, max_chars=900),
                }
            )
        except Exception as exc:  # noqa: BLE001 - validation must become evidence
            rows.append(
                {
                    "cmd": cmd,
                    "passed": False,
                    "returncode": None,
                    "advisory": advisory,
                    "error": str(exc),
                    "log_summary": summarize_log(str(exc), max_chars=900),
                }
            )
    return rows


def _file_hash_rows(
    before: dict[str, bytes | None],
    after: dict[str, bytes | None],
) -> list[dict[str, Any]]:
    rows = []
    for rel in sorted(set(before) | set(after)):
        old = before.get(rel)
        new = after.get(rel)
        if old == new:
            continue
        rows.append(
            {
                "path": rel,
                "before_sha256": None if old is None else _contract_hash(old),
                "after_sha256": None if new is None else _contract_hash(new),
            }
        )
    return rows


def _contract_hash(value: str | bytes) -> str:
    """Hash text with normalized line endings; keep binary hashes byte-exact."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return sha256_text(value)
    return sha256_text(_normalize_line_endings(value))


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_patch_text(patch_text: str, source_text: str) -> str:
    """Apply text operations using the file's dominant newline convention."""
    normalized = _normalize_line_endings(patch_text)
    if "\r\n" in source_text:
        return normalized.replace("\n", "\r\n")
    return normalized


def _range_terminal_newline(selected: str) -> str:
    """Return the selected range's terminal line ending, or empty if none."""
    if selected.endswith("\r\n"):
        return "\r\n"
    if selected.endswith("\n"):
        return "\n"
    if selected.endswith("\r"):
        return "\r"
    return ""


def _preserve_range_terminal_newline(text: str, selected: str) -> str:
    """Keep a line-based replace_range from swallowing the next source line.

    Line-oriented replacements that omit a trailing newline used to splice
    the following untouched line onto the replacement. Preserve the selected
    range's own terminator when the caller omitted one.
    """
    ending = _range_terminal_newline(selected)
    if not ending:
        return text
    if _range_terminal_newline(text):
        return text
    return text + ending


def _safe_path(root: Path, rel: str) -> Path:
    rel_path = Path(rel)
    portable_path = PurePosixPath(rel.replace("\\", "/"))
    if (
        not rel
        or "\0" in rel
        or rel in {".", ".."}
        or rel_path.is_absolute()
        or PureWindowsPath(rel).is_absolute()
        or portable_path.is_absolute()
        or ".." in portable_path.parts
    ):
        raise MechanicalEditError("unsafe_path", f"unsafe relative path: {rel}", path=rel)
    root_resolved = root.resolve()
    path = (root_resolved / rel_path).resolve()
    if not path.is_relative_to(root_resolved):
        raise MechanicalEditError("unsafe_path", f"path escapes root: {rel}", path=rel)
    return path


def _base_result(root: Path) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "root": str(root)}


def _refused(
    errors: list[dict[str, Any]],
    *,
    root: str | Path,
    planned_diff: str = "",
    files: list[dict[str, Any]] | None = None,
    validation: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = _base_result(Path(root))
    result.update(
        {
            "status": "refused",
            "applied": False,
            "noop": False,
            "planned_diff": planned_diff,
            "files": files or [],
            "operation_count": 0,
            "errors": errors,
            "validation": validation or [],
        }
    )
    return result
