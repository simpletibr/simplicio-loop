"""Versioned bounded frames for a future Fast IPC transport."""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
from dataclasses import dataclass

SCHEMA = "simplicio.fast.ipc/v1"
MAGIC = b"SFASTIPC"
HEADER = struct.Struct(">8sII")
MAX_HEADER_BYTES = 4 * 1024
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_FRAME_BYTES = HEADER.size + MAX_HEADER_BYTES + MAX_PAYLOAD_BYTES
_METADATA_KEYS = {"schema", "request_id", "operation", "generation", "payload_sha256"}


class IpcFrameError(ValueError):
    """A frame crossed the boundary with a stable fail-closed reason."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _positive_limits(
    max_header_bytes: int, max_payload_bytes: int, max_frame_bytes: int
) -> None:
    if any(
        not isinstance(value, int) or value < 1
        for value in (max_header_bytes, max_payload_bytes, max_frame_bytes)
    ):
        raise ValueError("frame limits must be positive integers")


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit:
        raise IpcFrameError(
            "invalid_metadata", f"{field} must be non-empty and <= {limit} bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class IpcFrame:
    request_id: str
    operation: str
    generation: str
    payload: bytes

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", 128)
        _text(self.operation, "operation", 128)
        _text(self.generation, "generation", 128)
        if not isinstance(self.payload, bytes):
            raise IpcFrameError("invalid_payload", "payload must be bytes")

    def encode(
        self,
        *,
        max_header_bytes: int = MAX_HEADER_BYTES,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
        max_frame_bytes: int = MAX_FRAME_BYTES,
    ) -> bytes:
        _positive_limits(max_header_bytes, max_payload_bytes, max_frame_bytes)
        if len(self.payload) > max_payload_bytes:
            raise IpcFrameError("payload_too_large", "payload exceeds configured bound")
        metadata = {
            "generation": self.generation,
            "operation": self.operation,
            "payload_sha256": hashlib.sha256(self.payload).hexdigest(),
            "request_id": self.request_id,
            "schema": SCHEMA,
        }
        header = json.dumps(
            metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if len(header) > max_header_bytes:
            raise IpcFrameError("header_too_large", "metadata exceeds configured bound")
        total = HEADER.size + len(header) + len(self.payload)
        if total > max_frame_bytes:
            raise IpcFrameError("frame_too_large", "frame exceeds configured bound")
        return (
            HEADER.pack(MAGIC, len(header), len(self.payload)) + header + self.payload
        )


def decode_frame(
    data: bytes,
    *,
    max_header_bytes: int = MAX_HEADER_BYTES,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> IpcFrame:
    _positive_limits(max_header_bytes, max_payload_bytes, max_frame_bytes)
    if not isinstance(data, bytes):
        raise IpcFrameError("invalid_frame", "frame must be bytes")
    if len(data) > max_frame_bytes:
        raise IpcFrameError("frame_too_large", "frame exceeds configured bound")
    if len(data) < HEADER.size:
        raise IpcFrameError("truncated_frame", "frame header is incomplete")
    magic, header_length, payload_length = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise IpcFrameError("invalid_magic", "frame magic is not supported")
    if header_length > max_header_bytes:
        raise IpcFrameError("header_too_large", "metadata exceeds configured bound")
    if payload_length > max_payload_bytes:
        raise IpcFrameError("payload_too_large", "payload exceeds configured bound")
    expected = HEADER.size + header_length + payload_length
    if len(data) < expected:
        raise IpcFrameError("truncated_frame", "frame body is incomplete")
    if len(data) > expected:
        raise IpcFrameError("trailing_bytes", "frame contains trailing bytes")
    try:
        metadata = json.loads(
            data[HEADER.size : HEADER.size + header_length].decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IpcFrameError(
            "invalid_header", "frame metadata is not valid UTF-8 JSON"
        ) from error
    if not isinstance(metadata, dict) or set(metadata) != _METADATA_KEYS:
        raise IpcFrameError("invalid_metadata", "frame metadata keys are invalid")
    if metadata.get("schema") != SCHEMA:
        raise IpcFrameError("unsupported_schema", "frame schema is not supported")
    payload_start = HEADER.size + header_length
    payload = data[payload_start:expected]
    digest = metadata.get("payload_sha256")
    if not isinstance(digest, str) or not hmac.compare_digest(
        digest, hashlib.sha256(payload).hexdigest()
    ):
        raise IpcFrameError("payload_digest_mismatch", "payload digest does not match")
    return IpcFrame(
        request_id=_text(metadata.get("request_id"), "request_id", 128),
        operation=_text(metadata.get("operation"), "operation", 128),
        generation=_text(metadata.get("generation"), "generation", 128),
        payload=payload,
    )


class IpcFrameDecoder:
    """Incrementally decode bounded frames from a stream transport."""

    def __init__(
        self,
        *,
        max_header_bytes: int = MAX_HEADER_BYTES,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
        max_frame_bytes: int = MAX_FRAME_BYTES,
    ) -> None:
        _positive_limits(max_header_bytes, max_payload_bytes, max_frame_bytes)
        self.max_header_bytes = max_header_bytes
        self.max_payload_bytes = max_payload_bytes
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> tuple[IpcFrame, ...]:
        if not isinstance(data, bytes):
            raise IpcFrameError("invalid_frame", "frame chunk must be bytes")
        self._buffer.extend(data)
        frames: list[IpcFrame] = []
        while len(self._buffer) >= HEADER.size:
            magic, header_length, payload_length = HEADER.unpack_from(self._buffer)
            if magic != MAGIC:
                raise IpcFrameError("invalid_magic", "frame magic is not supported")
            if header_length > self.max_header_bytes:
                raise IpcFrameError(
                    "header_too_large", "metadata exceeds configured bound"
                )
            if payload_length > self.max_payload_bytes:
                raise IpcFrameError(
                    "payload_too_large", "payload exceeds configured bound"
                )
            expected = HEADER.size + header_length + payload_length
            if expected > self.max_frame_bytes:
                raise IpcFrameError("frame_too_large", "frame exceeds configured bound")
            if len(self._buffer) < expected:
                break
            encoded = bytes(self._buffer[:expected])
            del self._buffer[:expected]
            frames.append(
                decode_frame(
                    encoded,
                    max_header_bytes=self.max_header_bytes,
                    max_payload_bytes=self.max_payload_bytes,
                    max_frame_bytes=self.max_frame_bytes,
                )
            )
        return tuple(frames)

    def finish(self) -> None:
        if self._buffer:
            raise IpcFrameError(
                "truncated_frame", "stream ended with an incomplete frame"
            )


__all__ = [
    "IpcFrame",
    "IpcFrameDecoder",
    "IpcFrameError",
    "MAGIC",
    "MAX_FRAME_BYTES",
    "MAX_HEADER_BYTES",
    "MAX_PAYLOAD_BYTES",
    "SCHEMA",
    "decode_frame",
]
