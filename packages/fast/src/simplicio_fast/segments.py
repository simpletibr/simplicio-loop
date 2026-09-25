"""Atomic immutable section storage derived from a validated SFAST snapshot."""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import threading
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from .snapshot import Snapshot
from .pager import PageKey, SemanticPager


MANIFEST_SCHEMA = "simplicio.fast.segments/v1"
MANIFEST_NAME = "manifest.json"
MANIFEST_BACKUP_NAME = "manifest.previous.json"


class SemanticSegmentPagerError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class SemanticSegmentPager:
    """Read bounded semantic windows from validated immutable segments."""

    def __init__(
        self,
        store: SegmentStore,
        repository: str,
        generation: str,
        *,
        overlay: str | None = None,
        page_bytes: int = 64 * 1024,
        max_bytes: int = 4 * 1024 * 1024,
        max_pages: int = 256,
    ) -> None:
        if not repository or not generation or page_bytes < 1:
            raise ValueError("repository, generation and page_bytes are required")
        self.store = store
        self.repository = repository
        self.generation = generation
        self.overlay = overlay
        self.page_bytes = page_bytes
        self._pager = SemanticPager(
            repository, generation, max_bytes=max_bytes, max_pages=max_pages
        )
        self._lock = threading.Lock()
        self._segment_reads = 0

    def read(self, name: str, offset: int, size: int) -> bytes:
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or offset < 0
            or size < 1
        ):
            raise SemanticSegmentPagerError(
                "segment_range_invalid", "offset and size must be positive integers"
            )
        manifest = self.store.read_manifest()
        if manifest.get("generation") != self.generation:
            raise SemanticSegmentPagerError(
                "stale_generation", "pager generation differs from segment manifest"
            )
        entry = next(
            (item for item in manifest["segments"] if item.get("name") == name), None
        )
        if entry is None:
            raise SemanticSegmentPagerError(
                "segment_not_found", f"segment not found: {name}"
            )
        segment_bytes = entry["bytes"]
        if offset + size > segment_bytes:
            raise SemanticSegmentPagerError(
                "segment_range_out_of_bounds", "requested range exceeds segment"
            )
        first = (offset // self.page_bytes) * self.page_bytes
        last = ((offset + size - 1) // self.page_bytes) * self.page_bytes
        chunks: list[bytes] = []
        for page_start in range(first, last + 1, self.page_bytes):
            page_size = min(self.page_bytes, segment_bytes - page_start)
            key = PageKey(
                self.repository,
                self.generation,
                self.overlay,
                name,
                f"{page_start}:{page_size}",
            )
            page = self._pager.get(
                key,
                lambda page_start=page_start, page_size=page_size: (
                    self.store.read_range(name, page_start, page_size)
                ),
            )
            begin = max(offset - page_start, 0)
            end = min(offset + size - page_start, page_size)
            chunks.append(page[begin:end])
        with self._lock:
            self._segment_reads += 1
        return b"".join(chunks)

    def stats(self) -> dict[str, object]:
        with self._lock:
            segment_reads = self._segment_reads
        return {
            "schema": "simplicio.fast.semantic-segment-pager/v1",
            "repository": self.repository,
            "generation": self.generation,
            "overlay": self.overlay,
            "page_bytes": self.page_bytes,
            "segment_reads": segment_reads,
            **self._pager.stats(),
        }


class SegmentStoreError(ValueError):
    """A segmented cache is missing, corrupt, or incompatible."""


@dataclass(frozen=True, slots=True)
class Segment:
    name: str
    file: str
    bytes: int
    sha256: str


class SegmentStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.manifest_path = self.directory / MANIFEST_NAME
        self.previous_manifest_path = self.directory / MANIFEST_BACKUP_NAME

    def publish(self, snapshot_path: Path) -> dict[str, Any]:
        """Publish all sections, then atomically swap the manifest pointer."""

        snapshot_path = snapshot_path.resolve()
        with Snapshot(snapshot_path) as snapshot:
            source_digest = snapshot.sha256
            segments: list[Segment] = []
            written = 0
            reused = 0
            staging = Path(
                tempfile.mkdtemp(
                    prefix=".segments-",
                    dir=self.directory.parent
                    if self.directory.parent.exists()
                    else None,
                )
            )
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                # Move staging under the destination parent only; files are
                # content-addressed, so old manifests remain readable while a
                # new generation is being prepared.
                if staging.parent != self.directory:
                    destination_staging = self.directory / staging.name
                    shutil.move(str(staging), str(destination_staging))
                    staging = destination_staging
                for name in sorted(snapshot._sections):
                    data = snapshot._section_bytes(name)
                    digest = hashlib.sha256(data).hexdigest()
                    filename = f"{name}-{digest}.seg"
                    temporary = staging / filename
                    temporary.write_bytes(data)
                    with temporary.open("r+b") as handle:
                        handle.flush()
                        os.fsync(handle.fileno())
                    final = self.directory / filename
                    if final.exists():
                        try:
                            existing_size = final.stat().st_size
                            existing_digest = hashlib.sha256(
                                final.read_bytes()
                            ).hexdigest()
                        except OSError as error:
                            raise SegmentStoreError(
                                f"segment_existing_unreadable:{name}"
                            ) from error
                        if existing_size != len(data) or existing_digest != digest:
                            raise SegmentStoreError(
                                f"segment_existing_checksum_mismatch:{name}"
                            )
                        reused += 1
                    else:
                        os.replace(temporary, final)
                        written += 1
                    segments.append(Segment(name, filename, len(data), digest))
                payload = {
                    "schema": MANIFEST_SCHEMA,
                    "generation": snapshot.generation,
                    "source_snapshot_sha256": source_digest,
                    "segments": [
                        segment.__dict__
                        if hasattr(segment, "__dict__")
                        else {
                            "name": segment.name,
                            "file": segment.file,
                            "bytes": segment.bytes,
                            "sha256": segment.sha256,
                        }
                        for segment in segments
                    ],
                    "segments_written": written,
                    "segments_reused": reused,
                }
                self.directory.mkdir(parents=True, exist_ok=True)
                manifest_tmp = self.directory / f".{MANIFEST_NAME}.{os.getpid()}.tmp"
                manifest_tmp.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with manifest_tmp.open("r+b") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
                if self.manifest_path.exists():
                    backup_tmp = (
                        self.directory / f".{MANIFEST_BACKUP_NAME}.{os.getpid()}.tmp"
                    )
                    shutil.copyfile(self.manifest_path, backup_tmp)
                    with backup_tmp.open("r+b") as handle:
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(backup_tmp, self.previous_manifest_path)
                os.replace(manifest_tmp, self.manifest_path)
                return payload
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def _read_manifest_file(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SegmentStoreError(f"manifest_unreadable:{error}") from error
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != MANIFEST_SCHEMA
            or not isinstance(payload.get("segments"), list)
        ):
            raise SegmentStoreError("manifest_schema_mismatch")
        generation = payload.get("generation")
        source_digest = payload.get("source_snapshot_sha256")
        if (
            not isinstance(generation, str)
            or not generation
            or not isinstance(source_digest, str)
            or len(source_digest) != 64
            or any(char not in "0123456789abcdef" for char in source_digest.lower())
        ):
            raise SegmentStoreError("manifest_metadata_invalid")
        segments = payload["segments"]
        if not segments:
            raise SegmentStoreError("manifest_segments_invalid")
        names = [
            item.get("name") if isinstance(item, dict) else None for item in segments
        ]
        if any(not isinstance(name, str) or not name for name in names) or len(
            set(names)
        ) != len(names):
            raise SegmentStoreError("manifest_segments_invalid")
        return payload

    def read_manifest(self) -> dict[str, Any]:
        return self._read_manifest_file(self.manifest_path)

    def recover_previous(self) -> dict[str, Any]:
        """Restore the last verified manifest after an interrupted pointer swap."""
        payload = self._read_manifest_file(self.previous_manifest_path)
        for item in payload["segments"]:
            self._validate_entry(item)
        manifest_tmp = self.directory / f".{MANIFEST_NAME}.{os.getpid()}.recovery.tmp"
        manifest_tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with manifest_tmp.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(manifest_tmp, self.manifest_path)
        return payload

    def validate(self) -> dict[str, Any]:
        payload = self.read_manifest()
        checked = 0
        for item in payload["segments"]:
            self._validate_entry(item)
            checked += 1
        return {
            "schema": "simplicio.fast.segments-validation/v1",
            "status": "valid",
            "segments": checked,
            "generation": payload["generation"],
        }

    def read(self, name: str) -> bytes:
        with self.map(name) as mapped:
            return bytes(mapped)

    def read_range(self, name: str, offset: int, size: int) -> bytes:
        """Read one bounded range without materializing the whole segment."""
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or offset < 0
            or size < 1
        ):
            raise SegmentStoreError("segment_range_invalid")
        with self.map(name) as mapped:
            if offset + size > len(mapped):
                raise SegmentStoreError("segment_range_out_of_bounds")
            return bytes(mapped[offset : offset + size])

    @contextmanager
    def map(self, name: str) -> Iterator[mmap.mmap | bytes]:
        """Validate and map one segment, loading only its requested bytes."""

        payload = self.read_manifest()
        item = next(
            (entry for entry in payload["segments"] if entry.get("name") == name), None
        )
        if item is None:
            raise SegmentStoreError(f"segment_not_found:{name}")
        self._validate_entry(item)
        path = self.directory / item["file"]
        if item["bytes"] == 0:
            yield b""
            return
        with path.open("rb") as handle:
            mapped = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                yield mapped
            finally:
                mapped.close()

    def _validate_entry(self, item: Any) -> None:
        if not isinstance(item, dict) or not all(
            key in item for key in ("name", "file", "bytes", "sha256")
        ):
            raise SegmentStoreError("segment_entry_invalid")
        if (
            isinstance(item["bytes"], bool)
            or not isinstance(item["bytes"], int)
            or item["bytes"] < 0
            or not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in item["sha256"].lower())
        ):
            raise SegmentStoreError("segment_entry_invalid")
        if not isinstance(item["file"], str) or Path(item["file"]).name != item["file"]:
            raise SegmentStoreError("segment_path_invalid")
        path = self.directory / item["file"]
        try:
            size = path.stat().st_size
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise SegmentStoreError(f"segment_missing:{item['name']}") from error
        if size != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise SegmentStoreError(f"segment_checksum_mismatch:{item['name']}")


def migrate_snapshot(snapshot_path: Path, directory: Path) -> dict[str, Any]:
    """Idempotent monolith-to-segments migration entry point."""

    return SegmentStore(directory).publish(snapshot_path)
