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
