"""Operational MapperStore doctor, safe repair and capacity checks.

The doctor is deliberately read-only.  Backup/restore and repair live in
separate functions so callers cannot accidentally turn a health check into a
mutation.  Reports contain counts, hashes and reason codes, never row content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import quote

from .paths import StorePathError, reject_network_path, reject_symlink_components

DOCTOR_SCHEMA = "simplicio.mapper-store.doctor/v1"
REPAIR_SCHEMA = "simplicio.mapper-store.repair/v1"
CAPACITY_SCHEMA = "simplicio.mapper-store.capacity/v1"
_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|client[_-]?secret|secret)\s*[:=]\s*['\"]?[^\s,;'\"]+|Bearer\s+[A-Za-z0-9._~+/=-]+"
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|authorization|password|secret)"
)
HEALTH_STATES = (
    "missing",
    "legacy",
    "migrating",
    "ready",
    "stale",
    "corrupt",
    "split_brain",
    "rollback_required",
)


class DoctorError(RuntimeError):
    """Typed operational failure with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical(value).encode("utf-8"))


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise DoctorError("SCHEMA_IDENTIFIER_INVALID", value)
    return f'"{value}"'


def redact(value: Any) -> Any:
    """Recursively redact secret-shaped values before they enter a report."""

    if isinstance(value, str):
        return _SECRET_RE.sub("[REDACTED]", value)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY_RE.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def _safe_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    reject_network_path(path)
    reject_symlink_components(path)
    if not path.name or path.name in {".", ".."}:
        raise StorePathError("store path must name a file")
    return path.absolute()


def _sidecars(path: Path) -> dict[str, int]:
    return {
        suffix: (
            path.with_name(path.name + suffix).stat().st_size
            if path.with_name(path.name + suffix).is_file()
            else 0
        )
        for suffix in ("-wal", "-shm")
    }


def _lock_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "present": False, "active": False, "stale": False, "owner": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"path": str(path), "present": True, "active": False, "stale": True, "owner": None}
    pid = payload.get("pid")
    active = False
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            active = True
        except (OSError, ProcessLookupError):
            active = False
    return {
        "path": str(path),
        "present": True,
        "active": active,
        "stale": not active,
        "owner": redact(payload.get("owner")),
        "pid": pid,
        "platform": payload.get("platform"),
    }


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view','virtual table')"
        )
    }


