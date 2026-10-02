"""simplicio_mapper.changeset — strict changeset validation and lifecycle (Issue #655).

Supports both:
1. JSON changesets (schema simplicio.fast.changeset/v2):
   - Fail-closed expected_sha256 verification (stale source hash).
   - Line boundaries and overlapping checks.
   - Byte-exact newline normalization (\n and \r\n).
   - Atomic multi-file write with rollback.
2. Binary changesets (schema simplicio.fast.binary-changeset/v1):
   - Frame encoding/decoding, checksums, and sealing.
   - Journaling, inspection, and verification.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

CHANGESET_SCHEMA_V2 = "simplicio.fast.changeset/v2"
CHANGESET_VALIDATION_SCHEMA_V2 = "simplicio.fast.changeset-validation/v2"
APPLY_RECEIPT_SCHEMA_V2 = "simplicio.fast.apply-receipt/v2"

BINARY_SCHEMA = "simplicio.fast.binary-changeset/v1"
JOURNAL_SCHEMA = "simplicio.fast.binary-changeset-journal/v1"
ADAPTER_SCHEMA = "simplicio.fast.dev-cli-adapter/v1"
RECEIPT_SCHEMA = "simplicio.fast.binary-changeset-receipt/v1"
MAGIC = b"SFBCHG01"
JOURNAL_MAGIC = b"SFBJRN01"
HEADER = struct.Struct(">8sBBIII32s")
FRAME = struct.Struct(">I")
ZERO_HASH = "0" * 64
OP_TYPES = {"create", "replace-range", "rename", "delete"}


class BinaryChangeSetError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


class BinaryChangeSetUnknownEffect(BinaryChangeSetError):
    """The Dev CLI outcome is unknown and must be reconciled before retry."""


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise BinaryChangeSetError("json_encoding_invalid") from error


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(
        data if isinstance(data, bytes) else data.encode("utf-8")
    ).hexdigest()


def _sha(value: str | None, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value.lower())
    ):
        raise BinaryChangeSetError("sha256_invalid")
    return value.lower()


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value or ":" in value:
        raise BinaryChangeSetError("path_invalid")
    normalized = value.replace("\\", "/")
    raw_parts = normalized.split("/")
    if ".." in raw_parts or "." in raw_parts:
        raise BinaryChangeSetError("path_outside_repository", value)
    if any(not part for part in raw_parts):
        raise BinaryChangeSetError("path_invalid", value)
    candidate = PurePosixPath(normalized)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in {"", "."} for part in candidate.parts)
        or value in {".", ".."}
    ):
        raise BinaryChangeSetError("path_outside_repository", value)
    if normalized.startswith("/") or normalized.endswith("/") or "//" in normalized:
        raise BinaryChangeSetError("path_invalid", value)
    return normalized


def _text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BinaryChangeSetError(reason)
    return value


def _safe_path(root: Path, relative: str) -> Path:
    """Resolve a changeset path without following a repository symlink."""
    root = root.resolve()
    candidate = root / relative
    current = root
    try:
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.is_symlink():
                raise BinaryChangeSetError("path_symlink", relative)
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except BinaryChangeSetError:
        raise
    except (OSError, ValueError) as error:
        raise BinaryChangeSetError("path_outside_repository", relative) from error
    return candidate


def _worktree(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).name != value
        or value in {".", ".."}
    ):
        raise BinaryChangeSetError("worktree_invalid")
    return value


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise BinaryChangeSetError("content_encoding_invalid") from error


def _normalized_sha(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return sha256(data)
    return sha256(text.replace("\r\n", "\n").replace("\r", "\n"))


def _matches_hash(data: bytes, expected: str | None) -> bool:
    return expected is not None and expected in {sha256(data), _normalized_sha(data)}


# ---------------------------------------------------------------------------
# Section 1: JSON Changesets (simplicio.fast.changeset/v2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PreparedChange:
    path: Path
    relative: str
    expected_sha256: str
    original: bytes
    updated: bytes
    replacements: int


def _atomic_replace(path: Path, data: bytes) -> None:
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".simplicio-fast",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def _file_records(prepared: list[PreparedChange]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in prepared:
        current = item.path.read_bytes()
        records.append(
            {
                "path": item.relative,
                "replacements": item.replacements,
                "expected_sha256": item.expected_sha256,
                "before_sha256": hashlib.sha256(item.original).hexdigest(),
                "after_sha256": hashlib.sha256(current).hexdigest(),
                "result_sha256": hashlib.sha256(item.updated).hexdigest(),
                "byte_representation": "raw-file-bytes",
                "newline": "crlf" if b"\r\n" in item.updated else "lf",
            }
        )
    return records


def prepare_changes(changes: list[Any], root: Path | str) -> list[PreparedChange]:
    """Strictly prepare and validate line-bounded changes against root disk files."""
    root_path = Path(root).resolve()
    prepared: list[PreparedChange] = []
    for change in changes:
        relative = change.get("path")
        expected = change.get("expected_sha256")
        replacements = change.get("replacements")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("each change requires path and expected_sha256")
        path = (root_path / relative).resolve()
        try:
            path.relative_to(root_path)
        except ValueError as error:
            raise ValueError(f"change path escapes root: {relative}") from error
        if not path.is_file():
            raise ValueError(f"source file missing: {relative}")
        original = path.read_bytes()
        actual = hashlib.sha256(original).hexdigest()
        if actual != expected:
            raise ValueError(f"stale source hash for {relative}")
        if not isinstance(replacements, list) or not replacements:
            raise ValueError(f"change requires replacements: {relative}")
        decoded = original.decode("utf-8")
        newline = "\r\n" if b"\r\n" in original else "\n"
        lines = decoded.splitlines(keepends=True)
        normalized: list[tuple[int, int, str]] = []
        for replacement in replacements:
            start = replacement.get("start_line")
            end = replacement.get("end_line")
            content = replacement.get("content")
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or not isinstance(content, str)
                or start < 1
                or end < start
                or end > len(lines)
            ):
                raise ValueError(f"invalid line replacement for {relative}")
            normalized.append((start, end, content))
        normalized.sort(reverse=True)
        for index, (start, end, content) in enumerate(normalized):
            if index and end >= normalized[index - 1][0]:
                raise ValueError(f"overlapping replacements for {relative}")
            canonical_content = content.replace("\r\n", "\n").replace("\r", "\n")
            canonical_content = canonical_content.replace("\n", newline)
            suffix = (
                newline
                if canonical_content and not canonical_content.endswith(newline)
                else ""
            )
            lines[start - 1 : end] = [canonical_content + suffix]
        updated = "".join(lines)
        prepared.append(
            PreparedChange(
                path=path,
                relative=relative,
                expected_sha256=expected,
                original=original,
                updated=updated.encode("utf-8"),
                replacements=len(replacements),
            )
        )
    return prepared


def validate_changeset(
    changeset: dict[str, Any] | str | Path,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate a changeset against repository source files."""
    root_path = Path(root or Path.cwd()).resolve()
    if isinstance(changeset, (str, Path)):
        changeset = load_changeset(Path(changeset))
    if changeset.get("schema") != CHANGESET_SCHEMA_V2:
        raise ValueError(f"unsupported changeset schema: {changeset.get('schema')}")
    changes = changeset.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("changeset must contain at least one change")
    prepared = prepare_changes(changes, root=root_path)
    return {
        "schema": CHANGESET_VALIDATION_SCHEMA_V2,
        "status": "valid",
        "files": [
            {
                "path": item.relative,
                "replacements": item.replacements,
                "expected_sha256": item.expected_sha256,
                "before_sha256": hashlib.sha256(item.original).hexdigest(),
                "result_sha256": hashlib.sha256(item.updated).hexdigest(),
                "newline": "crlf" if b"\r\n" in item.updated else "lf",
            }
            for item in prepared
        ],
    }


