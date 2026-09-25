"""Append-only binary changesets for isolated worktree execution.

The binary layer is disposable derived state. Source files and the shared Fast
snapshot remain authoritative; materialization is delegated to Dev CLI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping


SCHEMA = "simplicio.fast.binary-changeset/v1"
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
    def from_dict(cls, value: Mapping[str, Any]) -> "ChangeOperation":
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
        line_map = None
        line_map_sha256 = None
        line_map: dict[str, int] | None = None
        line_map_sha256: str | None = None
        if op == "replace-range":
            if any(
                key in value
                for key in ("byte_start", "byte_end", "offset", "byte_offset")
            ):
                raise BinaryChangeSetError("ambiguous_byte_offset")
            encoding = _text(value.get("encoding", "utf-8"), "encoding_required")
            line_map = value.get("line_map")
            if line_map is None:
                start = value.get("start_line", value.get("line_start"))
                end = value.get("end_line", value.get("line_end"))
                if (
                    isinstance(start, bool)
                    or not isinstance(start, int)
                    or isinstance(end, bool)
                    or not isinstance(end, int)
                ):
                    raise BinaryChangeSetError("line_map_required")
                line_map = {"start_line": start, "end_line": end}
            if not isinstance(line_map, Mapping):
                raise BinaryChangeSetError("line_map_invalid")
            start_line = line_map.get("start_line")
            end_line = line_map.get("end_line")
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
                value["content"] = self.content().decode(self.encoding or "utf-8")
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
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
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
    def from_dict(cls, value: Mapping[str, Any]) -> "BinaryChangeSet":
        if not isinstance(value, Mapping):
            raise BinaryChangeSetError("changeset_invalid")
        if value.get("schema") != SCHEMA:
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
            current = state.get(operation.path, _read(safe_paths[operation.path]))
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
                        operation.dest or "", _read(safe_paths[str(operation.dest)])
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
                    operation.dest or "", _read(safe_paths[str(operation.dest)])
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


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _replace(current: bytes, operation: ChangeOperation) -> bytes:
    if operation.encoding is None or operation.line_map is None:
        raise BinaryChangeSetError("line_map_required")
    try:
        text = current.decode(operation.encoding)
        replacement = (operation.content() or b"").decode(operation.encoding)
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


class BinaryChangeJournal:
    def __init__(
        self, path: Path, *, worktree_id: str, lease_id: str, fencing_token: str
    ) -> None:
        self.path = path.resolve()
        self.worktree_id = _worktree(worktree_id)
        self.lease_id = lease_id
        self.fencing_token = fencing_token

    def _ensure_header(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("wb") as handle:
            handle.write(JOURNAL_MAGIC + b"\x01")
            handle.flush()
            os.fsync(handle.fileno())

    def read(self, *, recover: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if not raw.startswith(JOURNAL_MAGIC + b"\x01"):
            raise BinaryChangeSetError("journal_header_invalid")
        events: list[dict[str, Any]] = []
        offset = len(JOURNAL_MAGIC) + 1
        while offset < len(raw):
            frame_start = offset
            if offset + FRAME.size > len(raw):
                if recover:
                    break
                raise BinaryChangeSetError("journal_truncated_tail")
            length = FRAME.unpack(raw[offset : offset + FRAME.size])[0]
            offset += FRAME.size
            end = offset + length
            if end + 32 > len(raw):
                if recover:
                    break
                raise BinaryChangeSetError("journal_truncated_tail")
            body = raw[offset:end]
            supplied = raw[end : end + 32].hex()
            offset = end + 32
            try:
                event = json.loads(body)
            except json.JSONDecodeError as error:
                raise BinaryChangeSetError("journal_record_invalid") from error
            previous = events[-1]["record_hash"] if events else ZERO_HASH
            material = {
                key: value for key, value in event.items() if key != "record_hash"
            }
            expected = sha256(previous + canonical(material).decode())
            if (
                supplied != expected
                or event.get("record_hash") != supplied
                or event.get("prev_hash") != previous
            ):
                raise BinaryChangeSetError("journal_chain_mismatch")
            if (
                event.get("worktree_id") != self.worktree_id
                or event.get("lease_id") != self.lease_id
                or event.get("fencing_token") != self.fencing_token
            ):
                raise BinaryChangeSetError("journal_authority_mismatch")
            events.append(event)
            if frame_start == offset:
                raise BinaryChangeSetError("journal_cursor_stalled")
        return events

    def append(
        self,
        changeset: BinaryChangeSet,
        state: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if changeset.worktree_id != self.worktree_id:
            raise BinaryChangeSetError("cross_worktree")
        if changeset.lease_id != self.lease_id:
            raise BinaryChangeSetError("lease_mismatch")
        if changeset.fencing_token != self.fencing_token:
            raise BinaryChangeSetError("fence_mismatch")
        events = self.read()
        for event in events:
            if (
                event.get("changeset_id") == changeset.changeset_id
                and event.get("state") == state
            ):
                return dict(event, idempotent=True)
        previous = events[-1]["record_hash"] if events else ZERO_HASH
        event = {
            "schema": JOURNAL_SCHEMA,
            "sequence": len(events) + 1,
            "changeset_id": changeset.changeset_id,
            "binary_sha256": sha256(changeset.encode()),
            "worktree_id": self.worktree_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "state": state,
            "prev_hash": previous,
            "evidence": dict(evidence or {}),
        }
        material = {key: value for key, value in event.items() if key != "record_hash"}
        event["record_hash"] = sha256(previous + canonical(material).decode())
        payload = canonical(event)
        self._ensure_header()
        with self.path.open("ab") as handle:
            handle.write(
                FRAME.pack(len(payload)) + payload + bytes.fromhex(event["record_hash"])
            )
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def recover(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema": "simplicio.fast.binary-changeset-recovery/v1",
                "status": "valid",
                "records": 0,
                "truncated_bytes": 0,
            }
        raw = self.path.read_bytes()
        events = self.read(recover=True)
        valid_end = len(JOURNAL_MAGIC) + 1
        for event in events:
            payload = canonical(event)
            valid_end += FRAME.size + len(payload) + 32
        truncated = max(0, len(raw) - valid_end)
        if truncated:
            with self.path.open("r+b") as handle:
                handle.truncate(valid_end)
                handle.flush()
                os.fsync(handle.fileno())
        return {
            "schema": "simplicio.fast.binary-changeset-recovery/v1",
            "status": "recovered" if truncated else "valid",
            "records": len(events),
            "truncated_bytes": truncated,
            "last_hash": events[-1]["record_hash"] if events else ZERO_HASH,
        }

    def inspect(self) -> dict[str, Any]:
        events = self.read()
        return {
            "schema": "simplicio.fast.binary-changeset-journal-inspection/v1",
            "status": "valid",
            "path": str(self.path),
            "worktree_id": self.worktree_id,
            "records": len(events),
            "states": [event["state"] for event in events],
            "last_hash": events[-1]["record_hash"] if events else ZERO_HASH,
        }


class DevCliAdapter:
    schema = ADAPTER_SCHEMA

    def materialize(self, changeset: BinaryChangeSet, root: Path) -> dict[str, Any]:
        root = root.resolve()
        safe_paths = {
            path: _safe_path(root, path)
            for operation in changeset.operations
            for path in (operation.path, operation.dest)
            if path is not None
        }
        operations: list[dict[str, Any]] = []
        for operation in changeset.operations:
            if operation.op == "create":
                operations.append(
                    {
                        "op": "create_file",
                        "path": operation.path,
                        "text": (operation.content() or b"").decode(
                            operation.encoding or "utf-8"
                        ),
                    }
                )
            elif operation.op == "replace-range":
                raw = safe_paths[operation.path].read_bytes()
                selected = _selected_range(raw, operation)
                operations.append(
                    {
                        "op": "replace_range",
                        "path": operation.path,
                        "start_line": operation.line_map["start_line"],
                        "end_line": operation.line_map["end_line"],
                        "text": _replacement_text(operation, selected),
                        "file_sha256": _normalized_sha(raw),
                        "range_sha256": _normalized_sha(selected),
                    }
                )
            elif operation.op == "rename":
                operations.append(
                    {
                        "op": "move_file",
                        "path": operation.path,
                        "dest": operation.dest,
                        "file_sha256": _normalized_sha(
                            safe_paths[operation.path].read_bytes()
                        ),
                    }
                )
            elif operation.op == "delete":
                operations.append(
                    {
                        "op": "delete_file",
                        "path": operation.path,
                        "file_sha256": _normalized_sha(
                            safe_paths[operation.path].read_bytes()
                        ),
                    }
                )
        plan = {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": sorted(
                {
                    path
                    for operation in changeset.operations
                    for path in (operation.path, operation.dest)
                    if path
                }
            ),
            "operations": operations,
            "validation": [],
        }
        executable = shutil.which("simplicio-dev-cli") or shutil.which("simplicio-py")
        if executable is None:
            raise BinaryChangeSetError("dev_cli_unavailable")
        try:
            completed = subprocess.run(
                [
                    executable,
                    "mechanical-edit",
                    "--root",
                    str(root),
                    "--plan",
                    "-",
                    "--apply",
                    "--json",
                ],
                input=json.dumps(plan, sort_keys=True, allow_nan=False),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BinaryChangeSetUnknownEffect(f"dev_cli_{type(error).__name__}") from error
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise BinaryChangeSetError("dev_cli_invalid_receipt") from error
        if (
            completed.returncode != 0
            or not isinstance(result, dict)
            or result.get("status") != "ok"
            or not result.get("applied")
        ):
            raise BinaryChangeSetError(
                "dev_cli_rejected", json.dumps(result, sort_keys=True, allow_nan=False)
            )
        return {"schema": ADAPTER_SCHEMA, "status": "applied", "result": result}


def _replacement_text(operation: ChangeOperation, selected: bytes) -> str:
    text = (operation.content() or b"").decode(operation.encoding or "utf-8")
    if text and not text.endswith(("\n", "\r")) and selected.endswith((b"\n", b"\r")):
        text += "\r\n" if selected.endswith(b"\r\n") else "\n"
    return text


def _selected_range(raw: bytes, operation: ChangeOperation) -> bytes:
    text = raw.decode(operation.encoding or "utf-8")
    lines = text.splitlines(keepends=True)
    start = operation.line_map["start_line"]
    end = operation.line_map["end_line"]
    if end > len(lines):
        raise BinaryChangeSetError("line_map_out_of_range")
    return "".join(lines[start - 1 : end]).encode(operation.encoding or "utf-8")


def refresh_semantic_inputs(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    command = [
        "simplicio-mapper",
        "delta",
        str(root),
        "--json",
        "--changed-paths",
        ",".join(sorted(set(paths))),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "status": "unverified",
            "reason": type(error).__name__,
            "command": command,
        }
    if completed.returncode != 0:
        return {
            "status": "unverified",
            "reason": "mapper_delta_failed",
            "command": command,
            "stderr": completed.stderr[-1000:],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"stdout": completed.stdout[-1000:]}
    return {"status": "refreshed", "command": command, "result": payload}


def materialize(
    changeset: BinaryChangeSet,
    root: Path,
    journal: BinaryChangeJournal,
    *,
    adapter: DevCliAdapter | None = None,
    refresh: Callable[[Path, Iterable[str]], dict[str, Any]] = refresh_semantic_inputs,
) -> dict[str, Any]:
    root = root.resolve()
    existing = journal.read()
    previous = next(
        (
            event
            for event in reversed(existing)
            if event.get("changeset_id") == changeset.changeset_id
        ),
        None,
    )
    if previous is not None and previous.get("state") in {"applied", "idempotent"}:
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "idempotent",
            "changeset_id": changeset.changeset_id,
            "journal": previous,
            "refresh": {"status": "not-needed"},
            "source_writer": "simplicio-dev-cli",
        }
    if previous is not None and previous.get("state") in {
        "unknown",
        "reconcile_ambiguous",
    }:
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "locked",
            "reason_code": "unknown_effect",
            "changeset_id": changeset.changeset_id,
            "journal": previous,
            "reconcile_required": True,
            "source_writer": "simplicio-dev-cli",
        }
    try:
        validation = changeset.validate(root)
        journal.append(changeset, "sealed", evidence={"validation": validation})
        if validation["idempotent"]:
            event = journal.append(
                changeset, "idempotent", evidence={"validation": validation}
            )
            return {
                "schema": RECEIPT_SCHEMA,
                "status": "idempotent",
                "changeset_id": changeset.changeset_id,
                "journal": event,
                "validation": validation,
                "refresh": {"status": "not-needed"},
                "source_writer": "simplicio-dev-cli",
            }
        applied = (adapter or DevCliAdapter()).materialize(changeset, root)
        after = changeset.validate(root)
        changed_paths = sorted(
            {
                path
                for operation in changeset.operations
                for path in (operation.path, operation.dest)
                if path is not None
            }
        )
        refresh_receipt = refresh(root, changed_paths)
        event = journal.append(
            changeset,
            "applied",
            evidence={
                "adapter": applied,
                "validation": after,
                "refresh": refresh_receipt,
            },
        )
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "applied",
            "changeset_id": changeset.changeset_id,
            "source_writer": "simplicio-dev-cli",
            "validation": after,
            "adapter": applied,
            "refresh": refresh_receipt,
            "journal": event,
        }
    except BinaryChangeSetUnknownEffect as error:
        evidence = {"reason_code": error.reason_code, "message": str(error)}
        try:
            event = journal.append(changeset, "unknown", evidence=evidence)
        except BinaryChangeSetError as journal_error:
            return {
                "schema": RECEIPT_SCHEMA,
                "status": "unknown",
                "reason_code": "unknown_effect",
                "changeset_id": changeset.changeset_id,
                "evidence": evidence,
                "journal_error": journal_error.reason_code,
                "reconcile_required": True,
                "source_writer": "simplicio-dev-cli",
            }
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "locked",
            "reason_code": "unknown_effect",
            "changeset_id": changeset.changeset_id,
            "evidence": evidence,
            "journal": event,
            "reconcile_required": True,
            "source_writer": "simplicio-dev-cli",
        }
    except BinaryChangeSetError as error:
        evidence = {"reason_code": error.reason_code, "message": str(error)}
        try:
            journal.append(changeset, "rejected", evidence=evidence)
        except BinaryChangeSetError:
            pass
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "rejected",
            "changeset_id": changeset.changeset_id,
            "reason_code": error.reason_code,
            "evidence": evidence,
            "source_writer": "simplicio-dev-cli",
    }


def reconcile_unknown_effect(
    changeset: BinaryChangeSet,
    root: Path,
    journal: BinaryChangeJournal,
) -> dict[str, Any]:
    """Reconcile a locked adapter outcome using source hashes before retry."""

    root = root.resolve()
    existing = journal.read()
    previous = next(
        (
            event
            for event in reversed(existing)
            if event.get("changeset_id") == changeset.changeset_id
        ),
        None,
    )
    if previous is None or previous.get("state") not in {
        "unknown",
        "reconciled",
    }:
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "rejected",
            "reason_code": "unknown_effect_missing",
            "changeset_id": changeset.changeset_id,
            "source_writer": "simplicio-dev-cli",
        }
    if previous.get("state") == "reconciled":
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "reconciled",
            "changeset_id": changeset.changeset_id,
            "reconciliation": previous.get("evidence", {}).get("reconciliation"),
            "journal": previous,
            "retry_allowed": previous.get("evidence", {}).get("retry_allowed", False),
            "source_writer": "simplicio-dev-cli",
        }
    try:
        validation = changeset.validate(root)
    except BinaryChangeSetError as error:
        evidence = {
            "reconciliation": "ambiguous",
            "reason_code": error.reason_code,
            "message": str(error),
            "retry_allowed": False,
        }
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "locked",
            "reason_code": "unknown_effect",
            "changeset_id": changeset.changeset_id,
            "evidence": evidence,
            "journal": previous,
            "reconcile_required": True,
            "source_writer": "simplicio-dev-cli",
        }
    if validation["idempotent"]:
        evidence = {
            "reconciliation": "already_applied",
            "unknown_record_hash": previous["record_hash"],
            "validation": validation,
            "retry_allowed": False,
        }
        event = journal.append(changeset, "applied", evidence=evidence)
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "reconciled",
            "changeset_id": changeset.changeset_id,
            "reconciliation": "already_applied",
            "journal": event,
            "retry_allowed": False,
            "source_writer": "simplicio-dev-cli",
        }
    evidence = {
        "reconciliation": "not_applied",
        "unknown_record_hash": previous["record_hash"],
        "validation": validation,
        "retry_allowed": True,
    }
    event = journal.append(changeset, "reconciled", evidence=evidence)
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "reconciled",
        "changeset_id": changeset.changeset_id,
        "reconciliation": "not_applied",
        "journal": event,
        "retry_allowed": True,
        "source_writer": "simplicio-dev-cli",
    }


def prepare_from_json(
    value: Mapping[str, Any],
    *,
    root: Path,
    base_generation: str,
    overlay_generation: str,
    attempt: str,
    worktree_id: str,
    lease_id: str,
    fencing_token: str,
    allowed_paths: Iterable[str] | None = None,
    verification_commands: Iterable[str] = (),
) -> BinaryChangeSet:
    operations = tuple(
        ChangeOperation.from_dict(item)
        for item in value.get("operations", value.get("changes", ()))
    )
    return BinaryChangeSet(
        repository=str(root.resolve()),
        base_generation=base_generation,
        overlay_generation=overlay_generation,
        attempt=attempt,
        worktree_id=worktree_id,
        lease_id=lease_id,
        fencing_token=fencing_token,
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
