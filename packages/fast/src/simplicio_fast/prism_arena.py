"""Resident PRISM arena backed by one immutable mmap and isolated task overlays."""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import shutil
import struct
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import resource  # Unix peak RSS; absent on Windows
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

from .hbp_codec import GENESIS, seal_receipt, verify_chain


def _peak_rss_kib() -> int:
    """Best-effort peak RSS in KiB. Never raises; returns 0 if unobservable."""
    if resource is not None:
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            get_mem = ctypes.windll.psapi.GetProcessMemoryInfo
            get_mem.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            get_mem.restype = wintypes.BOOL
            if get_mem(handle, ctypes.byref(counters), counters.cb):
                return max(1, int(counters.PeakWorkingSetSize // 1024))
        except Exception:
            return 0
    return 0


ARENA_SCHEMA = "simplicio.fast.prism-arena/v1"
SLOT_SCHEMA = "simplicio.fast.prism-slot/v1"
OVERLAY_SCHEMA = "simplicio.fast.prism-overlay/v1"
LEASE_SCHEMA = "simplicio.fast.prism-lease/v1"
RECEIPT_SCHEMA = "simplicio.fast.prism-arena-receipt/v1"
METRICS_SCHEMA = "simplicio.fast.prism-arena-metrics/v1"
BENCHMARK_SCHEMA = "simplicio.fast.prism-arena-benchmark/v1"
MAGIC = b"PRISMA1\0"
HEADER = struct.Struct(">8sI")
RECORD = struct.Struct(">HQ")
MAX_OVERLAYS_PER_SLOT = 10


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _digest(value: Any) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_component(value: str, name: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ArenaError("identity_invalid", f"{name} must be one safe path component")
    return value


def _safe_path(value: str) -> str:
    path = Path(value)
    # Windows does not treat "/escape" as absolute; reject rooted paths explicitly.
    if (
        not value
        or value.startswith(("/", "\\"))
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ArenaError("overlay_escape", value)
    return value


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
        try:
            directory = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory = None
        if directory is not None:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def encode_base(files: Mapping[str, bytes]) -> bytes:
    """Encode path/content records without JSON so the result can be mmapped."""
    records: list[tuple[bytes, bytes]] = []
    for path, content in sorted(files.items()):
        _safe_path(path)
        if not isinstance(content, bytes):
            raise ArenaError("base_content_invalid", path)
        encoded_path = path.encode("utf-8")
        if len(encoded_path) > 65535:
            raise ArenaError("base_path_too_long", path)
        records.append((encoded_path, content))
    output = bytearray(HEADER.pack(MAGIC, len(records)))
    for path, content in records:
        output.extend(RECORD.pack(len(path), len(content)))
        output.extend(path)
        output.extend(hashlib.sha256(content).digest())
        output.extend(content)
    return bytes(output)


class ArenaError(RuntimeError):
    """Fail-closed arena error with a machine-readable source-scan fallback."""

    def __init__(
        self, reason_code: str, detail: str = "", *, fallback: str = "source_scan"
    ) -> None:
        self.reason_code = reason_code
        self.detail = detail
        self.fallback = fallback
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "status": "fallback",
            "reason_code": self.reason_code,
            "detail": self.detail,
            "fallback": self.fallback,
        }


@dataclass(frozen=True, slots=True)
class PrismWorkDelta:
    writes: Mapping[str, bytes] = field(default_factory=dict)
    deletes: tuple[str, ...] = ()
    renames: Mapping[str, str] = field(default_factory=dict)
    dirty_spans: Mapping[str, tuple[tuple[int, int], ...]] = field(default_factory=dict)


@dataclass(slots=True)
class GenerationLease:
    schema: str
    lease_id: str
    generation: str
    owner: str
    fence: str
    expires_at: float
    active: bool = True


@dataclass(frozen=True, slots=True)
class SlotView:
    schema: str
    arena_id: str
    generation: str
    base_handle_id: str
    slot_id: str
    prism_id: str
    lease_id: str
    fence: str
    parent_slot_id: str | None
    max_overlay_bytes: int
    max_overlay_files: int


@dataclass(slots=True)
class TaskOverlay:
    schema: str
    overlay_id: str
    arena_id: str
    generation: str
    base_handle_id: str
    slot_id: str
    task_id: str
    attempt: int
    worktree_id: str
    fence: str
    max_bytes: int
    max_files: int
    path: Path
    records: dict[str, str | None] = field(default_factory=dict)
    dirty_spans: dict[str, tuple[tuple[int, int], ...]] = field(default_factory=dict)
    overlay_generation: str = GENESIS
    active: bool = True
    abandoned_at: float | None = None


@dataclass(frozen=True, slots=True)
class ArenaReceipt:
    schema: str
    action: str
    arena_id: str
    generation: str
    base_hash: str
    base_handle_id: str
    slot_id: str | None
    overlay_id: str | None
    detail_hash: str
    previous_event_hash: str
    event_hash: str
    hbp_row: str

    def export(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "action": self.action,
            "arena_id": self.arena_id,
            "generation": self.generation,
            "base_hash": self.base_hash,
            "base_handle_id": self.base_handle_id,
            "slot_id": self.slot_id,
            "overlay_id": self.overlay_id,
            "detail_hash": self.detail_hash,
            "previous_event_hash": self.previous_event_hash,
            "event_hash": self.event_hash,
        }


@dataclass(slots=True)
class _BaseHandle:
    path: Path
    stream: Any
    mapping: mmap.mmap
    generation: str
    source_hash: str
    handle_id: str
    catalog: dict[str, tuple[int, int, str]]
    refcount: int = 1
    reuse_count: int = 0


_REGISTRY_LOCK = threading.RLock()
_HANDLE_REGISTRY: dict[tuple[str, str], _BaseHandle] = {}


def _decode_catalog(mapping: mmap.mmap) -> dict[str, tuple[int, int, str]]:
    if len(mapping) < HEADER.size:
        raise ArenaError("snapshot_truncated", "header")
    magic, count = HEADER.unpack(mapping[: HEADER.size])
    if magic != MAGIC:
        raise ArenaError("snapshot_corrupt", "magic")
    offset = HEADER.size
    catalog: dict[str, tuple[int, int, str]] = {}
    for _ in range(count):
        if offset + RECORD.size > len(mapping):
            raise ArenaError("snapshot_truncated", "record header")
        path_length, content_length = RECORD.unpack(
            mapping[offset : offset + RECORD.size]
        )
        offset += RECORD.size
        end_path = offset + path_length
        end_hash = end_path + 32
        end_content = end_hash + content_length
        if end_content > len(mapping):
            raise ArenaError("snapshot_truncated", "record body")
        try:
            path = bytes(mapping[offset:end_path]).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ArenaError("snapshot_corrupt", "path encoding") from error
        _safe_path(path)
        if path in catalog:
            raise ArenaError("snapshot_corrupt", f"duplicate path {path}")
        expected = bytes(mapping[end_path:end_hash]).hex()
        actual = hashlib.sha256(mapping[end_hash:end_content]).hexdigest()
        if actual != expected:
            raise ArenaError("snapshot_corrupt", path)
        catalog[path] = (end_hash, content_length, expected)
        offset = end_content
    if offset != len(mapping):
        raise ArenaError("snapshot_corrupt", "trailing bytes")
    return catalog


def _metadata_fields(row: str) -> dict[str, str]:
    verify_chain([row])
    body = row.rsplit("|event_hash=", 1)[0]
    fields: dict[str, str] = {}
    for part in body.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    return fields


class PrismArena:
    """Data-plane owner for one immutable generation and its isolated overlays."""

    def __init__(
        self,
        storage: str | Path,
        repo: str,
        generation: str,
        *,
        expected_source_hash: str | None = None,
    ) -> None:
        self.storage = Path(storage).resolve()
        self.repo = repo
        self.generation = generation
        self.generation_dir = self.storage / "generations" / generation
        self.base_path = self.generation_dir / "base.sfa"
        metadata_path = self.generation_dir / "metadata.hbp"
        try:
            row = metadata_path.read_text(encoding="utf-8").strip()
            fields = _metadata_fields(row)
        except (OSError, ValueError) as error:
            raise ArenaError("snapshot_metadata_corrupt", str(error)) from error
        if fields.get("generation") != generation:
            raise ArenaError("snapshot_corrupt", "generation metadata mismatch")
        self.source_hash = fields.get("source_hash", "")
        if (
            expected_source_hash is not None
            and self.source_hash != expected_source_hash
        ):
            raise ArenaError("source_stale", "source hash differs")
        try:
            base_hash = _digest(self.base_path.read_bytes())
        except OSError as error:
            raise ArenaError("snapshot_missing", str(error)) from error
        if fields.get("base_hash") != base_hash:
            raise ArenaError("snapshot_corrupt", "base digest")
        self.base_hash = base_hash
        self._handle = self._acquire_handle()
        self.arena_id = _digest(
            {"repo": repo, "generation": generation, "handle": self._handle.handle_id}
        )
        self._lock = threading.RLock()
        self._slots: dict[str, SlotView] = {}
        self._leases: dict[str, GenerationLease] = {}
        self._overlays: dict[str, TaskOverlay] = {}
        self._children: dict[str, set[str]] = {}
        self._closed = False
        self._draining = False
        self._receipts: list[ArenaReceipt] = []
        self._metrics: dict[str, int] = {
            "base_reads": 0,
            "base_pages": 0,
            "base_bytes": 0,
            "overlay_reads": 0,
            "overlay_writes": 0,
            "overlay_bytes_written": 0,
            "misses": 0,
        }
        self._receipt_path = (
            self.storage
            / "receipts"
            / f"{self.arena_id}-{os.getpid()}-{uuid.uuid4().hex}.hbp"
        )
        self._record("open", detail={"source_hash": self.source_hash})

    @classmethod
    def publish(
        cls,
        storage: str | Path,
        repo: str,
        source_hash: str,
        files: Mapping[str, bytes],
    ) -> "PrismArena":
        blob = encode_base(files)
        base_hash = _digest(blob)
        generation = _digest(
            {
                "schema": ARENA_SCHEMA,
                "repo": repo,
                "source_hash": source_hash,
                "base_hash": base_hash,
            }
        )
        root = Path(storage).resolve()
        directory = root / "generations" / generation
        base_path = directory / "base.sfa"
        metadata_path = directory / "metadata.hbp"
        if base_path.exists():
            if _digest(base_path.read_bytes()) != base_hash:
                raise ArenaError("snapshot_corrupt", generation)
        else:
            _atomic_bytes(base_path, blob)
        metadata_body = (
            f"schema={ARENA_SCHEMA}|action=publish|repo_hash={_digest(repo)}"
            f"|generation={generation}|source_hash={source_hash}|base_hash={base_hash}"
            f"|size={len(blob)}"
        )
        metadata = seal_receipt(metadata_body)
        if metadata_path.exists():
            existing = metadata_path.read_text(encoding="utf-8").strip()
            if existing != metadata:
                raise ArenaError("generation_collision", generation)
        else:
            _atomic_bytes(metadata_path, (metadata + "\n").encode())
        current = seal_receipt(
            f"schema={ARENA_SCHEMA}|action=current|repo_hash={_digest(repo)}"
            f"|generation={generation}|source_hash={source_hash}"
        )
        _atomic_bytes(root / "current.hbp", (current + "\n").encode())
        return cls(root, repo, generation, expected_source_hash=source_hash)

    @classmethod
    def open_current(
        cls, storage: str | Path, repo: str, *, expected_source_hash: str | None = None
    ) -> "PrismArena":
        try:
            row = (
                (Path(storage).resolve() / "current.hbp")
                .read_text(encoding="utf-8")
                .strip()
            )
            fields = _metadata_fields(row)
            generation = fields["generation"]
        except (OSError, KeyError, ValueError) as error:
            raise ArenaError("current_generation_corrupt", str(error)) from error
        return cls(storage, repo, generation, expected_source_hash=expected_source_hash)

    def _acquire_handle(self) -> _BaseHandle:
        key = (str(self.base_path), self.generation)
        with _REGISTRY_LOCK:
            existing = _HANDLE_REGISTRY.get(key)
            if existing is not None:
                existing.refcount += 1
                existing.reuse_count += 1
                return existing
            try:
                stream = self.base_path.open("rb")
                mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
                stat = self.base_path.stat()
                handle_id = _digest(
                    {
                        "generation": self.generation,
                        "device": stat.st_dev,
                        "inode": stat.st_ino,
                    }
                )
                catalog = _decode_catalog(mapping)
            except ArenaError:
                if "mapping" in locals():
                    mapping.close()
                if "stream" in locals():
                    stream.close()
                raise
            except (OSError, ValueError) as error:
                if "stream" in locals():
                    stream.close()
                raise ArenaError("snapshot_corrupt", str(error)) from error
            handle = _BaseHandle(
                self.base_path,
                stream,
                mapping,
                self.generation,
                self.source_hash,
                handle_id,
                catalog,
            )
            _HANDLE_REGISTRY[key] = handle
            return handle

    @property
    def base_handle_id(self) -> str:
        return self._handle.handle_id

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArenaError("arena_closed")

    def _record(
        self,
        action: str,
        *,
        slot_id: str | None = None,
        overlay_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> ArenaReceipt:
        detail_hash = _digest(dict(detail or {}))
        previous = self._receipts[-1].event_hash if self._receipts else GENESIS
        body = (
            f"schema={RECEIPT_SCHEMA}|action={action}|arena_id={self.arena_id}"
            f"|generation={self.generation}|base_hash={self.base_hash}"
            f"|base_handle_id={self.base_handle_id}|slot_id={slot_id or '-'}"
            f"|overlay_id={overlay_id or '-'}|detail_hash={detail_hash}"
        )
        row = seal_receipt(body, previous)
        event_hash = row.rsplit("|event_hash=", 1)[1]
        receipt = ArenaReceipt(
            RECEIPT_SCHEMA,
            action,
            self.arena_id,
            self.generation,
            self.base_hash,
            self.base_handle_id,
            slot_id,
            overlay_id,
            detail_hash,
            previous,
            event_hash,
            row,
        )
        self._receipt_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._receipt_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, (row + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._receipts.append(receipt)
        return receipt

    def receipts(self) -> tuple[ArenaReceipt, ...]:
        rows = [receipt.hbp_row for receipt in self._receipts]
        verify_chain(rows)
        return tuple(self._receipts)

    def export_receipts(self) -> list[dict[str, Any]]:
        return [receipt.export() for receipt in self.receipts()]

    def open_slot(
        self,
        slot_id: str,
        prism_id: str,
        *,
        fence: str,
        ttl_seconds: float = 3600,
        parent: SlotView | None = None,
        max_overlay_bytes: int = 8 * 1024 * 1024,
        max_overlay_files: int = 512,
    ) -> SlotView:
        self._ensure_open()
        _safe_component(slot_id, "slot_id")
        _safe_component(prism_id, "prism_id")
        if (
            not fence
            or ttl_seconds <= 0
            or max_overlay_bytes <= 0
            or max_overlay_files <= 0
        ):
            raise ArenaError("slot_limits_invalid", slot_id)
        if parent is not None:
            self._validate_slot(parent)
        with self._lock:
            existing = self._slots.get(slot_id)
            if existing is not None:
                if existing.fence != fence:
                    raise ArenaError("fence_stale", slot_id)
                return existing
            lease = GenerationLease(
                LEASE_SCHEMA,
                uuid.uuid4().hex,
                self.generation,
                slot_id,
                fence,
                time.time() + min(ttl_seconds, 86400),
            )
            view = SlotView(
                SLOT_SCHEMA,
                self.arena_id,
                self.generation,
                self.base_handle_id,
                slot_id,
                prism_id,
                lease.lease_id,
                fence,
                parent.slot_id if parent else None,
                max_overlay_bytes,
                max_overlay_files,
            )
            self._leases[lease.lease_id] = lease
            self._slots[slot_id] = view
            if parent:
                self._children.setdefault(parent.slot_id, set()).add(slot_id)
            lease_row = seal_receipt(
                f"schema={LEASE_SCHEMA}|action=pin|lease_id={lease.lease_id}"
                f"|generation={self.generation}|owner={slot_id}|fence_hash={_digest(fence)}"
                f"|expires_at={lease.expires_at:.6f}"
            )
            _atomic_bytes(
                self.storage / "leases" / f"{lease.lease_id}.hbp",
                (lease_row + "\n").encode(),
            )
            self._record(
                "pin",
                slot_id=slot_id,
                detail={"lease_id": lease.lease_id, "parent": view.parent_slot_id},
            )
            return view

    def child_slots(self, view: SlotView) -> tuple[SlotView, ...]:
        self._validate_slot(view)
        return tuple(
            self._slots[slot_id]
            for slot_id in sorted(self._children.get(view.slot_id, ()))
        )

    def _validate_slot(self, view: SlotView) -> GenerationLease:
        self._ensure_open()
        if (
            view.arena_id != self.arena_id
            or view.generation != self.generation
            or view.base_handle_id != self.base_handle_id
        ):
            raise ArenaError("slot_generation_stale", view.slot_id)
        lease = self._leases.get(view.lease_id)
        if lease is None or not lease.active or lease.expires_at <= time.time():
            raise ArenaError("lease_stale", view.slot_id)
        if lease.fence != view.fence:
            raise ArenaError("fence_stale", view.slot_id)
        return lease

    def renew_slot(self, view: SlotView, ttl_seconds: float = 3600) -> GenerationLease:
        if ttl_seconds <= 0:
            raise ArenaError("lease_ttl_invalid")
        lease = self._validate_slot(view)
        lease.expires_at = time.time() + min(ttl_seconds, 86400)
        self._record("renew", slot_id=view.slot_id, detail={"lease_id": lease.lease_id})
        return lease

    def release_slot(self, view: SlotView) -> None:
        lease = self._validate_slot(view)
        lease.active = False
        (self.storage / "leases" / f"{lease.lease_id}.hbp").unlink(missing_ok=True)
        for overlay in self._overlays.values():
            if overlay.slot_id == view.slot_id and overlay.active:
                overlay.active = False
                overlay.abandoned_at = time.time()
        self._record(
            "release", slot_id=view.slot_id, detail={"lease_id": lease.lease_id}
        )

    def create_overlay(
        self,
        view: SlotView,
        task_id: str,
        attempt: int,
        worktree_id: str,
        *,
        fence: str,
        max_bytes: int | None = None,
        max_files: int | None = None,
    ) -> TaskOverlay:
        self._validate_slot(view)
        _safe_component(task_id, "task_id")
        _safe_component(worktree_id, "worktree_id")
        if attempt < 1 or fence != view.fence:
            raise ArenaError("fence_stale", task_id)
        identity = {
            "arena": self.arena_id,
            "generation": self.generation,
            "slot": view.slot_id,
            "task": task_id,
            "attempt": attempt,
            "worktree": worktree_id,
            "fence": fence,
        }
        overlay_id = _digest(identity)
        with self._lock:
            existing = self._overlays.get(overlay_id)
            if existing is not None:
                return existing
            active = [
                overlay
                for overlay in self._overlays.values()
                if overlay.slot_id == view.slot_id and overlay.active
            ]
            if len(active) >= MAX_OVERLAYS_PER_SLOT:
                raise ArenaError("overlay_limit_exceeded", view.slot_id)
            overlay = TaskOverlay(
                OVERLAY_SCHEMA,
                overlay_id,
                self.arena_id,
                self.generation,
                self.base_handle_id,
                view.slot_id,
                task_id,
                attempt,
                worktree_id,
                fence,
                min(max_bytes or view.max_overlay_bytes, view.max_overlay_bytes),
                min(max_files or view.max_overlay_files, view.max_overlay_files),
                self.storage / "overlays" / view.slot_id / overlay_id,
            )
            overlay.path.mkdir(parents=True, exist_ok=True)
            metadata = seal_receipt(
                f"schema={OVERLAY_SCHEMA}|action=create|overlay_id={overlay_id}"
                f"|generation={self.generation}|base_handle_id={self.base_handle_id}"
                f"|slot_id={view.slot_id}|task_id={task_id}|attempt={attempt}"
                f"|worktree_hash={_digest(worktree_id)}|fence_hash={_digest(fence)}"
            )
            _atomic_bytes(overlay.path / "metadata.hbp", (metadata + "\n").encode())
            self._overlays[overlay_id] = overlay
            self._record(
                "overlay",
                slot_id=view.slot_id,
                overlay_id=overlay_id,
                detail={"task": task_id, "attempt": attempt},
            )
            return overlay

    def _validate_overlay(self, view: SlotView, overlay: TaskOverlay) -> None:
        self._validate_slot(view)
        if (
            not overlay.active
            or overlay.arena_id != self.arena_id
            or overlay.slot_id != view.slot_id
            or overlay.generation != self.generation
            or overlay.base_handle_id != self.base_handle_id
            or overlay.fence != view.fence
            or self._overlays.get(overlay.overlay_id) is not overlay
        ):
            raise ArenaError("overlay_stale", overlay.overlay_id)

    def base_read(self, view: SlotView, path: str) -> bytes | None:
        self._validate_slot(view)
        _safe_path(path)
        record = self._handle.catalog.get(path)
        if record is None:
            self._metrics["misses"] += 1
            return None
        offset, length, expected = record
        data = bytes(self._handle.mapping[offset : offset + length])
        if hashlib.sha256(data).hexdigest() != expected:
            raise ArenaError("snapshot_corrupt", path)
        self._metrics["base_reads"] += 1
        self._metrics["base_bytes"] += length
        page_size = getattr(mmap, "PAGESIZE", 4096)
        self._metrics["base_pages"] += max(1, (length + page_size - 1) // page_size)
        return data

    def read(self, view: SlotView, overlay: TaskOverlay, path: str) -> bytes | None:
        self._validate_overlay(view, overlay)
        _safe_path(path)
        if path in overlay.records:
            self._metrics["overlay_reads"] += 1
            object_hash = overlay.records[path]
            if object_hash is None:
                return None
            object_path = overlay.path / "objects" / object_hash
            try:
                data = object_path.read_bytes()
            except OSError as error:
                raise ArenaError("overlay_corrupt", path) from error
            if _digest(data) != object_hash:
                raise ArenaError("overlay_corrupt", path)
            return data
        return self.base_read(view, path)

    def apply_delta(
        self, view: SlotView, overlay: TaskOverlay, delta: PrismWorkDelta
    ) -> ArenaReceipt:
        self._validate_overlay(view, overlay)
        changed: dict[str, bytes | None] = {}
        for source, destination in sorted(delta.renames.items()):
            _safe_path(source)
            _safe_path(destination)
            content = self.read(view, overlay, source)
            if content is None:
                raise ArenaError("rename_source_missing", source)
            changed[source] = None
            changed[destination] = content
        for path in delta.deletes:
            changed[_safe_path(path)] = None
        for path, content in sorted(delta.writes.items()):
            _safe_path(path)
            if not isinstance(content, bytes):
                raise ArenaError("overlay_content_invalid", path)
            changed[path] = content
        candidate = dict(overlay.records)
        for path, content in changed.items():
            candidate[path] = None if content is None else _digest(content)
        if len(candidate) > overlay.max_files:
            raise ArenaError("overlay_file_budget_exceeded", overlay.overlay_id)
        sizes: dict[str, int] = {}
        for path, object_hash in candidate.items():
            if object_hash is None:
                continue
            if path in changed and changed[path] is not None:
                sizes[path] = len(changed[path] or b"")
            else:
                sizes[path] = (overlay.path / "objects" / object_hash).stat().st_size
        if sum(sizes.values()) > overlay.max_bytes:
            raise ArenaError("overlay_byte_budget_exceeded", overlay.overlay_id)
        with self._lock:
            for path, content in changed.items():
                if content is None:
                    continue
                object_hash = _digest(content)
                object_path = overlay.path / "objects" / object_hash
                if object_path.exists():
                    if _digest(object_path.read_bytes()) != object_hash:
                        raise ArenaError("overlay_corrupt", path)
                else:
                    _atomic_bytes(object_path, content)
                self._metrics["overlay_writes"] += 1
                self._metrics["overlay_bytes_written"] += len(content)
            previous = overlay.overlay_generation
            overlay.records = candidate
            overlay.dirty_spans.update(
                {
                    _safe_path(path): tuple(spans)
                    for path, spans in delta.dirty_spans.items()
                }
            )
            overlay.overlay_generation = _digest(
                {
                    "previous": previous,
                    "records": overlay.records,
                    "dirty_spans": overlay.dirty_spans,
                }
            )
            journal_path = overlay.path / "journal.hbp"
            rows = (
                journal_path.read_text(encoding="utf-8").splitlines()
                if journal_path.exists()
                else []
            )
            previous_event = verify_chain(rows) if rows else GENESIS
            row = seal_receipt(
                f"schema={OVERLAY_SCHEMA}|action=delta|overlay_id={overlay.overlay_id}"
                f"|overlay_generation={overlay.overlay_generation}|previous_generation={previous}"
                f"|changed_hash={_digest({path: None if value is None else _digest(value) for path, value in changed.items()})}"
                f"|records_hash={_digest(overlay.records)}",
                previous_event,
            )
            descriptor = os.open(
                journal_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
            )
            try:
                os.write(descriptor, (row + "\n").encode())
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return self._record(
                "delta",
                slot_id=view.slot_id,
                overlay_id=overlay.overlay_id,
                detail={
                    "overlay_generation": overlay.overlay_generation,
                    "changed": sorted(changed),
                },
            )

    def close_overlay(self, view: SlotView, overlay: TaskOverlay) -> None:
        self._validate_overlay(view, overlay)
        overlay.active = False
        overlay.abandoned_at = time.time()
        self._record(
            "overlay_close",
            slot_id=view.slot_id,
            overlay_id=overlay.overlay_id,
            detail={"generation": overlay.overlay_generation},
        )

    def cleanup_abandoned(
        self, *, older_than: float = 0, apply: bool = False
    ) -> dict[str, Any]:
        self._ensure_open()
        threshold = time.time() - max(0, older_than)
        candidates = sorted(
            overlay.overlay_id
            for overlay in self._overlays.values()
            if not overlay.active
            and overlay.abandoned_at is not None
            and overlay.abandoned_at <= threshold
        )
        removed: list[str] = []
        if apply:
            for overlay_id in candidates:
                overlay = self._overlays[overlay_id]
                shutil.rmtree(overlay.path)
                removed.append(overlay_id)
                del self._overlays[overlay_id]
        self._record("cleanup", detail={"candidates": candidates, "removed": removed})
        return {
            "schema": RECEIPT_SCHEMA,
            "candidates": candidates,
            "removed": removed,
            "base_active": not self._closed,
            "base_path": str(self.base_path),
        }

    def refresh(self, source_hash: str, files: Mapping[str, bytes]) -> "PrismArena":
        self._ensure_open()
        refreshed = type(self).publish(self.storage, self.repo, source_hash, files)
        self._draining = True
        self._record(
            "refresh",
            detail={
                "new_generation": refreshed.generation,
                "old_readers": self.active_readers,
            },
        )
        return refreshed

    @property
    def active_readers(self) -> int:
        return sum(
            1
            for lease in self._leases.values()
            if lease.active and lease.expires_at > time.time()
        )

    def metrics(self) -> dict[str, Any]:
        self._ensure_open()
        rss = _peak_rss_kib()
        active_overlays = sum(
            1 for overlay in self._overlays.values() if overlay.active
        )
        return {
            "schema": METRICS_SCHEMA,
            "generation": self.generation,
            "base_handle_id": self.base_handle_id,
            "base_refcount": self._handle.refcount,
            "base_reuse_count": self._handle.reuse_count,
            "base_size_bytes": len(self._handle.mapping),
            "slots": len(self._slots),
            "active_readers": self.active_readers,
            "active_overlays": active_overlays,
            "rss_kib": int(rss),
            "io": {
                "read_bytes": self._metrics["base_bytes"],
                "write_bytes": self._metrics["overlay_bytes_written"],
            },
            "pages": {"read": self._metrics["base_pages"]},
            "cache": {
                "base_hits": self._metrics["base_reads"],
                "overlay_hits": self._metrics["overlay_reads"],
                "misses": self._metrics["misses"],
            },
            "draining": self._draining,
        }

    def projection(self):
        """Return the read-only operations view in the shared projection ABI."""
        from .projection import ProjectionEnvelope

        metrics = self.metrics()
        payload = {
            "repository": self.repo,
            "arena_id": self.arena_id,
            "metrics": metrics,
        }
        return ProjectionEnvelope.create(
            "operations",
            producer="simplicio-fast.prism-arena",
            producer_schema=METRICS_SCHEMA,
            generation=self.generation,
            stable_handle=f"arena:{self.arena_id}:{self.generation}",
            payload=payload,
        )

    def close(self) -> None:
        if self._closed:
            return
        for lease in self._leases.values():
            lease.active = False
            (self.storage / "leases" / f"{lease.lease_id}.hbp").unlink(missing_ok=True)
        self._record("close", detail={"active_readers": 0})
        key = (str(self.base_path), self.generation)
        with _REGISTRY_LOCK:
            self._handle.refcount -= 1
            if self._handle.refcount == 0:
                self._handle.mapping.close()
                self._handle.stream.close()
                _HANDLE_REGISTRY.pop(key, None)
        self._closed = True

    def __enter__(self) -> "PrismArena":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = [
    "ARENA_SCHEMA",
    "BENCHMARK_SCHEMA",
    "MAX_OVERLAYS_PER_SLOT",
    "ArenaError",
    "ArenaReceipt",
    "GenerationLease",
    "PrismArena",
    "PrismWorkDelta",
    "SlotView",
    "TaskOverlay",
    "encode_base",
]