def apply_changeset(
    changeset: dict[str, Any],
    root: Path | str | None = None,
    *,
    write: bool = False,
) -> dict[str, Any]:
    """Validate and optionally apply changeset modifications atomically."""
    root_path = Path(root or Path.cwd()).resolve()
    if changeset.get("schema") != CHANGESET_SCHEMA_V2:
        raise ValueError("unsupported changeset schema")
    changes = changeset.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("changeset must contain at least one change")
    prepared = prepare_changes(changes, root=root_path)

    applied: list[PreparedChange] = []
    if write:
        try:
            for item in prepared:
                if item.path.read_bytes() != item.original:
                    raise ValueError(f"stale source hash for {item.relative}")
                _atomic_replace(item.path, item.updated)
                applied.append(item)
        except Exception:
            for item in reversed(applied):
                _atomic_replace(item.path, item.original)
            raise

    files = _file_records(prepared)
    return {
        "schema": APPLY_RECEIPT_SCHEMA_V2,
        "mode": "write" if write else "dry-run",
        "outcome": "applied" if write else "dry_run",
        "applied": write,
        "write_attempted": write,
        "no_write_proof": not write,
        "files": files,
        "reason_code": None,
        "rollback": {
            "attempted": False,
            "status": "not-needed",
            "restored_paths": [],
        },
    }


