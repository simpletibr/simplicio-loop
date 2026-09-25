"""Bounded HBP/HBI persistence adapter for the delivery-ledger events."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .ledger import DeliveryLedger, LedgerEvent


SCHEMA = "simplicio.fast.delivery-ledger-store/v1"
HBP_MAGIC = b"SFASTHBP1"
HBI_MAGIC = b"SFASTHBI1"
_FILE_HEADER = struct.Struct(">9sI")
_RECORD_HEADER = struct.Struct(">QI")
_INDEX_ENTRY = struct.Struct(">QQI32s")
MAX_RECORD_BYTES = 16 * 1024 * 1024


class LedgerStoreError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class LedgerStore:
    """Persist ledger records in an append-only body plus validated offset index."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hbp_path = self.root / "delivery.hbp"
        self.hbi_path = self.root / "delivery.hbi"
        self.lock_path = self.root / "delivery.hbp.lock"

    @contextmanager
    def _writer_lock(self) -> Iterator[None]:
        with self.lock_path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _payload(event: LedgerEvent) -> bytes:
        payload = json.dumps(
            event.record(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > MAX_RECORD_BYTES:
            raise LedgerStoreError(
                "record_too_large", "ledger record exceeds bounded store size"
            )
        return payload

    @staticmethod
    def _ensure_header(handle: Any, magic: bytes) -> int:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size == 0:
            handle.write(_FILE_HEADER.pack(magic, 1))
            return _FILE_HEADER.size
        handle.seek(0)
        header = handle.read(_FILE_HEADER.size)
        if len(header) != _FILE_HEADER.size or header != _FILE_HEADER.pack(magic, 1):
            raise LedgerStoreError("invalid_header", "ledger store header is invalid")
        return _FILE_HEADER.size

    def append(self, event: LedgerEvent) -> dict[str, Any]:
        payload = self._payload(event)
        digest = hashlib.sha256(payload).digest()
        with self._writer_lock():
            with self.hbp_path.open("a+b") as hbp, self.hbi_path.open("a+b") as hbi:
                self._ensure_header(hbp, HBP_MAGIC)
                hbi_header = self._ensure_header(hbi, HBI_MAGIC)
                hbi.seek(0, os.SEEK_END)
                index_size = hbi.tell() - hbi_header
                if index_size % _INDEX_ENTRY.size:
                    raise LedgerStoreError("partial_index", "HBI tail is partial")
                expected_sequence = index_size // _INDEX_ENTRY.size
                if event.sequence != expected_sequence:
                    raise LedgerStoreError(
                        "sequence_mismatch", "event sequence does not follow HBI"
                    )
                hbp.seek(0, os.SEEK_END)
                offset = hbp.tell()
                hbp.write(_RECORD_HEADER.pack(event.sequence, len(payload)))
                hbp.write(payload)
                hbp.flush()
                os.fsync(hbp.fileno())
                hbi.write(
                    _INDEX_ENTRY.pack(event.sequence, offset, len(payload), digest)
                )
                hbi.flush()
                os.fsync(hbi.fileno())
        return {
            "schema": SCHEMA,
            "sequence": event.sequence,
            "offset": offset + _RECORD_HEADER.size,
            "length": len(payload),
            "payload_sha256": digest.hex(),
        }

    def recover_tail(self) -> dict[str, Any]:
        """Recover only a crash-consistent HBP/HBI prefix and discard orphaned tails."""
        with self._writer_lock():
            try:
                hbp_data = self.hbp_path.read_bytes()
                hbi_data = self.hbi_path.read_bytes()
            except FileNotFoundError as error:
                raise LedgerStoreError(
                    "missing_store", "HBP and HBI are required for recovery"
                ) from error
            header_size = _FILE_HEADER.size
            if len(hbp_data) < header_size or hbp_data[
                :header_size
            ] != _FILE_HEADER.pack(HBP_MAGIC, 1):
                raise LedgerStoreError("invalid_header", "HBP header is invalid")
            if len(hbi_data) < header_size or hbi_data[
                :header_size
            ] != _FILE_HEADER.pack(HBI_MAGIC, 1):
                raise LedgerStoreError("invalid_header", "HBI header is invalid")
            index_body = hbi_data[header_size:]
            complete_index_bytes = len(index_body) - (
                len(index_body) % _INDEX_ENTRY.size
            )
            valid_events = 0
            valid_hbp_end = header_size
            recovery_reason: str | None = None
            for sequence in range(complete_index_bytes // _INDEX_ENTRY.size):
                start = header_size + sequence * _INDEX_ENTRY.size
                indexed_sequence, offset, length, _digest = _INDEX_ENTRY.unpack_from(
                    hbi_data, start
                )
                if (
                    indexed_sequence != sequence
                    or length > MAX_RECORD_BYTES
                    or offset != valid_hbp_end
                ):
                    raise LedgerStoreError(
                        "index_mismatch", "HBI prefix is not contiguous"
                    )
                try:
                    if (
                        offset < header_size
                        or offset + _RECORD_HEADER.size + length > len(hbp_data)
                    ):
                        raise LedgerStoreError(
                            "body_out_of_bounds", "HBI points outside HBP"
                        )
                    record_sequence, record_length = _RECORD_HEADER.unpack_from(
                        hbp_data, offset
                    )
                    payload_start = offset + _RECORD_HEADER.size
                    payload = hbp_data[payload_start : payload_start + record_length]
                    if (
                        record_sequence != sequence
                        or record_length != length
                        or hashlib.sha256(payload).digest() != _digest
                    ):
                        raise LedgerStoreError(
                            "payload_digest_mismatch", "HBP payload does not match HBI"
                        )
                    try:
                        record = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise LedgerStoreError(
                            "invalid_record", "HBP payload is not valid JSON"
                        ) from error
                    if not isinstance(record, dict):
                        raise LedgerStoreError(
                            "invalid_record", "HBP record must be an object"
                        )
                except LedgerStoreError as error:
                    if error.reason_code != "body_out_of_bounds":
                        raise
                    recovery_reason = error.reason_code
                    break
                valid_events += 1
                valid_hbp_end = offset + _RECORD_HEADER.size + length
            if complete_index_bytes < len(index_body) and recovery_reason is None:
                recovery_reason = "partial_index"
            target_hbi_size = header_size + valid_events * _INDEX_ENTRY.size
            target_hbp_size = valid_hbp_end
            truncated_hbi_bytes = len(hbi_data) - target_hbi_size
            truncated_hbp_bytes = max(0, len(hbp_data) - target_hbp_size)
            if truncated_hbi_bytes or truncated_hbp_bytes:
                with self.hbi_path.open("r+b") as hbi:
                    hbi.truncate(target_hbi_size)
                    hbi.flush()
                    os.fsync(hbi.fileno())
                with self.hbp_path.open("r+b") as hbp:
                    hbp.truncate(target_hbp_size)
                    hbp.flush()
                    os.fsync(hbp.fileno())
            if recovery_reason is None and truncated_hbp_bytes:
                recovery_reason = "orphan_hbp_tail"
            return {
                "schema": SCHEMA,
                "status": "recovered"
                if truncated_hbi_bytes or truncated_hbp_bytes
                else "valid",
                "events": valid_events,
                "truncated_hbp_bytes": truncated_hbp_bytes,
                "truncated_hbi_bytes": truncated_hbi_bytes,
                "reason_code": recovery_reason or "already_consistent",
            }

    def _index_entry(self, sequence: int) -> tuple[int, int, int, bytes]:
        if sequence < 0:
            raise LedgerStoreError("invalid_sequence", "sequence must be non-negative")
        try:
            raw = self.hbi_path.read_bytes()
        except FileNotFoundError as exc:
            raise LedgerStoreError("missing_index", "HBI index is missing") from exc
        header = _FILE_HEADER.pack(HBI_MAGIC, 1)
        if len(raw) < _FILE_HEADER.size or raw[: _FILE_HEADER.size] != header:
            raise LedgerStoreError("invalid_header", "HBI header is invalid")
        body = raw[_FILE_HEADER.size :]
        if len(body) % _INDEX_ENTRY.size:
            raise LedgerStoreError("partial_index", "HBI tail is partial")
        start = sequence * _INDEX_ENTRY.size
        end = start + _INDEX_ENTRY.size
        if end > len(body):
            raise LedgerStoreError("index_out_of_bounds", "sequence is not indexed")
        return _INDEX_ENTRY.unpack(body[start:end])

    def read_record(self, sequence: int) -> dict[str, Any]:
        indexed_sequence, offset, length, digest = self._index_entry(sequence)
        if indexed_sequence != sequence or length > MAX_RECORD_BYTES:
            raise LedgerStoreError(
                "index_mismatch", "HBI sequence or length is invalid"
            )
        try:
            data = self.hbp_path.read_bytes()
        except FileNotFoundError as exc:
            raise LedgerStoreError("missing_body", "HBP body is missing") from exc
        header_size = _FILE_HEADER.size
        if len(data) < header_size or data[:header_size] != _FILE_HEADER.pack(
            HBP_MAGIC, 1
        ):
            raise LedgerStoreError("invalid_header", "HBP header is invalid")
        if offset < header_size or offset + _RECORD_HEADER.size + length > len(data):
            raise LedgerStoreError("body_out_of_bounds", "HBI points outside HBP")
        record_sequence, record_length = _RECORD_HEADER.unpack_from(data, offset)
        payload_start = offset + _RECORD_HEADER.size
        payload = data[payload_start : payload_start + record_length]
        if (
            record_sequence != sequence
            or record_length != length
            or hashlib.sha256(payload).digest() != digest
        ):
            raise LedgerStoreError(
                "payload_digest_mismatch", "HBP payload does not match HBI"
            )
        try:
            record = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LedgerStoreError(
                "invalid_record", "HBP payload is not valid JSON"
            ) from exc
        if not isinstance(record, dict):
            raise LedgerStoreError("invalid_record", "HBP record must be an object")
        return record

    @staticmethod
    def _event_from_record(record: dict[str, Any]) -> LedgerEvent:
        try:
            return LedgerEvent(
                sequence=int(record["sequence"]),
                event_type=str(record["event_type"]),
                event_id=str(record["event_id"]),
                task_id=str(record["task_id"]),
                attempt_id=str(record["attempt_id"]),
                candidate_id=record["candidate_id"],
                repository=str(record["repository"]),
                source_commit=record["source_commit"],
                base_generation=record["base_generation"],
                overlay_generation=record["overlay_generation"],
                producer=str(record["producer"]),
                artifact_handles=tuple(record["artifact_handles"]),
                artifact_digests=tuple(record["artifact_digests"]),
                payload_digest=record["payload_digest"],
                prev_event_hash=str(record["prev_event_hash"]),
                event_hash=str(record["event_hash"]),
                metadata=dict(record["metadata"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LedgerStoreError(
                "invalid_record", "HBP event fields are invalid"
            ) from exc

    def verify(self) -> dict[str, Any]:
        try:
            hbi = self.hbi_path.read_bytes()
        except FileNotFoundError:
            return {
                "schema": SCHEMA,
                "status": "invalid",
                "reason_code": "missing_index",
                "events": 0,
            }
        header_size = _FILE_HEADER.size
        if len(hbi) < header_size or hbi[:header_size] != _FILE_HEADER.pack(
            HBI_MAGIC, 1
        ):
            return {
                "schema": SCHEMA,
                "status": "invalid",
                "reason_code": "invalid_header",
                "events": 0,
            }
        count = (len(hbi) - header_size) // _INDEX_ENTRY.size
        invalid: list[int] = []
        previous = "0" * 64
        repository: str | None = None
        for sequence in range(count):
            try:
                record = self.read_record(sequence)
                event = self._event_from_record(record)
                if repository is None:
                    repository = event.repository
                checker = DeliveryLedger(event.repository)
                valid = (
                    event.sequence == sequence
                    and event.prev_event_hash == previous
                    and event.event_hash == checker._event_hash(event.material())
                )
                if not valid:
                    invalid.append(sequence)
                previous = event.event_hash
            except LedgerStoreError:
                invalid.append(sequence)
                break
        return {
            "schema": SCHEMA,
            "status": "valid" if not invalid else "invalid",
            "events": count,
            "invalid_sequences": invalid,
            "head": previous,
            "repository": repository,
        }
