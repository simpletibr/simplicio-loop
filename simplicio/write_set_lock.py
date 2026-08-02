"""Write-set locks, capability leases and fencing (#365).

Loop owns concurrency policy. Dev CLI enforces mutual exclusion on write-set
paths and rejects stale fencing tokens before mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

try:
    from simplicio_mapper.mapper.file_lock import (
        LockHandle,
        acquire_lock_at,
        inspect_lock_at,
        release_lock_at,
    )
except ImportError as exc:  # pragma: no cover - exercised by dependency gate
    LockHandle = cast(Any, None)
    acquire_lock_at = inspect_lock_at = release_lock_at = cast(Any, None)
    _MAPPER_IMPORT_ERROR: ImportError | None = exc
else:
    _MAPPER_IMPORT_ERROR = None


class LockError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _normalize(path: str) -> str:
    value = path.replace("\\", "/").strip()
    if not value or value.startswith("/") or ".." in value.split("/"):
        raise LockError("UNSAFE_PATH", path)
    return value


class WriteSetLockManager:
    """MapperStore file-lock backed exclusive locks."""

    def __init__(self, root: str | Path) -> None:
        if _MAPPER_IMPORT_ERROR is not None:
            raise LockError("MAPPER_STORE_UNAVAILABLE", str(_MAPPER_IMPORT_ERROR))
        self.root = Path(root).resolve()
        self.lock_root: Path = self.root / ".simplicio" / "mapper-store" / "locks"
        self.lock_root.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, LockHandle] = {}

    def _lock_path(self, path: str) -> Path:
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        return self.lock_root / f"{digest}.lock"

    @staticmethod
    def _record_path(status: dict[str, Any]) -> str | None:
        owner = status.get("owner")
        if not isinstance(owner, dict):
            return None
        value = owner.get("write_set_path")
        return value if isinstance(value, str) else None

    @staticmethod
    def _handle_from_status(lock_path: Path, status: dict[str, Any]) -> LockHandle | None:
        owner = status.get("owner")
        if not isinstance(owner, dict):
            return None
        token = owner.get("owner_token", owner.get("token"))
        if not isinstance(token, str) or not token:
            return None
        return LockHandle(path=str(lock_path), token=token, extra={
            "write_set_path": owner.get("write_set_path", ""),
            "owner": owner.get("owner", ""),
            "lease_id": owner.get("lease_id", ""),
            "fencing_token": owner.get("fencing_token", ""),
        })

    def _release_handles(self, handles: Sequence[LockHandle]) -> None:
        for handle in handles:
            release_lock_at(handle)

    def acquire(
        self,
        paths: Sequence[str],
        *,
        owner: str,
        lease_id: str,
        fencing_token: str,
        active_fence: str | None = None,
    ) -> dict[str, Any]:
        if not owner or not lease_id or not fencing_token:
            raise LockError("LEASE_REQUIRED")
        if active_fence is not None and active_fence != fencing_token:
            raise LockError("STALE_FENCE", fencing_token)
        ordered = sorted({_normalize(path) for path in paths})
        if not ordered:
            raise LockError("EMPTY_WRITE_SET")

        acquired: list[LockHandle] = []
        try:
            for path in ordered:
                lock_path = self._lock_path(path)
                status = inspect_lock_at(str(lock_path), recover=True)
                if status.get("active"):
                    record = status.get("owner") or {}
                    if record.get("owner") != owner or record.get("lease_id") != lease_id:
                        raise LockError(
                            "CONFLICT_BLOCKED",
                            f"{path} held by {record.get('owner', 'unknown')}",
                        )
                    handle = self._handle_from_status(lock_path, status)
                    if handle is None:
                        raise LockError("MAPPER_STORE_PERSISTENCE_FAILED", path)
                else:
                    handle = acquire_lock_at(
                        str(lock_path),
                        operation="write-set",
                        extra_fields={
                            "write_set_path": path,
                            "owner": owner,
                            "lease_id": lease_id,
                            "fencing_token": fencing_token,
                        },
                    )
                    if handle is None:
                        raise LockError("CONFLICT_BLOCKED", path)
                acquired.append(handle)
                self._handles[path] = handle
        except LockError:
            self._release_handles(acquired)
            for path in ordered:
                self._handles.pop(path, None)
            raise
        except OSError as exc:
            self._release_handles(acquired)
            for path in ordered:
                self._handles.pop(path, None)
            raise LockError("MAPPER_STORE_PERSISTENCE_FAILED", str(exc)) from exc
        return {
            "schema": "simplicio.write-set-lock-receipt/v1",
            "owner": owner,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
            "paths": ordered,
            "status": "acquired",
        }

    def validate_fence(self, fencing_token: str, *, expected: str) -> None:
        if fencing_token != expected:
            raise LockError("STALE_FENCE", fencing_token)

    def release(self, *, owner: str, lease_id: str) -> dict[str, Any]:
        for lock_path in self.lock_root.glob("*.lock"):
            status = inspect_lock_at(str(lock_path), recover=False)
            if not status.get("active"):
                continue
            record = status.get("owner") or {}
            if record.get("owner") == owner and record.get("lease_id") == lease_id:
                handle = self._handle_from_status(lock_path, status)
                release_lock_at(handle)
                path = self._record_path(status)
                if path:
                    self._handles.pop(path, None)
        return {
            "schema": "simplicio.write-set-lock-receipt/v1",
            "owner": owner,
            "lease_id": lease_id,
            "status": "released",
        }

    def held_paths(self) -> list[str]:
        paths: list[str] = []
        for lock_path in self.lock_root.glob("*.lock"):
            status = inspect_lock_at(str(lock_path), recover=False)
            if status.get("active"):
                path = self._record_path(status)
                if path:
                    paths.append(path)
        return sorted(paths)
