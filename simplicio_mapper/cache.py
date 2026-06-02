"""Persistent cache helpers for mapper file processing."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from diskcache import Cache


class FileProcessingCache:
    """Disk-backed cache for parsed file metadata.

    The cache key uses normalized path, size and mtime. This avoids re-reading
    unchanged files during large mapping runs while naturally invalidating when a
    file changes on disk.
    """

    __slots__ = ("_cache",)

    VERSION = "v1"

    def __init__(self, cache_dir: str | Path) -> None:
        self._cache = Cache(str(cache_dir))

    def __enter__(self) -> FileProcessingCache:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._cache.close()

    def clear(self) -> None:
        self._cache.clear()

    def make_file_key(self, path: str | Path, size_bytes: int, mtime_ns: int) -> str:
        normalized = Path(path).as_posix()
        raw = f"{self.VERSION}:{normalized}:{size_bytes}:{mtime_ns}".encode()
        digest = hashlib.blake2b(raw, digest_size=24).hexdigest()
        return f"file:{digest}"

    def get_processed_file(self, path: str | Path, size_bytes: int, mtime_ns: int) -> dict[str, Any] | None:
        value = self._cache.get(self.make_file_key(path, size_bytes, mtime_ns))
        return value if isinstance(value, dict) else None

    def set_processed_file(
        self,
        path: str | Path,
        size_bytes: int,
        mtime_ns: int,
        result: dict[str, Any],
        expire: int | None = None,
    ) -> None:
        self._cache.set(self.make_file_key(path, size_bytes, mtime_ns), result, expire=expire)
