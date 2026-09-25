"""Side-effect-free MapperStore status and capability inspection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .connection import StoreConnection, StoreMissingError
from .paths import StorePathError, reject_network_path, reject_symlink_components
from .profiles import StoreMode, StoreProfile


def inspect_store(
    path: str | Path,
    *,
    profile: StoreProfile | None = None,
    path_source: str = "explicit",
) -> dict[str, object]:
    """Return deterministic status without creating a file or directory."""

    selected = profile or StoreProfile.read_only()
    if selected.mode not in {StoreMode.READ_ONLY, StoreMode.BACKUP}:
        raise ValueError("status inspection requires a read-only or backup profile")
    if path_source not in {"explicit", "flag", "env", "home", "repo", "temp"}:
        raise ValueError(f"invalid path_source: {path_source}")
    target = Path(path).expanduser()
    payload: dict[str, object] = {
        "schema": "simplicio.mapper-store-status/v1",
        "path": str(target.resolve(strict=False)),
        "path_source": path_source,
        "persistence": "sqlite",
        "mode": selected.mode.value,
        "timeout": selected.timeout_seconds,
        "journal_mode": None,
        "schema_version": None,
        "capabilities": {"wal": False, "fts5": False, "sqlite_vec": False},
        "status": "missing",
        "reason_code": "STORE_MISSING",
    }
    try:
        reject_network_path(path)
        reject_symlink_components(path)
    except StorePathError:
        payload.update({"status": "unsafe", "reason_code": "STORE_UNSAFE_PATH"})
        return payload
    if target.is_symlink() or (target.exists() and not target.is_file()):
        payload.update({"status": "unsafe", "reason_code": "STORE_UNSAFE_PATH"})
        return payload
    if not target.exists():
        return payload
    try:
        wal_sidecar = target.with_name(target.name + "-wal")
        shm_sidecar = target.with_name(target.name + "-shm")
        with target.open("rb") as header_file:
            header = header_file.read(20)
        header_wal = len(header) > 19 and (header[18] == 2 or header[19] == 2)
        if wal_sidecar.exists() != shm_sidecar.exists():
            payload.update({"status": "unsafe", "reason_code": "STORE_WAL_INCOMPLETE"})
            return payload
        if wal_sidecar.exists() and (wal_sidecar.stat().st_size == 0 or shm_sidecar.stat().st_size == 0):
            payload.update({"status": "unsafe", "reason_code": "STORE_WAL_INVALID"})
            return payload
        live_wal = wal_sidecar.exists() and shm_sidecar.exists()
        with StoreConnection.open(target, selected, immutable=not live_wal) as store:
            journal = str(store.connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if live_wal or header_wal:
                journal = "wal"
            compile_options = {
                str(row[0]).lower() for row in store.connection.execute("PRAGMA compile_options")
            }
            module_names = {
                str(row[0]).lower() for row in store.connection.execute("SELECT name FROM pragma_module_list")
            }
            payload.update(
                {
                    "status": "ready",
                    "reason_code": None,
                    "journal_mode": journal,
                    "schema_version": int(store.connection.execute("PRAGMA user_version").fetchone()[0]),
                    "capabilities": {
                        "wal": journal == "wal",
                        "fts5": "enable_fts5" in compile_options,
                        "sqlite_vec": any(name.startswith(("vec", "sqlite_vec")) for name in module_names),
                    },
                }
            )
    except StoreMissingError:
        return payload
    except StorePathError:
        payload.update({"status": "unsafe", "reason_code": "STORE_UNSAFE_PATH"})
        return payload
    except (OSError, sqlite3.Error) as error:
        payload.update(
            {"status": "corrupt", "reason_code": "STORE_OPEN_FAILED", "error_type": type(error).__name__}
        )
    return payload
