"""Cross-platform advisory file locks with explicit ownership metadata."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .paths import reject_network_path, reject_symlink_components


class StoreLockError(RuntimeError):
    """Raised when a lock cannot be acquired or released safely."""


class StoreFileLock:
    """Process-scoped advisory lock; the lock file is never used as a database."""

    def __init__(self, path: str | Path, *, owner: str, blocking: bool = False) -> None:
        if not owner or not owner.strip():
            raise ValueError("lock owner is required")
        self.path = Path(path)
        self.owner = owner.strip()
        self.blocking = blocking
        self._handle = None

    def acquire(self) -> StoreFileLock:
        if self._handle is not None:
            raise StoreLockError("lock already acquired")
        try:
            reject_network_path(self.path)
            reject_symlink_components(self.path)
        except Exception as error:
            raise StoreLockError(f"unsafe lock path: {self.path}") from error
        try:
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        except OSError as error:
            raise StoreLockError(f"lock parent unavailable: {self.path.parent}") from error
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
            self._handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        except OSError as error:
            raise StoreLockError(f"lock unavailable: {self.path}") from error
        try:
            if os.name == "nt":  # pragma: no cover - exercised by Windows CI
                import msvcrt

                self._handle.seek(0)
                if self._handle.read(1) == "":
                    self._handle.seek(0)
                    self._handle.write("\0")
                    self._handle.flush()
                self._handle.seek(0)
                mode = msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK
                msvcrt.locking(self._handle.fileno(), mode, 1)
            else:
                import fcntl

                flags = fcntl.LOCK_EX if self.blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(self._handle.fileno(), flags)
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(
                json.dumps({"owner": self.owner, "pid": os.getpid(), "platform": sys.platform}) + "\n"
            )
            self._handle.flush()
            return self
        except (OSError, BlockingIOError) as error:
            self._handle.close()
            self._handle = None
            raise StoreLockError(f"lock unavailable: {self.path}") from error

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":  # pragma: no cover - exercised by Windows CI
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> StoreFileLock:
        return self.acquire()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.release()
