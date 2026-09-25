"""Bounded raw block streaming with checkpoint and atomic manifest publication."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "simplicio.fast.streaming-store/v1"
DEFAULT_BLOCK_BYTES = 1024 * 1024
MAX_BLOCK_BYTES = 16 * 1024 * 1024
MAX_RANGE_BYTES = 64 * 1024 * 1024
ATOMIC_REPLACE_ATTEMPTS = 4
ATOMIC_REPLACE_DELAY_SECONDS = 0.01


class StreamingStoreError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class StreamingBlockStore:
    """Write raw blocks without materializing the complete source in memory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_replace(temporary: Path, destination: Path) -> None:
        for attempt in range(ATOMIC_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, destination)
                return
            except PermissionError as error:
                if attempt + 1 >= ATOMIC_REPLACE_ATTEMPTS:
                    raise StreamingStoreError(
                        "atomic_replace_unavailable",
                        "destination remained locked after bounded retries",
                    ) from error
                time.sleep(ATOMIC_REPLACE_DELAY_SECONDS * (attempt + 1))

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        StreamingBlockStore._atomic_replace(temporary, path)

    @staticmethod
    def _blocks(chunks: Iterable[bytes], block_bytes: int) -> Iterable[bytes]:
        pending = bytearray()
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise StreamingStoreError(
                    "invalid_chunk", "stream chunks must be bytes"
                )
            pending.extend(chunk)
            while len(pending) >= block_bytes:
                yield bytes(pending[:block_bytes])
                del pending[:block_bytes]
        if pending:
            yield bytes(pending)

    def _load_checkpoint(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise StreamingStoreError(
                "invalid_checkpoint", "checkpoint is missing or malformed"
            ) from exc
        if value.get("schema") != SCHEMA or not isinstance(value.get("blocks"), list):
            raise StreamingStoreError(
                "invalid_checkpoint", "checkpoint schema is invalid"
            )
        return value

    def _validate_existing(self, work: Path, checkpoint: dict[str, Any]) -> None:
        segment = work / "segment-000000.bin"
        try:
            data = segment.read_bytes()
        except FileNotFoundError as exc:
            raise StreamingStoreError(
                "missing_segment", "checkpoint segment is missing"
            ) from exc
        cursor = 0
        for index, block in enumerate(checkpoint["blocks"]):
            if block.get("index") != index:
                raise StreamingStoreError(
                    "checkpoint_sequence", "checkpoint block sequence is invalid"
                )
            length = int(block["length"])
            if length < 1 or cursor + length > len(data):
                raise StreamingStoreError(
                    "checkpoint_bounds", "checkpoint block is outside segment"
                )
            payload = data[cursor : cursor + length]
            if hashlib.sha256(payload).hexdigest() != block.get("sha256"):
                raise StreamingStoreError(
                    "checkpoint_digest", "checkpoint block digest is invalid"
                )
            cursor += length
        if cursor != len(data):
            raise StreamingStoreError(
                "segment_tail", "segment has bytes outside checkpoint"
            )

    def build(
        self,
        chunks: Iterable[bytes],
        *,
        generation: str,
        block_bytes: int = DEFAULT_BLOCK_BYTES,
        resume: bool = False,
        fail_after_blocks: int | None = None,
    ) -> dict[str, Any]:
        if not generation or Path(generation).name != generation:
            raise StreamingStoreError(
                "invalid_generation", "generation must be a simple path component"
            )
        if not 1 <= block_bytes <= MAX_BLOCK_BYTES:
            raise StreamingStoreError(
                "invalid_block_size", "block size is outside supported bounds"
            )
        work = self.root / generation
        work.mkdir(parents=True, exist_ok=True)
        checkpoint_path = work / "checkpoint.json"
        if resume:
            checkpoint = self._load_checkpoint(checkpoint_path)
            if (
                checkpoint.get("generation") != generation
                or checkpoint.get("block_bytes") != block_bytes
            ):
                raise StreamingStoreError(
                    "checkpoint_mismatch", "checkpoint generation or block size differs"
                )
            self._validate_existing(work, checkpoint)
        else:
            checkpoint = {
                "schema": SCHEMA,
                "generation": generation,
                "block_bytes": block_bytes,
                "input_bytes": 0,
                "blocks": [],
            }
            self._atomic_json(checkpoint_path, checkpoint)
            (work / "segment-000000.bin").write_bytes(b"")
        existing = checkpoint["blocks"]
        segment_path = work / "segment-000000.bin"
        source_digest = hashlib.sha256()
        input_bytes = 0
        appended = 0
        with segment_path.open("ab") as segment:
            for index, payload in enumerate(self._blocks(chunks, block_bytes)):
                source_digest.update(payload)
                input_bytes += len(payload)
                if index < len(existing):
                    expected = existing[index]
                    if (
                        len(payload) != expected["length"]
                        or hashlib.sha256(payload).hexdigest() != expected["sha256"]
                    ):
                        raise StreamingStoreError(
                            "resume_source_mismatch", "source differs from checkpoint"
                        )
                    continue
                segment.write(payload)
                segment.flush()
                os.fsync(segment.fileno())
                entry = {
                    "index": index,
                    "length": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                checkpoint["blocks"].append(entry)
                checkpoint["input_bytes"] = input_bytes
                self._atomic_json(checkpoint_path, checkpoint)
                appended += 1
                if fail_after_blocks is not None and appended >= fail_after_blocks:
                    raise RuntimeError("injected_stream_failure")
        if len(existing) > input_bytes // block_bytes + (
            1 if input_bytes % block_bytes else 0
        ):
            raise StreamingStoreError(
                "checkpoint_ahead", "checkpoint has more blocks than source"
            )
        if input_bytes != sum(int(item["length"]) for item in checkpoint["blocks"]):
            raise StreamingStoreError(
                "checkpoint_length", "checkpoint byte count is inconsistent"
            )
        manifest = {
            "schema": SCHEMA,
            "generation": generation,
            "block_bytes": block_bytes,
            "input_bytes": input_bytes,
            "source_sha256": source_digest.hexdigest(),
            "blocks": checkpoint["blocks"],
            "segment": "segment-000000.bin",
        }
        self._atomic_json(work / "manifest.json", manifest)
        self._atomic_json(self.root / "current.json", manifest)
        checkpoint_path.unlink(missing_ok=True)
        return {**manifest, "status": "published", "appended_blocks": appended}

    def build_file(
        self,
        source: str | Path,
        *,
        generation: str,
        block_bytes: int = DEFAULT_BLOCK_BYTES,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Stream a file into bounded blocks without materializing it."""
        source_path = Path(source)
        try:
            handle = source_path.open("rb")
        except OSError as error:
            raise StreamingStoreError(
                "source_unavailable", "stream source is unavailable"
            ) from error
        with handle:
            chunks = iter(lambda: handle.read(block_bytes), b"")
            return self.build(
                chunks, generation=generation, block_bytes=block_bytes, resume=resume
            )

    def read_range(self, generation: str, start: int, length: int) -> bytes:
        if (
            isinstance(start, bool)
            or isinstance(length, bool)
            or not isinstance(start, int)
            or not isinstance(length, int)
            or start < 0
            or length < 0
            or length > MAX_RANGE_BYTES
        ):
            raise StreamingStoreError(
                "invalid_range",
                "range must be non-negative integers within the bounded limit",
            )
        work = self.root / generation
        try:
            manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise StreamingStoreError(
                "missing_manifest", "published generation is unavailable"
            ) from error
        if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
            raise StreamingStoreError(
                "invalid_manifest", "published manifest schema is invalid"
            )
        total = manifest.get("input_bytes")
        blocks = manifest.get("blocks")
        segment_name = manifest.get("segment")
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or not isinstance(blocks, list)
            or not isinstance(segment_name, str)
            or Path(segment_name).name != segment_name
            or start + length > total
        ):
            raise StreamingStoreError(
                "invalid_range", "range is outside the published generation"
            )
        if length == 0:
            return b""
        result = bytearray()
        cursor = 0
        try:
            with (work / segment_name).open("rb") as segment:
                for block in blocks:
                    if not isinstance(block, dict):
                        raise StreamingStoreError(
                            "invalid_manifest", "manifest block is invalid"
                        )
                    try:
                        block_length = int(block["length"])
                    except (KeyError, TypeError, ValueError) as error:
                        raise StreamingStoreError(
                            "invalid_manifest", "manifest block length is invalid"
                        ) from error
                    block_end = cursor + block_length
                    if block_length < 1 or block_end > total:
                        raise StreamingStoreError(
                            "invalid_manifest", "manifest block bounds are invalid"
                        )
                    if cursor < start + length and block_end > start:
                        segment.seek(cursor)
                        payload = segment.read(block_length)
                        if len(payload) != block_length:
                            raise StreamingStoreError(
                                "segment_bounds", "segment block is truncated"
                            )
                        if hashlib.sha256(payload).hexdigest() != block.get("sha256"):
                            raise StreamingStoreError(
                                "block_digest", "stream block digest is invalid"
                            )
                        left = max(start, cursor) - cursor
                        right = min(start + length, block_end) - cursor
                        result.extend(payload[left:right])
                    cursor = block_end
                    if cursor >= start + length:
                        break
        except FileNotFoundError as error:
            raise StreamingStoreError(
                "missing_segment", "published segment is unavailable"
            ) from error
        if cursor < start + length or len(result) != length:
            raise StreamingStoreError(
                "segment_bounds", "range is outside the published segment"
            )
        return bytes(result)

    def read_all(self, generation: str) -> bytes:
        work = self.root / generation
        try:
            manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
            data = (work / manifest["segment"]).read_bytes()
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            raise StreamingStoreError(
                "missing_manifest", "published generation is unavailable"
            ) from exc
        if (
            len(data) != manifest["input_bytes"]
            or hashlib.sha256(data).hexdigest() != manifest["source_sha256"]
        ):
            raise StreamingStoreError(
                "manifest_digest", "published generation digest is invalid"
            )
        return data