def load_changeset(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("changeset root must be an object")
    return value


# ---------------------------------------------------------------------------
# Section 2: Binary Changesets (simplicio.fast.binary-changeset/v1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChangeOperation:
    op: str
    path: str
    before_sha256: str | None = None
    after_sha256: str | None = None
    dest: str | None = None
    content_b64: str | None = None
    encoding: str | None = None
    line_map: dict[str, int] | None = None
    line_map_sha256: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ChangeOperation:
        if not isinstance(value, Mapping):
            raise BinaryChangeSetError("operation_invalid")
        raw_op = value.get("op", "")
        if not isinstance(raw_op, str):
            raise BinaryChangeSetError("operation_type_invalid")
        op = raw_op.replace("_", "-")
        if op not in OP_TYPES:
            raise BinaryChangeSetError("operation_type_invalid", op)
        path = _path(_text(value.get("path", ""), "path_invalid"))
        dest = (
            _path(_text(value["dest"], "path_invalid"))
            if value.get("dest") is not None
            else None
        )
        before = _sha(value.get("before_sha256"))
        after = _sha(value.get("after_sha256"))
        content_b64 = value.get("content_b64")
        if content_b64 is None and value.get("content") is not None:
            content = value["content"]
            if not isinstance(content, str):
                raise BinaryChangeSetError("content_invalid")
            content_b64 = _b64(content.encode("utf-8"))
        if content_b64 is not None:
            if not isinstance(content_b64, str):
                raise BinaryChangeSetError("content_encoding_invalid")
            _unb64(content_b64)
        line_map: dict[str, int] | None = None
        line_map_sha256: str | None = None
        if op == "replace-range":
            if any(
                key in value
                for key in ("byte_start", "byte_end", "offset", "byte_offset")
            ):
                raise BinaryChangeSetError("ambiguous_byte_offset")
            encoding = _text(value.get("encoding", "utf-8"), "encoding_required")
            raw_line_map = value.get("line_map")
            if raw_line_map is None:
                start = value.get("start_line", value.get("line_start"))
                end = value.get("end_line", value.get("line_end"))
                if (
                    isinstance(start, bool)
                    or not isinstance(start, int)
                    or isinstance(end, bool)
                    or not isinstance(end, int)
                ):
                    raise BinaryChangeSetError("line_map_required")
                raw_line_map = {"start_line": start, "end_line": end}
            if not isinstance(raw_line_map, Mapping):
                raise BinaryChangeSetError("line_map_invalid")
            start_line = raw_line_map.get("start_line")
            end_line = raw_line_map.get("end_line")
            if (
                isinstance(start_line, bool)
                or not isinstance(start_line, int)
                or isinstance(end_line, bool)
                or not isinstance(end_line, int)
            ):
                raise BinaryChangeSetError("line_map_invalid")
            line_map = {
                "start_line": start_line,
                "end_line": end_line,
            }
            if (
                line_map["start_line"] < 1
                or line_map["end_line"] < line_map["start_line"]
            ):
                raise BinaryChangeSetError("line_map_invalid")
            supplied_map_hash = value.get("line_map_sha256")
            expected_map_hash = sha256(canonical(line_map))
            if supplied_map_hash is not None and not isinstance(supplied_map_hash, str):
                raise BinaryChangeSetError("line_map_hash_invalid")
            if supplied_map_hash is not None and supplied_map_hash != expected_map_hash:
                raise BinaryChangeSetError("line_map_hash_mismatch")
            line_map_sha256 = expected_map_hash
        else:
            encoding = (
                _text(value["encoding"], "encoding_invalid")
                if value.get("encoding") is not None
                else None
            )
            line_map = None
            if value.get("line_map_sha256") is not None:
                line_map_sha256 = _text(value["line_map_sha256"], "line_map_hash_invalid")
        if op == "create" and (content_b64 is None or after is None):
            raise BinaryChangeSetError("create_payload_missing")
        if op == "replace-range" and (
            content_b64 is None or before is None or after is None
        ):
            raise BinaryChangeSetError("replace_payload_missing")
        if op == "rename" and (dest is None or before is None or after is None):
            raise BinaryChangeSetError("rename_payload_missing")
        if op == "delete" and before is None:
            raise BinaryChangeSetError("delete_payload_missing")
        if op == "rename" and dest == path:
            raise BinaryChangeSetError("rename_destination_invalid")
        return cls(
            op,
            path,
            before,
            after,
            dest,
            content_b64,
            encoding,
            line_map,
            line_map_sha256,
        )

    def content(self) -> bytes | None:
        return _unb64(self.content_b64) if self.content_b64 is not None else None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "op": self.op,
            "path": self.path,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
        }
        if self.dest is not None:
            value["dest"] = self.dest
        if self.content_b64 is not None:
            value["content_b64"] = self.content_b64
            try:
                raw_c = self.content()
                if raw_c is not None:
                    value["content"] = raw_c.decode(self.encoding or "utf-8")
            except (UnicodeDecodeError, AttributeError):
                pass
        if self.encoding is not None:
            value["encoding"] = self.encoding
        if self.line_map is not None:
            value["line_map"] = dict(self.line_map)
            value["line_map_sha256"] = self.line_map_sha256
        return value


