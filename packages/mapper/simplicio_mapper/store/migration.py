"""Governed legacy-to-MapperStore migration coordinator (#479).

The coordinator is intentionally separate from the schema registry: registry
owns DDL migrations, while this module owns source discovery, verified backup,
data parity, shadow state, cutover pointer and explicit rollback receipts.
Read-only verbs never create a directory, database, WAL, backup or receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .locks import StoreFileLock
from .paths import reject_network_path, reject_symlink_components

MIGRATION_SCHEMA = "simplicio.mapper-store.migration/v1"
MIGRATION_EVENT_SCHEMA = "simplicio.mapper-store.migration-event/v1"
MIGRATION_DISCOVERY_SCHEMA = "simplicio.mapper-store.discovery/v1"
MIGRATION_PLAN_SCHEMA = "simplicio.mapper-store.migration-plan/v1"
MIGRATION_STATUS_SCHEMA = "simplicio.mapper-store.migration-status/v1"
STATES = (
    "DISCOVERED",
    "PLANNED",
    "BACKED_UP",
    "IMPORTED",
    "VALIDATED",
    "SHADOWING",
    "READY",
    "CUTOVER",
    "OBSERVED",
    "HELD",
    "ROLLBACK",
)
_INTERNAL_TABLES = {"sqlite_sequence"}


class MigrationCoordinatorError(RuntimeError):
    """Typed migration failure with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: object) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalize(value: object) -> object:
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    return value


def _table_rows(connection: sqlite3.Connection, table: str, columns: list[str]) -> list[list[object]]:
    query = f"SELECT {', '.join(_quote(column) for column in columns)} FROM {_quote(table)}"  # noqa: S608
    return [[_normalize(value) for value in row] for row in connection.execute(query).fetchall()]


def _inventory(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "tables": [], "size": None, "sha256": None}
    reject_network_path(path)
    reject_symlink_components(path)
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0]).lower()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables: list[dict[str, object]] = []
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall():
                columns = [
                    str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quote(name)})").fetchall()
                ]
                rows = _table_rows(connection, str(name), columns)
                tables.append(
                    {
                        "name": str(name),
                        "sql": sql,
                        "columns": columns,
                        "rows": len(rows),
                        "sha256": _sha(rows),
                    }
                )
    except (OSError, sqlite3.Error) as error:
        return {
            "path": str(path),
            "exists": True,
            "tables": [],
            "size": path.stat().st_size,
            "sha256": _sha(path.read_bytes()),
            "integrity": "error",
            "error": str(error),
        }
    return {
        "path": str(path),
        "exists": True,
        "size": path.stat().st_size,
        "sha256": _sha(path.read_bytes()),
        "integrity": integrity,
        "user_version": version,
        "tables": tables,
    }


def _writer_status(path: Path) -> dict[str, object]:
    lock = path.with_name(path.name + ".writer.lock")
    if not lock.exists():
        return {"active": False, "path": str(lock), "owner": None, "stale": False}
    try:
        owner = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(owner.get("pid", 0))
        try:
            os.kill(pid, 0)
            active = True
        except OSError:
            active = False
        return {"active": active, "path": str(lock), "owner": owner, "stale": not active}
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {"active": True, "path": str(lock), "owner": None, "stale": False, "error": str(error)}


