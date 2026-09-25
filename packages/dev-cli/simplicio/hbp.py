"""Runtime-compatible HBP v1 evidence ledger.

The binary layout is owned by ``simplicio-runtime`` and intentionally mirrors
``src/hbp/mod.rs``.  This module is an additive adapter: existing JSONL
writers remain unchanged until an explicit migration and installed E2E prove
that every consumer can read HBP.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

HBP_SCHEMA = "simplicio.hbp/v1"
HBP_MAGIC = b"HBP1"
HBP_VERSION = 1
HBP_FLAGS = 0
HBP_GENESIS = "genesis"
HBP_FILE_NAME = "hbp-inbox.bin"
MAX_FIELD_BYTES = 4 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_LEDGER_BYTES = 64 * 1024 * 1024


class HbpError(ValueError):
    """Fail-closed HBP format or integrity error."""


@dataclass(frozen=True)
class HbpRow:
    seq: int
    timestamp: int
    topic: str
    payload: str
    provenance: str
    crypto_token: str | None
    prev_hash: str
    hash: str


def row_content_hash(
    seq: int,
    prev_hash: str,
    topic: str,
    payload: str,
    provenance: str,
    crypto_token: str | None,
) -> str:
    """Return the exact Runtime-compatible length-delimited row digest."""

    fields = (
        str(seq),
        prev_hash,
        topic,
        payload,
        provenance,
        crypto_token or "",
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(struct.pack("<Q", len(encoded)))
        digest.update(encoded)
    return digest.hexdigest()


def _put_string(out: bytearray, value: str, field: str) -> None:
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_FIELD_BYTES:
        raise HbpError(f"HBP {field} exceeds {MAX_FIELD_BYTES} bytes")
    out.extend(struct.pack("<I", len(encoded)))
    out.extend(encoded)


def _take(data: bytes, cursor: int, count: int) -> tuple[bytes, int]:
    end = cursor + count
    if end > len(data):
        raise HbpError("truncated HBP record")
    return data[cursor:end], end


def _take_string(data: bytes, cursor: int, field: str) -> tuple[str, int]:
    raw_length, cursor = _take(data, cursor, 4)
    length = struct.unpack("<I", raw_length)[0]
    if length > MAX_FIELD_BYTES:
        raise HbpError(f"HBP {field} exceeds {MAX_FIELD_BYTES} bytes")
    raw, cursor = _take(data, cursor, length)
    try:
        return raw.decode("utf-8"), cursor
    except UnicodeDecodeError as exc:
        raise HbpError(f"HBP {field} is not UTF-8") from exc


def _encode_record(row: HbpRow) -> bytes:
    body = bytearray()
    body.extend(struct.pack("<Q", row.seq))
    body.extend(struct.pack("<Q", row.timestamp))
    _put_string(body, row.topic, "topic")
    _put_string(body, row.payload, "payload")
    _put_string(body, row.provenance, "provenance")
    if row.crypto_token is None:
        body.append(0)
    else:
        body.append(1)
        _put_string(body, row.crypto_token, "crypto_token")
    _put_string(body, row.prev_hash, "prev_hash")
    _put_string(body, row.hash, "hash")
    if len(body) > MAX_RECORD_BYTES:
        raise HbpError(f"HBP record exceeds {MAX_RECORD_BYTES} bytes")
    return struct.pack("<I", len(body)) + body


def _decode_record(body: bytes) -> HbpRow:
    if len(body) > MAX_RECORD_BYTES:
        raise HbpError(f"HBP record exceeds {MAX_RECORD_BYTES} bytes")
    cursor = 0
    raw, cursor = _take(body, cursor, 8)
    seq = struct.unpack("<Q", raw)[0]
    raw, cursor = _take(body, cursor, 8)
    timestamp = struct.unpack("<Q", raw)[0]
    topic, cursor = _take_string(body, cursor, "topic")
    payload, cursor = _take_string(body, cursor, "payload")
    provenance, cursor = _take_string(body, cursor, "provenance")
    raw, cursor = _take(body, cursor, 1)
    marker = raw[0]
    if marker == 0:
        crypto_token = None
    elif marker == 1:
        crypto_token, cursor = _take_string(body, cursor, "crypto_token")
    else:
        raise HbpError("invalid HBP optional-token marker")
    prev_hash, cursor = _take_string(body, cursor, "prev_hash")
    row_hash, cursor = _take_string(body, cursor, "hash")
    if cursor != len(body):
        raise HbpError("trailing bytes in HBP record")
    return HbpRow(seq, timestamp, topic, payload, provenance, crypto_token, prev_hash, row_hash)


def _decode_file(raw: bytes) -> tuple[HbpRow, ...]:
    if not raw:
        return ()
    if len(raw) > MAX_LEDGER_BYTES:
        raise HbpError(f"HBP ledger exceeds {MAX_LEDGER_BYTES} bytes")
    if len(raw) < 8 or raw[:4] != HBP_MAGIC:
        raise HbpError("legacy or unknown HBP ledger; explicit migration is required")
    version, flags = struct.unpack("<HH", raw[4:8])
    if version != HBP_VERSION or flags != HBP_FLAGS:
        raise HbpError("unsupported HBP version or flags")

    rows: list[HbpRow] = []
    cursor = 8
    expected_seq = 0
    expected_prev = HBP_GENESIS
    while cursor < len(raw):
        length_raw, cursor = _take(raw, cursor, 4)
        length = struct.unpack("<I", length_raw)[0]
        if length > MAX_RECORD_BYTES:
            raise HbpError(f"HBP record exceeds {MAX_RECORD_BYTES} bytes")
        body, cursor = _take(raw, cursor, length)
        row = _decode_record(body)
        if row.seq != expected_seq:
            raise HbpError(f"HBP sequence gap at {row.seq}; expected {expected_seq}")
        if row.prev_hash != expected_prev:
            raise HbpError(f"HBP chain link mismatch at seq {row.seq}")
        expected_hash = row_content_hash(
            row.seq, row.prev_hash, row.topic, row.payload, row.provenance, row.crypto_token
        )
        if row.hash != expected_hash:
            raise HbpError(f"HBP content hash mismatch at seq {row.seq}")
        rows.append(row)
        expected_seq += 1
        expected_prev = row.hash
    return tuple(rows)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HbpError("HBP ledger is locked") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class HbpEvidenceLedger:
    """Append-only Runtime-compatible evidence ledger."""

    def __init__(self, directory: str | Path, *, file_name: str = HBP_FILE_NAME) -> None:
        self.directory = Path(directory)
        if not file_name or Path(file_name).name != file_name or file_name.endswith(".lock"):
            raise ValueError("HBP file_name must be a plain file name")
        self.path = self.directory / file_name
        self.lock_path = self.directory / f"{file_name}.lock"

    def rows(self) -> tuple[HbpRow, ...]:
        if not self.path.exists():
            return ()
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise HbpError("cannot read HBP ledger") from exc
        return _decode_file(raw)

    def verify(self) -> tuple[HbpRow, ...]:
        return self.rows()

    def __len__(self) -> int:
        return len(self.rows())

    def append(
        self,
        topic: str,
        payload: str,
        provenance: str,
        crypto_token: str | None = None,
        *,
        timestamp: int | None = None,
    ) -> HbpRow:
        self.directory.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(self.lock_path):
            rows = self.rows()
            previous_hash = rows[-1].hash if rows else HBP_GENESIS
            row = HbpRow(
                seq=len(rows),
                timestamp=int(time.time()) if timestamp is None else timestamp,
                topic=topic,
                payload=payload,
                provenance=provenance,
                crypto_token=crypto_token,
                prev_hash=previous_hash,
                hash=row_content_hash(len(rows), previous_hash, topic, payload, provenance, crypto_token),
            )
            encoded = _encode_record(row)
            current_size = self.path.stat().st_size if self.path.exists() else 0
            header = b"" if current_size else HBP_MAGIC + struct.pack("<HH", HBP_VERSION, HBP_FLAGS)
            if current_size + len(header) + len(encoded) > MAX_LEDGER_BYTES:
                raise HbpError(f"HBP ledger exceeds {MAX_LEDGER_BYTES} bytes")
            try:
                with self.path.open("ab") as handle:
                    if header:
                        handle.write(header)
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise HbpError("cannot append HBP ledger") from exc
            return row

    def record(self, action: str, evidence: str, agent_id: str, *, timestamp: int | None = None) -> HbpRow:
        payload = "hbp-fields/v1" + "".join(
            f":{len(field.encode('utf-8'))}:{field}" for field in (action, evidence, agent_id)
        )
        return self.append("agent-action", payload, f"agent:{agent_id}", timestamp=timestamp)

    def record_fields(
        self,
        topic: str,
        fields: Mapping[str, object],
        provenance: str,
        *,
        timestamp: int | None = None,
    ) -> HbpRow:
        """Append deterministic key/value fields without JSON serialization.

        The framing is deliberately simple and Runtime-compatible: the HBP
        row remains the integrity/container format while the payload declares
        ``hbp-fields/v1`` and carries length-delimited UTF-8 fields.  Values
        are supplied by the caller as already-canonical strings so this
        helper never smuggles a JSON object into an internal ledger.
        """
        encoded: list[str] = []
        for key in sorted(fields):
            value = fields[key]
            if not isinstance(key, str) or not key:
                raise HbpError("HBP field names must be non-empty strings")
            if isinstance(value, (dict, list, tuple, set)):
                raise HbpError("HBP fields must be scalar canonical values")
            encoded.append(f"{key}={value}")
        payload = "hbp-fields/v1" + "".join(f":{len(field.encode('utf-8'))}:{field}" for field in encoded)
        return self.append(topic, payload, provenance, timestamp=timestamp)

    def migrate_jsonl(
        self,
        source: str | Path,
        *,
        topic: str = "legacy-migration",
        provenance: str = "simplicio-dev-cli/legacy-json-migration",
    ) -> int:
        """Atomically migrate a legacy JSONL file into one HBP ledger.

        The JSON parser is isolated in :mod:`legacy_json_adapter`. The target
        is fully built and verified before it replaces the destination; the
        source is renamed only after the target is durable. If a process is
        interrupted after replacement but before the rename, the next call
        verifies the target and completes the source rename without replaying
        rows.
        """
        from .legacy_json_adapter import read_jsonl

        legacy = Path(source)
        migrated = legacy.with_name(legacy.name + ".migrated")
        if not legacy.is_file():
            return 0
        if self.path.exists():
            rows = self.verify()
            if not migrated.exists():
                os.replace(legacy, migrated)
            return len(rows)
        fields_rows = read_jsonl(legacy)
        self.directory.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{self.path.name}.", dir=str(self.directory)))
        try:
            temp_ledger = HbpEvidenceLedger(temp_dir, file_name=self.path.name)
            for fields in fields_rows:
                temp_ledger.record_fields(topic, fields, provenance)
            temp_ledger.verify()
            os.replace(temp_ledger.path, self.path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.replace(legacy, migrated)
        return len(fields_rows)


__all__ = ["HBP_FILE_NAME", "HBP_GENESIS", "HbpError", "HbpEvidenceLedger", "HbpRow", "row_content_hash"]