@dataclass(frozen=True, slots=True)
class BinaryChangeSet:
    repository: str
    base_generation: str
    overlay_generation: str
    attempt: str
    worktree_id: str
    lease_id: str
    fencing_token: str
    allowed_paths: tuple[str, ...]
    operations: tuple[ChangeOperation, ...]
    verification_commands: tuple[str, ...] = field(default_factory=tuple)
    schema: str = BINARY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != BINARY_SCHEMA:
            raise BinaryChangeSetError("schema_invalid")
        if (
            not self.repository
            or not self.base_generation
            or not self.overlay_generation
            or not self.attempt
        ):
            raise BinaryChangeSetError("binding_missing")
        _worktree(self.worktree_id)
        if not self.lease_id or not self.fencing_token:
            raise BinaryChangeSetError("authority_missing")
        if not isinstance(self.allowed_paths, (tuple, list)) or any(
            not isinstance(path, str) or not path.strip() for path in self.allowed_paths
        ):
            raise BinaryChangeSetError("allowed_paths_invalid")
        if not isinstance(self.operations, (tuple, list)) or any(
            not isinstance(operation, ChangeOperation) for operation in self.operations
        ):
            raise BinaryChangeSetError("operations_invalid")
        if not isinstance(self.verification_commands, (tuple, list)) or any(
            not isinstance(command, str) or not command.strip()
            for command in self.verification_commands
        ):
            raise BinaryChangeSetError("verification_commands_invalid")
        allowed = tuple(sorted({_path(path) for path in self.allowed_paths}))
        if not allowed:
            raise BinaryChangeSetError("allowed_paths_missing")
        if not self.operations:
            raise BinaryChangeSetError("operations_missing")
        for operation in self.operations:
            for path in (operation.path, operation.dest):
                if path is not None and path not in allowed:
                    raise BinaryChangeSetError("path_not_allowed", path)
        object.__setattr__(self, "allowed_paths", allowed)
        object.__setattr__(self, "operations", tuple(self.operations))
        object.__setattr__(
            self,
            "verification_commands",
            tuple(self.verification_commands),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BinaryChangeSet:
        if not isinstance(value, Mapping):
            raise BinaryChangeSetError("changeset_invalid")
        if value.get("schema") != BINARY_SCHEMA:
            raise BinaryChangeSetError("schema_invalid")
        raw_operations = value.get("operations", ())
        if not isinstance(raw_operations, (tuple, list)):
            raise BinaryChangeSetError("operations_invalid")
        operations = tuple(
            ChangeOperation.from_dict(item) for item in raw_operations
        )
        raw_allowed = value.get("allowed_paths")
        if raw_allowed is not None and not isinstance(raw_allowed, (tuple, list)):
            raise BinaryChangeSetError("allowed_paths_invalid")
        allowed = (
            tuple(_text(item, "allowed_paths_invalid") for item in raw_allowed)
            if raw_allowed is not None and raw_allowed
            else tuple(
                sorted(
                    {
                        path
                        for operation in operations
                        for path in (operation.path, operation.dest)
                        if path
                    }
                )
            )
        )
        fields = (
            ("repository", "binding_missing"),
            ("base_generation", "binding_missing"),
            ("overlay_generation", "binding_missing"),
            ("attempt", "binding_missing"),
            ("worktree_id", "worktree_invalid"),
            ("lease_id", "authority_missing"),
            ("fencing_token", "authority_missing"),
        )
        identity = {name: _text(value.get(name, ""), reason) for name, reason in fields}
        raw_commands = value.get("verification_commands", ())
        if not isinstance(raw_commands, (tuple, list)) or any(
            not isinstance(item, str) or not item.strip() for item in raw_commands
        ):
            raise BinaryChangeSetError("verification_commands_invalid")
        result = cls(
            **identity,
            allowed_paths=allowed,
            operations=operations,
            verification_commands=tuple(raw_commands),
        )
        supplied = value.get("changeset_id")
        if supplied is not None and supplied != result.changeset_id:
            raise BinaryChangeSetError("changeset_id_mismatch")
        return result

    @property
    def changeset_id(self) -> str:
        return sha256(canonical(self.identity()))

    def identity(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository": self.repository,
            "base_generation": self.base_generation,
            "overlay_generation": self.overlay_generation,
            "attempt": self.attempt,
            "worktree_id": self.worktree_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "allowed_paths": list(self.allowed_paths),
            "operations": [operation.to_dict() for operation in self.operations],
            "verification_commands": list(self.verification_commands),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity(), "changeset_id": self.changeset_id}

    def validate(
        self,
        root: Path,
        *,
        lease_id: str | None = None,
        fencing_token: str | None = None,
    ) -> dict[str, Any]:
        root = root.resolve()
        if self.repository != str(root):
            raise BinaryChangeSetError("repository_mismatch")
        if lease_id is not None and self.lease_id != lease_id:
            raise BinaryChangeSetError("lease_mismatch")
        if fencing_token is not None and self.fencing_token != fencing_token:
            raise BinaryChangeSetError("fence_mismatch")
        safe_paths = {
            path: _safe_path(root, path)
            for operation in self.operations
            for path in (operation.path, operation.dest)
            if path is not None
        }
        state: dict[str, bytes | None] = {}
        statuses: list[dict[str, Any]] = []
        for operation in self.operations:
            current = state.get(operation.path, _read_bytes_safe(safe_paths[operation.path]))
            if operation.op == "create":
                expected = operation.after_sha256
                if current is None:
                    state[operation.path] = operation.content()
                    statuses.append({"path": operation.path, "status": "ready"})
                elif _matches_hash(current, expected):
                    statuses.append({"path": operation.path, "status": "idempotent"})
                else:
                    raise BinaryChangeSetError("target_exists", operation.path)
            elif operation.op == "replace-range":
                if current is None:
                    raise BinaryChangeSetError("source_missing", operation.path)
                if _matches_hash(current, operation.after_sha256):
                    statuses.append({"path": operation.path, "status": "idempotent"})
                    continue
                if not _matches_hash(current, operation.before_sha256):
                    raise BinaryChangeSetError("stale_source", operation.path)
                updated = _replace(current, operation)
                if not _matches_hash(updated, operation.after_sha256):
                    raise BinaryChangeSetError("after_hash_mismatch", operation.path)
                state[operation.path] = updated
                statuses.append({"path": operation.path, "status": "ready"})
            elif operation.op == "rename":
                if current is None:
                    destination = state.get(
                        operation.dest or "", _read_bytes_safe(safe_paths[str(operation.dest)])
                    )
                    if destination is not None and _matches_hash(
                        destination, operation.after_sha256
                    ):
                        statuses.append(
                            {"path": operation.path, "status": "idempotent"}
                        )
                        continue
                    raise BinaryChangeSetError("source_missing", operation.path)
                if not _matches_hash(current, operation.before_sha256):
                    raise BinaryChangeSetError("stale_source", operation.path)
                destination = state.get(
                    operation.dest or "", _read_bytes_safe(safe_paths[str(operation.dest)])
                )
                if destination is not None:
                    raise BinaryChangeSetError(
                        "rename_destination_exists", str(operation.dest)
                    )
                state[operation.dest or ""] = current
                state[operation.path] = None
                statuses.append({"path": operation.path, "status": "ready"})
            elif operation.op == "delete":
                if current is None:
                    statuses.append({"path": operation.path, "status": "idempotent"})
                elif not _matches_hash(current, operation.before_sha256):
                    raise BinaryChangeSetError("stale_source", operation.path)
                else:
                    state[operation.path] = None
                    statuses.append({"path": operation.path, "status": "ready"})
        return {
            "schema": "simplicio.fast.binary-changeset-validation/v1",
            "changeset_id": self.changeset_id,
            "status": "valid",
            "operations": statuses,
            "idempotent": all(item["status"] == "idempotent" for item in statuses),
        }

    def encode(self) -> bytes:
        metadata = canonical(self.to_dict())
        records = b"".join(
            FRAME.pack(len(payload)) + payload + hashlib.sha256(payload).digest()
            for payload in (
                canonical(operation.to_dict()) for operation in self.operations
            )
        )
        digest = hashlib.sha256(metadata + records).digest()
        return (
            HEADER.pack(
                MAGIC, 1, 0, len(metadata), len(self.operations), len(records), digest
            )
            + metadata
            + records
        )

    def seal_to(self, path: Path) -> dict[str, Any]:
        payload = self.encode()
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "sealed",
            "changeset_id": self.changeset_id,
            "binary_sha256": sha256(payload),
            "bytes": len(payload),
            "path": str(path),
        }


