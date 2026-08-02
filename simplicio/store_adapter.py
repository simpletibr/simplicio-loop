"""Small MapperStore persistence boundary for Dev CLI state."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from simplicio_mapper.mapper.file_lock import LockHandle, acquire_lock_at, release_lock_at


class StoreAdapterError(RuntimeError):
    """A durable MapperStore record could not be read or written."""


STORAGE_CAPABILITIES_SCHEMA = "simplicio.dev-cli.storage-capabilities/v1"
MAPPER_STORE_DOMAINS = ("effect-transactions", "mutation-worker", "prism-transactions", "write-set-locks")
LEGACY_STORE_PATHS = (
    ".simplicio/effect-transactions.sqlite3",
    ".simplicio/mutation-worker.sqlite3",
    ".simplicio/prism-transactions.sqlite3",
    ".simplicio/write-set-locks.sqlite3",
    ".simplicio/memory/index.sqlite3",
)


def storage_capabilities(root: str | Path = ".") -> dict[str, Any]:
    """Return read-only cutover diagnostics without materializing state."""
    resolved = Path(root).resolve()
    mapper_store_root = resolved / ".simplicio" / "mapper-store"
    try:
        import importlib.metadata

        mapper_version = importlib.metadata.version("simplicio-mapper")
        mapper_ready = True
        mapper_reason = "installed"
    except importlib.metadata.PackageNotFoundError:
        mapper_version = None
        mapper_ready = False
        mapper_reason = "mapper-package-not-installed"
    legacy = {
        path: {
            "present": (resolved / path).is_file(),
            "path": path,
            "authority": "legacy-read-only",
        }
        for path in LEGACY_STORE_PATHS
    }
    return {
        "schema": STORAGE_CAPABILITIES_SCHEMA,
        "root": str(resolved),
        "read_only": True,
        "side_effects": {"directories_created": 0, "files_created": 0, "writes": 0},
        "mapper_store": {
            "ready": mapper_ready,
            "reason": mapper_reason,
            "version": mapper_version,
            "root": str(mapper_store_root),
            "present": mapper_store_root.is_dir(),
            "domains": {domain: (mapper_store_root / domain).is_dir() for domain in MAPPER_STORE_DOMAINS},
        },
        "legacy": legacy,
        "route": {
            "selected": "mapper-store" if mapper_ready else "blocked",
            "frozen_before_effect": True,
            "reason": "mapper-capability-ready" if mapper_ready else mapper_reason,
        },
    }


class MapperStoreAdapter:
    """Content-addressed JSON records guarded by Mapper-owned file locks."""

    def __init__(self, root: str | Path, domain: str) -> None:
        self.root = Path(root).resolve()
        self.directory = self.root / ".simplicio" / "mapper-store" / domain
        self.directory.mkdir(parents=True, exist_ok=True)

    def _digest(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def record_path(self, key: str) -> Path:
        return self.directory / f"{self._digest(key)}.json"

    def lock_path(self, key: str) -> Path:
        return self.directory / f"{self._digest(key)}.lock"

    def acquire(self, key: str, *, operation: str) -> LockHandle:
        handle = acquire_lock_at(str(self.lock_path(key)), operation=operation)
        if handle is None:
            raise StoreAdapterError("STORE_LOCKED")
        return handle

    @staticmethod
    def release(handle: LockHandle) -> None:
        release_lock_at(handle)

    def read(self, key: str) -> dict[str, Any] | None:
        path = self.record_path(key)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreAdapterError("STORE_CORRUPT") from exc
        if not isinstance(value, dict):
            raise StoreAdapterError("STORE_CORRUPT")
        return value

    def write(self, key: str, value: dict[str, Any]) -> None:
        target = self.record_path(key)
        temporary = target.with_suffix(f".tmp-{os.getpid()}")
        try:
            temporary.write_text(
                json.dumps(value, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with temporary.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(5):
                try:
                    os.replace(temporary, target)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        except OSError as exc:
            raise StoreAdapterError("STORE_WRITE_FAILED") from exc

    @contextmanager
    def lock(self, key: str, *, operation: str) -> Iterator[LockHandle]:
        handle = acquire_lock_at(str(self.lock_path(key)), operation=operation)
        if handle is None:
            raise StoreAdapterError("STORE_LOCKED")
        try:
            yield handle
        finally:
            release_lock_at(handle)
