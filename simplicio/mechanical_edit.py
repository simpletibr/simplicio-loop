"""Deterministic mechanical edit executor for Simplicio contract v1."""

from __future__ import annotations

import difflib
import io
import json
import subprocess
import tokenize
from copy import deepcopy
from pathlib import Path
from typing import Any

from .token_primitives import sha256_text, summarize_log

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


def execute_plan_json(
    plan_text: str,
    *,
    root: str | Path = ".",
    apply: bool = False,
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
    return execute_plan(plan, root=root, apply=apply)


def execute_plan(
    plan: dict[str, Any],
    *,
    root: str | Path = ".",
    apply: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    errors = _validate_shape(plan)
    operations = plan.get("operations") if isinstance(plan.get("operations"), list) else []
    touched_files = _declared_touched_files(plan, operations)
    errors.extend(_validate_paths(root_path, operations, touched_files))
    errors.extend(_validate_overlaps(operations))
    if errors:
        return _refused(errors, root=root_path)

    before = _snapshot(root_path, operations)
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
        start = int(operation.get("start_line", operation.get("line", 1)))
        end = int(operation.get("end_line", start))
        if operation.get("op") == "insert_after":
            start = end = int(operation.get("line", operation.get("end_line", start)))
        if operation.get("op") == "insert_before":
            start = end = int(operation.get("line", operation.get("start_line", start)))
        ranges.setdefault(path, []).append((start, end, index, isinstance(operation.get("order"), int)))
    for path, rows in ranges.items():
        rows = sorted(rows)
        for left, right in zip(rows, rows[1:], strict=False):
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
    if all(isinstance(operation.get("order"), int) for operation in operations):
        return sorted(operations, key=lambda item: item["order"])
    return sorted(
        operations,
        key=lambda item: (
            str(item.get("path", "")),
            -int(item.get("start_line", item.get("line", item.get("end_line", 0))) or 0),
        ),
    )


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
    text = _normalize_patch_text(str(operation.get("text", "")), source_text)
    text_lines = text.splitlines(keepends=True)
    name = operation["op"]
    start = int(operation.get("start_line", operation.get("line", 1)))
    end = int(operation.get("end_line", start))
    if start < 1 or end < start or end > max(len(lines), 1):
        raise MechanicalEditError("invalid_range", f"invalid line range for {rel}", path=rel)
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
        path.write_bytes(raw)


def _restore(root: Path, backups: dict[str, bytes | None]) -> None:
    for rel, raw in backups.items():
        path = _safe_path(root, rel)
        if raw is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def _run_validation(raw: Any, root: Path) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cmd = item.get("cmd")
        advisory = bool(item.get("advisory", False))
        timeout = int(item.get("timeout", 120))
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
            proc = subprocess.run(
                cmd,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            log = (proc.stdout or "") + (proc.stderr or "")
            rows.append(
                {
                    "cmd": cmd,
                    "passed": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "advisory": advisory,
                    "log_summary": summarize_log(log, max_chars=900),
                }
            )
        except Exception as exc:
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


def _safe_path(root: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise MechanicalEditError("unsafe_path", f"unsafe relative path: {rel}", path=rel)
    root_resolved = root.resolve()
    path = (root_resolved / rel_path).resolve()
    if not str(path).startswith(str(root_resolved)):
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