def _read_bytes_safe(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _replace(current: bytes, operation: ChangeOperation) -> bytes:
    if operation.encoding is None or operation.line_map is None:
        raise BinaryChangeSetError("line_map_required")
    try:
        text = current.decode(operation.encoding)
        content_bytes = operation.content() or b""
        replacement = content_bytes.decode(operation.encoding)
    except UnicodeDecodeError as error:
        raise BinaryChangeSetError("encoding_mismatch", operation.path) from error
    lines = text.splitlines(keepends=True)
    start = operation.line_map["start_line"]
    end = operation.line_map["end_line"]
    if end > len(lines):
        raise BinaryChangeSetError("line_map_out_of_range", operation.path)
    newline = "\r\n" if "\r\n" in text else "\n"
    if (
        replacement
        and not replacement.endswith(("\n", "\r"))
        and lines[end - 1].endswith(("\n", "\r"))
    ):
        replacement += newline
    replacement = (
        replacement.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    )
    lines[start - 1 : end] = [replacement]
    return "".join(lines).encode(operation.encoding)


def decode_binary(payload: bytes) -> BinaryChangeSet:
    if len(payload) < HEADER.size:
        raise BinaryChangeSetError("binary_truncated")
    magic, version, flags, metadata_len, record_count, section_len, digest = (
        HEADER.unpack(payload[: HEADER.size])
    )
    if magic != MAGIC or version != 1 or flags != 0:
        raise BinaryChangeSetError("binary_header_invalid")
    end_metadata = HEADER.size + metadata_len
    end_section = end_metadata + section_len
    if end_section != len(payload):
        raise BinaryChangeSetError("binary_length_mismatch")
    metadata = payload[HEADER.size : end_metadata]
    section = payload[end_metadata:end_section]
    if hashlib.sha256(metadata + section).digest() != digest:
        raise BinaryChangeSetError("binary_checksum_mismatch")
    try:
        value = json.loads(metadata)
    except json.JSONDecodeError as error:
        raise BinaryChangeSetError("metadata_invalid") from error
    operations: list[dict[str, Any]] = []
    offset = 0
    for _ in range(record_count):
        if offset + FRAME.size > len(section):
            raise BinaryChangeSetError("record_truncated")
        length = FRAME.unpack(section[offset : offset + FRAME.size])[0]
        offset += FRAME.size
        end = offset + length
        if end + 32 > len(section):
            raise BinaryChangeSetError("record_truncated")
        record = section[offset:end]
        checksum = section[end : end + 32]
        if hashlib.sha256(record).digest() != checksum:
            raise BinaryChangeSetError("record_checksum_mismatch")
        try:
            operations.append(json.loads(record))
        except json.JSONDecodeError as error:
            raise BinaryChangeSetError("record_invalid") from error
        offset = end + 32
    if offset != len(section):
        raise BinaryChangeSetError("section_length_mismatch")
    value["operations"] = operations
    return BinaryChangeSet.from_dict(value)


def read_binary(path: Path) -> BinaryChangeSet:
    try:
        return decode_binary(path.read_bytes())
    except FileNotFoundError as error:
        raise BinaryChangeSetError("binary_missing") from error


def inspect_binary(payload: bytes | Path) -> dict[str, Any]:
    raw = payload.read_bytes() if isinstance(payload, Path) else payload
    changeset = decode_binary(raw)
    return {
        "schema": "simplicio.fast.binary-changeset-inspection/v1",
        "status": "valid",
        "changeset_id": changeset.changeset_id,
        "binary_sha256": sha256(raw),
        "bytes": len(raw),
        "repository": changeset.repository,
        "base_generation": changeset.base_generation,
        "overlay_generation": changeset.overlay_generation,
        "worktree_id": changeset.worktree_id,
        "operation_count": len(changeset.operations),
        "operations": [operation.op for operation in changeset.operations],
    }


def prepare_from_json(
    value: Mapping[str, Any],
    *,
    root: Path,
    base_generation: str = "",
    overlay_generation: str = "",
    attempt: str = "attempt-1",
    worktree_id: str = "worktree-1",
    lease_id: str = "lease-1",
    fencing_token: str = "fence-1",  # noqa: S107
    allowed_paths: Iterable[str] | None = None,
    verification_commands: Iterable[str] = (),
) -> BinaryChangeSet:
    """Prepare a BinaryChangeSet from a JSON intent or v2 changeset."""
    root = root.resolve()
    raw_ops = value.get("operations")
    if raw_ops is None and "changes" in value:
        changes = value.get("changes", ())
        if changes and isinstance(changes[0], dict) and "op" in changes[0]:
            raw_ops = changes
        else:
            # Convert v2 changeset changes to operations
            prepared = prepare_changes(changes, root=root)
            raw_ops = []
            for p in prepared:
                total_lines = len(p.original.decode("utf-8", errors="replace").splitlines()) or 1
                line_map = {"start_line": 1, "end_line": total_lines}
                raw_ops.append(
                    {
                        "op": "replace-range",
                        "path": p.relative,
                        "before_sha256": p.expected_sha256,
                        "after_sha256": hashlib.sha256(p.updated).hexdigest(),
                        "content_b64": _b64(p.updated),
                        "encoding": "utf-8",
                        "line_map": line_map,
                        "line_map_sha256": sha256(canonical(line_map)),
                    }
                )
    elif raw_ops is None:
        raw_ops = ()

    operations = tuple(ChangeOperation.from_dict(item) for item in raw_ops)
    return BinaryChangeSet(
        repository=str(root),
        base_generation=base_generation or ("0" * 64),
        overlay_generation=overlay_generation or ("0" * 64),
        attempt=attempt or "attempt-1",
        worktree_id=worktree_id or "worktree-1",
        lease_id=lease_id or "lease-1",
        fencing_token=fencing_token or "fence-1",
        allowed_paths=tuple(
            allowed_paths
            or [
                path
                for operation in operations
                for path in (operation.path, operation.dest)
                if path
            ]
        ),
        operations=operations,
        verification_commands=tuple(verification_commands),
    )


# ---------------------------------------------------------------------------
# Section 3: CLI Dispatch
# ---------------------------------------------------------------------------

def run_changeset_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-mapper changeset",
        description="Public changeset lifecycle (validation, preparation, sealing).",
    )
    subparsers = parser.add_subparsers(dest="changeset_action", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate a changeset file")
    validate_parser.add_argument("file", help="path to changeset JSON or binary (.sfc)")
    validate_parser.add_argument("--root", default=".", help="repository root")
    validate_parser.add_argument("--lease-id", default=None)
    validate_parser.add_argument("--fencing-token", default=None)

    prepare_parser = subparsers.add_parser("prepare", help="prepare a sealed binary changeset")
    prepare_parser.add_argument("input_json", help="path to input JSON changeset")
    prepare_parser.add_argument("--root", default=".", help="repository root")
    prepare_parser.add_argument("--output", default=None, help="output path for sealed binary changeset")
    prepare_parser.add_argument("--base-generation", default="0" * 64)
    prepare_parser.add_argument("--overlay-generation", default="0" * 64)
    prepare_parser.add_argument("--attempt", default="attempt-1")
    prepare_parser.add_argument("--worktree-id", default="worktree-1")
    prepare_parser.add_argument("--lease-id", default="lease-1")
    prepare_parser.add_argument("--fencing-token", default="fence-1")
    prepare_parser.add_argument("--allowed-path", action="append", default=None)
    prepare_parser.add_argument("--verification-command", action="append", default=[])

    args = parser.parse_args(list(argv))
    root_path = Path(args.root).resolve()

    if args.changeset_action == "validate":
        target = Path(args.file)
        if not target.is_file():
            print(json.dumps({"status": "error", "message": f"file not found: {args.file}"}))
            return 1
        raw_header = target.read_bytes()[:8]
        if raw_header == MAGIC:
            cs = read_binary(target)
            val = cs.validate(root_path, lease_id=args.lease_id, fencing_token=args.fencing_token)
            print(json.dumps({
                "schema": "simplicio.fast.binary-changeset-cli-validation/v1",
                "status": "valid",
                "changeset_id": cs.changeset_id,
                "validation": val,
            }, indent=2, sort_keys=True))
            return 0
        else:
            try:
                data = load_changeset(target)
                if data.get("schema") == CHANGESET_SCHEMA_V2:
                    res = validate_changeset(data, root=root_path)
                    print(json.dumps(res, indent=2, sort_keys=True))
                    return 0
                elif data.get("schema") == BINARY_SCHEMA:
                    cs = BinaryChangeSet.from_dict(data)
                    val = cs.validate(root_path, lease_id=args.lease_id, fencing_token=args.fencing_token)
                    print(json.dumps({
                        "schema": "simplicio.fast.binary-changeset-cli-validation/v1",
                        "status": "valid",
                        "changeset_id": cs.changeset_id,
                        "validation": val,
                    }, indent=2, sort_keys=True))
                    return 0
                else:
                    print(json.dumps({"status": "error", "message": f"unrecognized schema: {data.get('schema')}"}))
                    return 1
            except Exception as error:  # noqa: BLE001
                print(json.dumps({"status": "error", "message": str(error)}))
                return 1

    elif args.changeset_action == "prepare":
        input_path = Path(args.input_json)
        if not input_path.is_file():
            print(json.dumps({"status": "error", "message": f"file not found: {args.input_json}"}))
            return 1
        data = load_changeset(input_path)
        output_path = Path(args.output) if args.output else input_path.with_suffix(".sfc")
        cs = prepare_from_json(
            data,
            root=root_path,
            base_generation=args.base_generation,
            overlay_generation=args.overlay_generation,
            attempt=args.attempt,
            worktree_id=args.worktree_id,
            lease_id=args.lease_id,
            fencing_token=args.fencing_token,
            allowed_paths=args.allowed_path,
            verification_commands=args.verification_command,
        )
        receipt = cs.seal_to(output_path)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0

    return 0


__all__ = [
    "CHANGESET_SCHEMA_V2",
    "CHANGESET_VALIDATION_SCHEMA_V2",
    "APPLY_RECEIPT_SCHEMA_V2",
    "BINARY_SCHEMA",
    "PreparedChange",
    "ChangeOperation",
    "BinaryChangeSet",
    "BinaryChangeSetError",
    "prepare_changes",
    "validate_changeset",
    "apply_changeset",
    "load_changeset",
    "prepare_from_json",
    "decode_binary",
    "read_binary",
    "inspect_binary",
    "run_changeset_cli",
]