def _schema_checksum(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type, name, COALESCE(sql, '') FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return _sha_json([[str(kind), str(name), str(sql)] for kind, name, sql in rows])


def _schema_markers(connection: sqlite3.Connection) -> list[str]:
    markers: list[str] = []
    for table in ("semantic_store_meta", "memory_store_meta", "operations_meta", "mapper_schema_registry"):
        if table not in _table_names(connection):
            continue
        try:
            row = connection.execute(
                f"SELECT value FROM {_identifier(table)} WHERE key='schema' LIMIT 1"  # noqa: S608
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row:
            markers.append(str(row[0]))
    return sorted(markers)


def _check_fts(connection: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
    if "semantic_fts" not in tables or "semantic_chunks" not in tables:
        return {
            "available": False,
            "synchronized": None,
            "rows": None,
            "expected_rows": None,
            "orphan_rows": 0,
        }
    try:
        rows = int(connection.execute("SELECT COUNT(*) FROM semantic_fts").fetchone()[0])
        expected = int(
            connection.execute("SELECT COUNT(*) FROM semantic_chunks WHERE tombstone=0").fetchone()[0]
        )
        orphan = int(
            connection.execute(
                "SELECT COUNT(*) FROM semantic_fts f LEFT JOIN semantic_chunks c ON c.chunk_id=f.chunk_id "
                "WHERE c.chunk_id IS NULL OR c.tombstone=1"
            ).fetchone()[0]
        )
        missing = int(
            connection.execute(
                "SELECT COUNT(*) FROM semantic_chunks c LEFT JOIN semantic_fts f ON f.chunk_id=c.chunk_id "
                "WHERE c.tombstone=0 AND f.chunk_id IS NULL"
            ).fetchone()[0]
        )
    except sqlite3.Error as error:
        return {
            "available": True,
            "synchronized": False,
            "reason_code": "FTS_CHECK_FAILED",
            "error_type": type(error).__name__,
        }
    return {
        "available": True,
        "synchronized": rows == expected and orphan == 0 and missing == 0,
        "rows": rows,
        "expected_rows": expected,
        "orphan_rows": orphan,
        "missing_rows": missing,
    }


def _check_references(connection: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    result = {"memory_without_semantic": 0, "semantic_memory_without_entry": 0}
    if {"memory_entries", "semantic_items"}.issubset(tables):
        result["memory_without_semantic"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_entries e LEFT JOIN semantic_items i ON i.stable_id=e.stable_id "
                "WHERE e.tombstone=0 AND i.stable_id IS NULL"
            ).fetchone()[0]
        )
        result["semantic_memory_without_entry"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM semantic_items i LEFT JOIN memory_entries e ON e.stable_id=i.stable_id "
                "WHERE i.kind='memory' AND i.tombstone=0 AND e.stable_id IS NULL"
            ).fetchone()[0]
        )
    return result


def _check_migration(connection: sqlite3.Connection) -> dict[str, Any]:
    if "migration_ledger" not in _table_names(connection):
        return {"present": False, "events": 0, "latest": None, "valid": None}
    rows = connection.execute(
        "SELECT event, event_hash, previous_hash FROM migration_ledger ORDER BY seq"
    ).fetchall()
    valid = True
    previous = ""
    for _event, event_hash, previous_hash in rows:
        if str(previous_hash) != previous:
            valid = False
        previous = str(event_hash)
    latest = str(rows[-1][0]) if rows else None
    return {"present": True, "events": len(rows), "latest": latest, "valid": valid}


def _active_pointer(path: Path) -> dict[str, Any] | None:
    pointer = path.with_name(path.name + ".active.json")
    if not pointer.exists():
        return None
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"path": str(pointer), "valid": False, "reason_code": "ACTIVE_POINTER_INVALID"}
    return {"path": str(pointer), "valid": isinstance(value, dict), **redact(value)}


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise DoctorError("STORE_MISSING", str(path))
    wal = path.with_name(path.name + "-wal").is_file()
    query = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro" + ("" if wal else "&immutable=1")
    connection = sqlite3.connect(query, uri=True, isolation_level=None, timeout=5)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def doctor_store(
    path: str | Path,
    *,
    path_source: str = "explicit",
    max_bytes: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Inspect one store without creating files, directories, WAL or locks."""

    if path_source not in {"explicit", "flag", "env", "home", "repo", "temp"}:
        raise ValueError(f"invalid path_source: {path_source}")
    target = _safe_path(path)
    payload: dict[str, Any] = {
        "schema": DOCTOR_SCHEMA,
        "path": str(target),
        "path_source": path_source,
        "state": "missing",
        "reason_codes": ["STORE_MISSING"],
        "side_effects": False,
        "checks": {},
        "capabilities": {"fts5": None, "sqlite_vec": None},
        "counts": {},
        "alerts": [],
    }
    if not target.exists():
        return payload
    if target.is_symlink() or not target.is_file():
        payload.update({"state": "corrupt", "reason_codes": ["STORE_UNSAFE_PATH"]})
        return payload
    locks = {
        name: _lock_info(target.with_name(target.name + suffix))
        for name, suffix in (("writer", ".writer.lock"), ("migration", ".migration.lock"))
    }
    payload["checks"]["locks"] = locks
    pointer = _active_pointer(target)
    payload["checks"]["active_pointer"] = pointer
    if pointer and pointer.get("valid") and pointer.get("writer_authority") not in {None, "mapper-store"}:
        payload.update({"state": "split_brain", "reason_codes": ["MULTIPLE_WRITER_AUTHORITIES"]})
    if locks["migration"]["active"]:
        payload.update({"state": "migrating", "reason_codes": ["MIGRATION_LOCK_ACTIVE"]})
    before = set(target.parent.iterdir())
    try:
        with closing(_open_readonly(target)) as connection:
            tables = _table_names(connection)
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0]).lower()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            compile_options = {str(row[0]).upper() for row in connection.execute("PRAGMA compile_options")}
            modules = {
                str(row[0]).casefold() for row in connection.execute("SELECT name FROM pragma_module_list")
            }
            fts = _check_fts(connection, tables)
            references = _check_references(connection, tables)
            migration = _check_migration(connection)
            markers = _schema_markers(connection)
            row_counts = {}
            for name in sorted(tables):
                if name.startswith("sqlite_") or name.startswith("fts"):
                    continue
                try:
                    row_counts[name] = int(
                        connection.execute(f"SELECT COUNT(*) FROM {_identifier(name)}").fetchone()[0]  # noqa: S608
                    )
                except sqlite3.Error:
                    row_counts[name] = None
            payload["checks"].update(
                {
                    "integrity": integrity,
                    "foreign_keys": {"ok": not foreign_keys, "violations": len(foreign_keys)},
                    "schema_checksum": _schema_checksum(connection),
                    "migration": migration,
                    "fts": fts,
                    "references": references,
                    "tables": sorted(tables),
                }
            )
            payload["capabilities"] = {
                "fts5": "ENABLE_FTS5" in compile_options,
                "sqlite_vec": any(name.startswith(("vec", "sqlite_vec")) for name in modules),
                "vec_observed": any("embedding" in name for name in tables),
            }
            payload["counts"] = {
                "rows": row_counts,
                "database_bytes": target.stat().st_size,
                "wal_bytes": _sidecars(target)["-wal"],
            }
            expected_checksum = None
            for meta_table in ("semantic_store_meta", "memory_store_meta", "operations_meta"):
                if meta_table in tables:
                    row = connection.execute(
                        f"SELECT value FROM {_identifier(meta_table)} WHERE key='schema_checksum' LIMIT 1"  # noqa: S608
                    ).fetchone()
                    if row:
                        expected_checksum = str(row[0])
                        break
            if expected_checksum:
                payload["checks"]["schema_checksum_expected"] = expected_checksum
                if expected_checksum != payload["checks"]["schema_checksum"]:
                    payload["reason_codes"].append("SCHEMA_CHECKSUM_MISMATCH")
            if migration["latest"] in {"intent", "rollback_intent"}:
                payload.update(
                    {
                        "state": "rollback_required"
                        if migration["latest"] == "rollback_intent"
                        else "migrating"
                    }
                )
                payload["reason_codes"].append("MIGRATION_RECEIPT_INCOMPLETE")
            elif not markers:
                payload["state"] = "legacy"
                payload["reason_codes"].append("LEGACY_SCHEMA")
            else:
                payload["state"] = "ready"
            if integrity != "ok" or foreign_keys:
                payload.update(
                    {"state": "corrupt", "reason_codes": [*payload["reason_codes"], "INTEGRITY_CHECK_FAILED"]}
                )
            if fts.get("synchronized") is False:
                payload["reason_codes"].append("FTS_OUT_OF_SYNC")
            if any(references.values()):
                payload["reason_codes"].append("REFERENCE_GAP")
            if max_bytes is not None and target.stat().st_size > max_bytes:
                payload["alerts"].append({"code": "DATABASE_SIZE_BUDGET_EXCEEDED", "limit": max_bytes})
            total_rows = sum(value for value in row_counts.values() if isinstance(value, int))
            if max_rows is not None and total_rows > max_rows:
                payload["alerts"].append(
                    {"code": "ROW_BUDGET_EXCEEDED", "limit": max_rows, "rows": total_rows}
                )
            if (
                pointer
                and pointer.get("valid")
                and pointer.get("writer_authority") not in {None, "mapper-store"}
            ):
                payload.update(
                    {
                        "state": "split_brain",
                        "reason_codes": [*payload["reason_codes"], "MULTIPLE_WRITER_AUTHORITIES"],
                    }
                )
            elif locks["migration"]["active"]:
                payload.update(
                    {
                        "state": "migrating",
                        "reason_codes": [*payload["reason_codes"], "MIGRATION_LOCK_ACTIVE"],
                    }
                )
            elif any(item.get("present") and item.get("stale") for item in locks.values()):
                payload.update({"state": "stale", "reason_codes": [*payload["reason_codes"], "STALE_LOCK"]})
    except (sqlite3.Error, OSError, DoctorError) as error:
        payload.update(
            {"state": "corrupt", "reason_codes": ["STORE_OPEN_FAILED"], "error_type": type(error).__name__}
        )
    after = set(target.parent.iterdir())
    if before != after:
        payload["reason_codes"].append("UNEXPECTED_SIDE_EFFECT")
        payload["state"] = "corrupt"
    payload["reason_codes"] = sorted(set(payload["reason_codes"]))
    return redact(payload)


def capacity_report(
    path: str | Path, *, max_bytes: int | None = None, max_rows: int | None = None
) -> dict[str, Any]:
    report = doctor_store(path, max_bytes=max_bytes, max_rows=max_rows)
    return {
        "schema": CAPACITY_SCHEMA,
        "path": report["path"],
        "state": report["state"],
        "database_bytes": report.get("counts", {}).get("database_bytes"),
        "wal_bytes": report.get("counts", {}).get("wal_bytes"),
        "rows": sum(v for v in report.get("counts", {}).get("rows", {}).values() if isinstance(v, int)),
        "alerts": report.get("alerts", []),
        "budgets": {"max_bytes": max_bytes, "max_rows": max_rows},
        "reason_codes": report["reason_codes"],
    }


def _verify_manifest(manifest: Mapping[str, Any], database: Path | None = None) -> None:
    if manifest.get("schema") != "simplicio.mapper-store.backup/v1":
        raise DoctorError("BACKUP_MANIFEST_INVALID")
    backup_path = Path(str(manifest.get("backup_path", ""))).expanduser()
    if not backup_path.is_file() or _sha_bytes(backup_path.read_bytes()) != manifest.get("sha256"):
        raise DoctorError("BACKUP_HASH_MISMATCH")
    if (
        database is not None
        and manifest.get("source_path")
        and Path(str(manifest["source_path"])).absolute() != database.absolute()
    ):
        raise DoctorError("BACKUP_SOURCE_MISMATCH")


def backup_store(path: str | Path, destination: str | Path) -> dict[str, Any]:
    """Create a verified, consistent SQLite backup and immutable manifest."""

    source = _safe_path(path)
    target = _safe_path(destination)
    if target.exists() or target.is_symlink():
        raise DoctorError("BACKUP_DESTINATION_EXISTS", str(target))
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(target.parent, stat.S_IRWXU)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with (
            closing(_open_readonly(source)) as source_connection,
            closing(sqlite3.connect(temporary)) as destination_connection,
        ):
            source_connection.backup(destination_connection)
            destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            integrity = str(destination_connection.execute("PRAGMA integrity_check").fetchone()[0]).lower()
            if integrity != "ok":
                raise DoctorError("BACKUP_INTEGRITY_FAILED")
        if target.exists():
            raise DoctorError("BACKUP_DESTINATION_EXISTS", str(target))
        os.link(temporary, target)
        temporary.unlink()
        temporary = None
        digest = _sha_bytes(target.read_bytes())
        manifest = {
            "schema": "simplicio.mapper-store.backup/v1",
            "version": 1,
            "source_path": str(source),
            "backup_path": str(target),
            "sha256": digest,
            "size": target.stat().st_size,
            "schema_checksum": doctor_store(target)["checks"].get("schema_checksum"),
            "created_at": _now(),
            "permissions": oct(stat.S_IMODE(target.stat().st_mode)),
        }
        manifest_path = target.with_name(target.name + ".manifest.json")
        if manifest_path.exists():
            raise DoctorError("BACKUP_MANIFEST_EXISTS")
        manifest_path.write_text(_canonical(redact(manifest)) + "\n", encoding="utf-8")
        os.chmod(manifest_path, stat.S_IRUSR | stat.S_IWUSR)
        return {"schema": "simplicio.mapper-store.backup/v1", "status": "backed_up", "manifest": manifest}
    except Exception:
        if target.exists() and not target.is_symlink():
            target.unlink()
        raise
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def restore_store(
    backup: str | Path,
    destination: str | Path,
    *,
    manifest: Mapping[str, Any] | str | Path | None = None,
    allow_overwrite: bool = False,
    authorization: str | None = None,
) -> dict[str, Any]:
    """Restore only to a new destination unless an explicit token authorizes overwrite."""

    source = _safe_path(backup)
    target = _safe_path(destination)
    if manifest is None:
        manifest_path = source.with_name(source.name + ".manifest.json")
        if not manifest_path.is_file():
            raise DoctorError("BACKUP_MANIFEST_REQUIRED")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    checked = dict(manifest)
    checked["backup_path"] = str(source)
    _verify_manifest(checked)
    if target.exists() and (not allow_overwrite or authorization != "mapper-store-restore-overwrite/v1"):
        raise DoctorError("RESTORE_DESTINATION_EXISTS")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = target.with_name(f".{target.name}.restore.tmp")
    if temporary.exists():
        raise DoctorError("RESTORE_TEMP_EXISTS")
    try:
        with (
            closing(sqlite3.connect(source)) as source_connection,
            closing(sqlite3.connect(temporary)) as destination_connection,
        ):
            source_connection.backup(destination_connection)
            integrity = str(destination_connection.execute("PRAGMA integrity_check").fetchone()[0]).lower()
            if integrity != "ok":
                raise DoctorError("RESTORE_INTEGRITY_FAILED")
        if target.exists() and allow_overwrite:
            target.unlink()
        os.replace(temporary, target)
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        return {
            "schema": "simplicio.mapper-store.restore/v1",
            "status": "restored",
            "path": str(target),
            "sha256": _sha_bytes(target.read_bytes()),
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def repair_store(
    path: str | Path,
    *,
    apply: bool = False,
    backup_manifest: Mapping[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Plan or apply only derived-index repair; authoritative rows are untouched."""

    target = _safe_path(path)
    report = doctor_store(target)
    actions: list[str] = []
    fts = report.get("checks", {}).get("fts", {})
    if fts.get("synchronized") is False:
        actions.append("rebuild_fts")
    references = report.get("checks", {}).get("references", {})
    if any(isinstance(value, int) and value > 0 for value in references.values()):
        actions.append("quarantine_reference_gaps")
    if not actions:
        return {"schema": REPAIR_SCHEMA, "status": "no_op", "apply": apply, "side_effects": False}
    if not apply:
        return {
            "schema": REPAIR_SCHEMA,
            "status": "planned",
            "apply": False,
            "side_effects": False,
            "actions": actions,
            "reason_codes": report["reason_codes"],
        }
    if backup_manifest is None:
        raise DoctorError("BACKUP_REQUIRED")
    if isinstance(backup_manifest, (str, Path)):
        checked = json.loads(Path(backup_manifest).read_text(encoding="utf-8"))
    else:
        checked = dict(backup_manifest)
    _verify_manifest(checked, target)
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS mapper_repair_quarantine ("
                "record_id TEXT PRIMARY KEY, category TEXT NOT NULL, stable_id TEXT NOT NULL, "
                "detail_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            connection.execute("DELETE FROM semantic_fts")
            connection.execute(
                "INSERT INTO semantic_fts(stable_id, chunk_id, content) "
                "SELECT stable_id, chunk_id, content FROM semantic_chunks WHERE tombstone=0"
            )
            if references.get("memory_without_semantic", 0):
                connection.execute(
                    "INSERT OR IGNORE INTO mapper_repair_quarantine(record_id, category, stable_id, detail_json, created_at) "
                    "SELECT 'memory_without_semantic:' || e.stable_id, 'memory_without_semantic', e.stable_id, '{\"authoritative\":true}', ? "
                    "FROM memory_entries e LEFT JOIN semantic_items i ON i.stable_id=e.stable_id "
                    "WHERE e.tombstone=0 AND i.stable_id IS NULL",
                    (_now(),),
                )
            if references.get("semantic_memory_without_entry", 0):
                connection.execute(
                    "INSERT OR IGNORE INTO mapper_repair_quarantine(record_id, category, stable_id, detail_json, created_at) "
                    "SELECT 'semantic_memory_without_entry:' || i.stable_id, 'semantic_memory_without_entry', i.stable_id, '{\"authoritative\":true}', ? "
                    "FROM semantic_items i LEFT JOIN memory_entries e ON e.stable_id=i.stable_id "
                    "WHERE i.kind='memory' AND i.tombstone=0 AND e.stable_id IS NULL",
                    (_now(),),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    verified = doctor_store(target)
    if verified["checks"].get("fts", {}).get("synchronized") is not True:
        raise DoctorError("REPAIR_VERIFICATION_FAILED")
    return {
        "schema": REPAIR_SCHEMA,
        "status": "repaired",
        "apply": True,
        "side_effects": True,
        "actions": actions,
        "post_check": {
            "fts": verified["checks"]["fts"],
            "references": verified["checks"].get("references", {}),
            "quarantine": True,
        },
    }


def secure_export(payload: Mapping[str, Any], destination: str | Path) -> dict[str, Any]:
    target = _safe_path(destination)
    if target.exists():
        raise DoctorError("EXPORT_DESTINATION_EXISTS")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    target.write_text(_canonical(redact(dict(payload))) + "\n", encoding="utf-8")
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    return {
        "schema": "simplicio.mapper-store.secure-export/v1",
        "path": str(target),
        "sha256": _sha_bytes(target.read_bytes()),
        "permissions": oct(stat.S_IMODE(target.stat().st_mode)),
    }


__all__ = [
    "CAPACITY_SCHEMA",
    "DOCTOR_SCHEMA",
    "DoctorError",
    "HEALTH_STATES",
    "REPAIR_SCHEMA",
    "backup_store",
    "capacity_report",
    "doctor_store",
    "redact",
    "repair_store",
    "restore_store",
    "secure_export",
]