class MigrationCoordinator:
    """Stateful migration coordinator with explicit effect receipts."""

    def __init__(
        self,
        destination: str | Path,
        sources: Mapping[str, str | Path] | None = None,
        *,
        state_path: str | Path | None = None,
        backup_dir: str | Path | None = None,
    ) -> None:
        self.destination = Path(destination).expanduser().absolute()
        reject_network_path(self.destination)
        reject_symlink_components(self.destination)
        self.sources = {
            str(name): Path(path).expanduser().absolute() for name, path in (sources or {}).items()
        }
        self.state_path = (
            Path(state_path or self.destination.with_suffix(self.destination.suffix + ".migration.jsonl"))
            .expanduser()
            .absolute()
        )
        self.backup_dir = (
            Path(backup_dir or self.destination.parent / "migration-backups").expanduser().absolute()
        )
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")

    def _events(self) -> list[dict[str, object]]:
        if not self.state_path.exists():
            return []
        previous = ""
        events: list[dict[str, object]] = []
        try:
            lines = self.state_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                event = json.loads(line)
                material = dict(event)
                event_hash = material.pop("event_hash", None)
                if (
                    event.get("event_schema") != MIGRATION_EVENT_SCHEMA
                    or event.get("previous_hash") != previous
                    or _sha(material) != event_hash
                ):
                    raise MigrationCoordinatorError("RECEIPT_TAMPERED")
                previous = str(event_hash)
                events.append(event)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
            if isinstance(error, MigrationCoordinatorError):
                raise
            raise MigrationCoordinatorError("RECEIPT_INVALID") from error
        return events

    def _append(self, event: str, payload: Mapping[str, object], *, state: str) -> dict[str, object]:
        self.state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with StoreFileLock(self.lock_path, owner=f"mapper-migration:{os.getpid()}", blocking=True):
            previous = self._events()
            event_data: dict[str, object] = {
                "event_schema": MIGRATION_EVENT_SCHEMA,
                "seq": len(previous) + 1,
                "event": event,
                "state": state,
                "occurred_at": _now(),
                "payload": dict(payload),
                "previous_hash": previous[-1]["event_hash"] if previous else "",
            }
            event_data["event_hash"] = _sha(event_data)
            with self.state_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical(event_data) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return event_data

    def _latest(self, event: str | None = None) -> dict[str, object] | None:
        events = self._events()
        selected = [item for item in events if event is None or item.get("event") == event]
        return selected[-1] if selected else None

    def discover(self, *, dry_run: bool = False) -> dict[str, object]:
        sources = []
        blockers: list[dict[str, object]] = []
        for name, path in sorted(self.sources.items()):
            inventory = _inventory(path)
            writers = _writer_status(path)
            item = {"name": name, "inventory": inventory, "writers": writers}
            sources.append(item)
            if not inventory.get("exists"):
                blockers.append({"code": "SOURCE_MISSING", "source": name})
            elif inventory.get("integrity") != "ok":
                blockers.append({"code": "SOURCE_CORRUPT", "source": name})
            if writers.get("active"):
                blockers.append(
                    {"code": "WRITER_ACTIVE", "source": name, "next_action": "quiesce legacy writer"}
                )
        payload: dict[str, object] = {
            "schema": MIGRATION_DISCOVERY_SCHEMA,
            "destination": str(self.destination),
            "sources": sources,
            "blockers": blockers,
            "ok": not blockers,
            "dry_run": dry_run,
        }
        if not dry_run:
            self._append("discover", payload, state="DISCOVERED" if not blockers else "HELD")
        return payload

    def plan(self, *, dry_run: bool = True) -> dict[str, object]:
        discovery = self.discover(dry_run=True)
        steps = [
            {"state": state, "effect": effect}
            for state, effect in (
                ("BACKED_UP", "verified source backup"),
                ("IMPORTED", "idempotent table import"),
                ("VALIDATED", "count/hash parity"),
                ("SHADOWING", "read-only shadow comparison"),
                ("CUTOVER", "atomic generation pointer"),
            )
        ]
        payload: dict[str, object] = {
            "schema": MIGRATION_PLAN_SCHEMA,
            "destination": str(self.destination),
            "sources": discovery["sources"],
            "steps": steps,
            "blockers": discovery["blockers"],
            "dry_run": dry_run,
            "side_effects": [],
        }
        if not dry_run:
            self._append("plan", payload, state="PLANNED")
        return payload

    def backup(self, *, dry_run: bool = False) -> dict[str, object]:
        discovery = self.discover(dry_run=True)
        if discovery["blockers"]:
            raise MigrationCoordinatorError("PREFLIGHT_BLOCKED", _canonical(discovery["blockers"]))
        if dry_run:
            return {
                "schema": MIGRATION_API_SCHEMA,
                "status": "would_backup",
                "dry_run": True,
                "sources": list(self.sources),
                "side_effects": [],
            }
        self.backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        receipts: list[dict[str, object]] = []
        if self.destination.is_file():
            destination_backup = self.backup_dir / f"destination.{uuid4().hex}.sqlite"
            with (
                sqlite3.connect(self.destination) as source,
                sqlite3.connect(destination_backup) as destination,
            ):
                source.backup(destination)
                destination.commit()
            receipts.append(
                {
                    "source": "__destination__",
                    "path": str(destination_backup),
                    "sha256": _sha(destination_backup.read_bytes()),
                    "size": destination_backup.stat().st_size,
                    "existed": True,
                }
            )
        else:
            receipts.append(
                {"source": "__destination__", "path": None, "sha256": None, "size": 0, "existed": False}
            )
        for name, path in sorted(self.sources.items()):
            backup = self.backup_dir / f"{name}.{uuid4().hex}.sqlite"
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
                destination.commit()
            with closing(sqlite3.connect(backup)) as checked:
                integrity = str(checked.execute("PRAGMA integrity_check").fetchone()[0]).lower()
            if integrity != "ok":
                raise MigrationCoordinatorError("BACKUP_INVALID", name)
            receipt = {
                "source": name,
                "path": str(backup),
                "sha256": _sha(backup.read_bytes()),
                "size": backup.stat().st_size,
            }
            receipts.append(receipt)
        payload = {"schema": MIGRATION_API_SCHEMA, "status": "backed_up", "receipts": receipts}
        self._append("backup", payload, state="BACKED_UP")
        return payload

    def _backup_for(self, name: str) -> dict[str, object]:
        for event in reversed(self._events()):
            if event.get("event") == "backup":
                for receipt in event.get("payload", {}).get("receipts", []):
                    if receipt.get("source") == name:
                        path = Path(str(receipt["path"]))
                        if path.is_file() and _sha(path.read_bytes()) == receipt.get("sha256"):
                            return receipt
        raise MigrationCoordinatorError("BACKUP_REQUIRED", name)

    def _copy_table(
        self, source: sqlite3.Connection, target: sqlite3.Connection, table: str, columns: list[str]
    ) -> int:
        rows = _table_rows(source, table, columns)
        placeholders = ",".join("?" for _ in columns)
        query = f"INSERT INTO {_quote(table)} ({', '.join(_quote(column) for column in columns)}) VALUES ({placeholders})"  # noqa: S608
        existing_query = (  # noqa: S608
            f"SELECT 1 FROM {_quote(table)} WHERE "  # noqa: S608
            + " AND ".join(f"{_quote(column)} IS ?" for column in columns)
            + " LIMIT 1"
        )
        inserted = 0
        for row in rows:
            if target.execute(existing_query, row).fetchone() is None:
                target.execute(query, row)
                inserted += 1
        return inserted

    def import_data(self, *, dry_run: bool = False) -> dict[str, object]:
        discovery = self.discover(dry_run=True)
        if discovery["blockers"]:
            raise MigrationCoordinatorError("PREFLIGHT_BLOCKED", _canonical(discovery["blockers"]))
        if dry_run:
            return {
                "schema": MIGRATION_API_SCHEMA,
                "status": "would_import",
                "dry_run": True,
                "side_effects": [],
            }
        for name in self.sources:
            self._backup_for(name)
        self.destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.destination.touch(mode=0o600, exist_ok=True)
        imported: list[dict[str, object]] = []
        with closing(sqlite3.connect(self.destination)) as target:
            target.execute("BEGIN IMMEDIATE")
            try:
                for name, path in sorted(self.sources.items()):
                    with closing(sqlite3.connect(path)) as source:
                        tables: list[dict[str, object]] = []
                        for table in _inventory(path)["tables"]:
                            table_name = str(table["name"])
                            columns = [str(column) for column in table["columns"]]
                            sql = str(table["sql"])
                            if "VIRTUAL TABLE" in sql.upper() or not columns:
                                continue
                            target_columns = [
                                str(column[1])
                                for column in target.execute(
                                    f"PRAGMA table_info({_quote(table_name)})"
                                ).fetchall()
                            ]
                            if target_columns and target_columns != columns:
                                raise MigrationCoordinatorError("SCHEMA_MISMATCH", table_name)
                            create_sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                            target.execute(create_sql)
                            count = self._copy_table(source, target, table_name, columns)
                            tables.append(
                                {
                                    "name": table_name,
                                    "rows": int(table["rows"]),
                                    "inserted": count,
                                    "sha256": table["sha256"],
                                }
                            )
                        imported.append({"source": name, "tables": tables})
                target.commit()
            except Exception:
                target.rollback()
                raise
        payload = {
            "schema": MIGRATION_API_SCHEMA,
            "status": "imported",
            "destination": str(self.destination),
            "sources": imported,
        }
        self._append("import", payload, state="IMPORTED")
        return payload

    def validate(self, *, record: bool = False) -> dict[str, object]:
        if not self.destination.is_file():
            return {
                "schema": MIGRATION_API_SCHEMA,
                "status": "blocked",
                "ok": False,
                "reason_code": "DESTINATION_MISSING",
                "parity": [],
            }
        destination = _inventory(self.destination)
        parity: list[dict[str, object]] = []
        for name, source in sorted(self.sources.items()):
            source_inventory = _inventory(source)
            destination_tables = {str(item["name"]): item for item in destination["tables"]}
            for table in source_inventory["tables"]:
                found = destination_tables.get(str(table["name"]))
                parity.append(
                    {
                        "source": name,
                        "table": table["name"],
                        "source_rows": table["rows"],
                        "destination_rows": found.get("rows") if found else None,
                        "source_sha256": table["sha256"],
                        "destination_sha256": found.get("sha256") if found else None,
                        "ok": bool(
                            found and found["rows"] == table["rows"] and found["sha256"] == table["sha256"]
                        ),
                    }
                )
        ok = bool(parity) and all(bool(item["ok"]) for item in parity)
        payload: dict[str, object] = {
            "schema": MIGRATION_API_SCHEMA,
            "status": "validated" if ok else "diverged",
            "ok": ok,
            "reason_code": None if ok else "SHADOW_DIVERGENCE",
            "parity": parity,
        }
        if record:
            self._append("validate", payload, state="VALIDATED" if ok else "HELD")
        return payload

    def shadow(self, *, dry_run: bool = False) -> dict[str, object]:
        report = self.validate(record=False)
        payload = {**report, "status": "would_shadow" if dry_run else "shadowed", "dry_run": dry_run}
        if not dry_run:
            self._append("shadow", payload, state="SHADOWING" if report["ok"] else "HELD")
        return payload

    def cutover(self, *, dry_run: bool = False) -> dict[str, object]:
        report = self.validate(record=False)
        if not report["ok"]:
            raise MigrationCoordinatorError("SHADOW_DIVERGENCE", _canonical(report))
        pointer = self.destination.with_name(self.destination.name + ".active.json")
        payload = {
            "schema": MIGRATION_API_SCHEMA,
            "status": "would_cutover" if dry_run else "cutover",
            "pointer": str(pointer),
            "writer_authority": "mapper-store",
            "legacy_policy": "read-only",
            "generation": _sha({"destination": str(self.destination), "parity": report["parity"]}),
        }
        if dry_run:
            payload["dry_run"] = True
            return payload
        self._append("cutover_intent", payload, state="READY")
        pointer.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=pointer.name + ".", dir=pointer.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_canonical(payload) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, pointer)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._append("cutover", payload, state="CUTOVER")
        return payload

    def rollback(self, *, dry_run: bool = False) -> dict[str, object]:
        latest = self._latest()
        if latest and latest.get("event") in {"cutover_intent", "rollback_intent"}:
            raise MigrationCoordinatorError("RECONCILIATION_REQUIRED", "post-effect state is unknown")
        if not latest or latest.get("state") != "CUTOVER":
            raise MigrationCoordinatorError("ROLLBACK_NOT_ALLOWED", "cutover receipt is not known")
        receipts = {
            str(item["source"]): item
            for event in self._events()
            if event.get("event") == "backup"
            for item in event.get("payload", {}).get("receipts", [])
        }
        if not receipts:
            raise MigrationCoordinatorError("BACKUP_REQUIRED")
        payload = {
            "schema": MIGRATION_API_SCHEMA,
            "status": "would_rollback" if dry_run else "rolled_back",
            "destination": str(self.destination),
            "backups": receipts,
        }
        if dry_run:
            payload["dry_run"] = True
            return payload
        self._append("rollback_intent", payload, state="CUTOVER")
        destination_receipt = receipts.get("__destination__")
        if not destination_receipt:
            raise MigrationCoordinatorError("BACKUP_REQUIRED", "destination")
        if destination_receipt.get("existed"):
            backup = Path(str(destination_receipt["path"]))
            if not backup.is_file() or _sha(backup.read_bytes()) != destination_receipt.get("sha256"):
                raise MigrationCoordinatorError("BACKUP_TAMPERED")
            temporary = self.destination.with_name(self.destination.name + ".rollback." + uuid4().hex)
            shutil.copy2(backup, temporary)
            os.replace(temporary, self.destination)
        elif self.destination.exists():
            self.destination.unlink()
        pointer = self.destination.with_name(self.destination.name + ".active.json")
        if pointer.exists():
            pointer.unlink()
        self._append("rollback", payload, state="ROLLBACK")
        return payload

    def status(self) -> dict[str, object]:
        events = self._events()
        latest = events[-1] if events else None
        return {
            "schema": MIGRATION_STATUS_SCHEMA,
            "destination": str(self.destination),
            "state": latest.get("state") if latest else None,
            "latest_event": latest.get("event") if latest else None,
            "events": len(events),
            "receipts_valid": True,
            "sources": {name: str(path) for name, path in sorted(self.sources.items())},
        }


MIGRATION_API_SCHEMA = "simplicio.mapper-store.migration-api/v1"

__all__ = [
    "MIGRATION_API_SCHEMA",
    "MIGRATION_DISCOVERY_SCHEMA",
    "MIGRATION_PLAN_SCHEMA",
    "MIGRATION_SCHEMA",
    "MIGRATION_STATUS_SCHEMA",
    "MigrationCoordinator",
    "MigrationCoordinatorError",
    "STATES",
]
