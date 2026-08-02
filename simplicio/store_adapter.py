"""Small MapperStore persistence boundary for Dev CLI state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from simplicio_mapper.mapper.file_lock import (
        LockHandle,
        acquire_lock_at,
        inspect_lock_at,
        release_lock_at,
    )

    _MAPPER_IMPORT_ERROR: Exception | None = None
except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - exercised in installed smoke
    LockHandle = Any  # type: ignore[misc,assignment]
    acquire_lock_at = None  # type: ignore[assignment]
    inspect_lock_at = None  # type: ignore[assignment]
    release_lock_at = None  # type: ignore[assignment]
    _MAPPER_IMPORT_ERROR = exc


class StoreAdapterError(RuntimeError):
    """A durable MapperStore record could not be read or written."""


STORAGE_CAPABILITIES_SCHEMA = "simplicio.dev-cli.storage-capabilities/v1"
MAPPER_STORE_DOMAINS = (
    "effect-transactions",
    "mutations",
    "prism-transactions",
    "locks",
    "memory-index",
    "memory-notes",
)
MAPPER_MIN_VERSION = (0, 26, 2)
ROUTE_SCHEMA = "simplicio.dev-cli.storage-route/v1"
ROUTE_FILENAME = "route.json"
LEGACY_STORE_PATHS = (
    ".simplicio/effect-transactions.sqlite3",
    ".simplicio/mutation-worker.sqlite3",
    ".simplicio/prism-transactions.sqlite3",
    ".simplicio/write-set-locks.sqlite3",
    ".simplicio/memory/index.sqlite3",
)
_ROUTE_FREEZE_LOCK = threading.Lock()


def storage_capabilities(root: str | Path = ".") -> dict[str, Any]:
    """Return read-only cutover diagnostics without materializing state."""
    resolved = Path(root).resolve()
    mapper_store_root = resolved / ".simplicio" / "mapper-store"
    mapper_version, mapper_ready, mapper_reason = _mapper_status()
    route_path = mapper_store_root / ROUTE_FILENAME
    route_receipt = _read_route(route_path)
    legacy = {
        path: {
            "present": (resolved / path).is_file(),
            "path": path,
            "authority": "legacy-read-only",
        }
        for path in LEGACY_STORE_PATHS
    }
    payload: dict[str, Any] = {
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
            "selected": "mapper-store" if route_receipt is not None or mapper_ready else "blocked",
            "frozen_before_effect": True,
            "reason": "mapper-capability-ready" if mapper_ready else mapper_reason,
        },
    }
    if route_receipt is not None:
        payload["route"].update({"frozen": True, "receipt": route_receipt})
    return payload


def _mapper_status() -> tuple[str | None, bool, str]:
    if _MAPPER_IMPORT_ERROR is not None:
        if isinstance(_MAPPER_IMPORT_ERROR, ModuleNotFoundError) and _MAPPER_IMPORT_ERROR.name in {
            None,
            "simplicio_mapper",
        }:
            return None, False, "mapper-package-not-installed"
        return None, False, "mapper-api-unavailable"
    try:
        import importlib.metadata

        mapper_version = os.environ.get("SIMPLICIO_MAPPER_VERSION") or importlib.metadata.version(
            "simplicio-mapper"
        )
    except importlib.metadata.PackageNotFoundError:
        return None, False, "mapper-package-not-installed"
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", mapper_version)
    parsed = tuple(int(part or 0) for part in match.groups()) if match else None
    if parsed is None or parsed < MAPPER_MIN_VERSION:
        return mapper_version, False, "mapper-version-incompatible"
    if not callable(acquire_lock_at) or not callable(inspect_lock_at) or not callable(release_lock_at):
        return mapper_version, False, "mapper-api-unavailable"
    return mapper_version, True, "installed"


def _require_mapper_store() -> None:
    _version, ready, reason = _mapper_status()
    if not ready:
        raise StoreAdapterError(f"MAPPER_STORE_UNAVAILABLE:{reason}")


def _read_route(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:route-invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema") != ROUTE_SCHEMA:
        raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:route-invalid")
    if payload.get("selected") != "mapper-store":
        raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:route-frozen")
    return payload


def _freeze_route(root: Path, mapper_version: str | None) -> None:
    with _ROUTE_FREEZE_LOCK:
        route_root = root / ".simplicio" / "mapper-store"
        route_path = route_root / ROUTE_FILENAME
        existing = _read_route(route_path)
        if existing is not None:
            return
        route_root.mkdir(parents=True, exist_ok=True)
        temporary = route_path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
        payload = {
            "schema": ROUTE_SCHEMA,
            "selected": "mapper-store",
            "mapper_min_version": ".".join(str(part) for part in MAPPER_MIN_VERSION),
            "mapper_version": mapper_version,
            "frozen_before_effect": True,
        }
        try:
            serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            for attempt in range(3):
                try:
                    temporary.write_text(serialized, encoding="utf-8")
                    os.replace(temporary, route_path)
                    return
                except OSError as exc:
                    try:
                        if _read_route(route_path) is not None:
                            return
                    except StoreAdapterError:
                        # A concurrent Windows replace can leave the route briefly
                        # unreadable; retry the same atomic publication window.
                        pass
                    if attempt == 2:
                        raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:route-freeze-failed") from exc
                    time.sleep(0.01)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass


class MapperStoreAdapter:
    """Content-addressed JSON records guarded by Mapper-owned file locks."""

    def __init__(self, root: str | Path, domain: str) -> None:
        mapper_version, ready, reason = _mapper_status()
        if not ready:
            raise StoreAdapterError(f"MAPPER_STORE_UNAVAILABLE:{reason}")
        self.root = Path(root).resolve()
        _freeze_route(self.root, mapper_version)
        self.directory = self.root / ".simplicio" / "mapper-store" / domain
        self.directory.mkdir(parents=True, exist_ok=True)

    def _digest(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def record_path(self, key: str) -> Path:
        return self.directory / f"{self._digest(key)}.json"

    def lock_path(self, key: str) -> Path:
        return self.directory / f"{self._digest(key)}.lock"

    def acquire(self, key: str, *, operation: str) -> LockHandle:
        _require_mapper_store()
        if acquire_lock_at is None:
            raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:mapper-api-unavailable")
        handle = acquire_lock_at(str(self.lock_path(key)), operation=operation)
        if handle is None:
            raise StoreAdapterError("STORE_LOCKED")
        return handle

    @staticmethod
    def release(handle: LockHandle) -> None:
        if release_lock_at is None:
            raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:mapper-api-unavailable")
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
        _require_mapper_store()
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
        _require_mapper_store()
        if acquire_lock_at is None or release_lock_at is None:
            raise StoreAdapterError("MAPPER_STORE_UNAVAILABLE:mapper-api-unavailable")
        handle = acquire_lock_at(str(self.lock_path(key)), operation=operation)
        if handle is None:
            raise StoreAdapterError("STORE_LOCKED")
        try:
            yield handle
        finally:
            release_lock_at(handle)
