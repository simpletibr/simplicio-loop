"""Canonical schema registry and resumable SQLite migrations for MapperStore/v1."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .connection import StoreConnection, StoreError, WriterIdentity
from .locks import StoreFileLock, StoreLockError
from .paths import reject_network_path, reject_symlink_components
from .profiles import StoreProfile
from .transactions import transaction

SCHEMA_REGISTRY = "simplicio.mapper-store.schema-registry/v1"
MIGRATION_EVENT_SCHEMA = "simplicio.mapper-store.migration-event/v1"
REASON_INCOMPATIBLE_WRITER = "INCOMPATIBLE_WRITER"
REASON_CHECKSUM_DIVERGENCE = "CHECKSUM_DIVERGENCE"
REASON_AMBIGUOUS_MIGRATION = "AMBIGUOUS_MIGRATION"


class RegistryError(StoreError):
    """Base class for typed schema-registry failures."""


class RegistryChecksumError(RegistryError):
    """The local manifest or migration differs from its signed identity."""


class MigrationPreflightError(RegistryError):
    """The host cannot safely run the requested migration."""


class AmbiguousMigrationError(RegistryError):
    """A DDL boundary is neither verifiably complete nor safely unstarted."""


class IncompatibleWriterError(RegistryError):
    """A writer is newer than the reader contract allows."""


class MigrationFault(RegistryError):
    """A test or embedding hook intentionally stopped a migration boundary."""


def canonical_json(value: Any) -> str:
    """Return the cross-language canonical JSON representation."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fixture_path(relative: str) -> Path | None:
    path = Path(__file__).parents[1] / "contracts" / relative
    return path if path.is_file() else None


def _default_manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA_REGISTRY,
        "registry_version": 1,
        "manifest_id": "mapper-store-v1",
        "namespaces": {
            "semantic": {"current": 1, "minimum_reader": 1, "maximum_writer": 1},
            "operations": {"current": 1, "minimum_reader": 1, "maximum_writer": 1},
            "memory": {"current": 1, "minimum_reader": 1, "maximum_writer": 1},
            "catalog": {"current": 1, "minimum_reader": 1, "maximum_writer": 1},
        },
        "capabilities": ["sqlite", "wal", "fts5", "append-only-ledger", "verified-backup"],
        "legacy_policy": {"read": "allow-n-minus-2", "write": "current-only", "downgrade": "explicit-only"},
    }


DEFAULT_MANIFEST = _default_manifest()


@dataclass(frozen=True)
class MigrationSpec:
    """One explicit, forward migration with a bounded rollback class."""

    migration_id: str
    from_version: int
    to_version: int
    forward: tuple[str, ...]
    verification_query: str
    rollback_class: str = "none"
    rollback: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    destructive: bool = False
    checksum: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.migration_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "forward": list(self.forward),
            "verification_query": self.verification_query,
            "rollback_class": self.rollback_class,
            "rollback": list(self.rollback),
            "prerequisites": list(self.prerequisites),
            "destructive": self.destructive,
        }

    @property
    def identity(self) -> str:
        return self.checksum or sha256_json(self.payload())

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload(), "checksum": self.identity}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MigrationSpec:
        required = {"id", "from_version", "to_version", "forward", "verification_query", "checksum"}
        missing = required - value.keys()
        if missing:
            raise ValueError(f"migration missing fields: {sorted(missing)}")
        spec = cls(
            migration_id=str(value["id"]),
            from_version=int(value["from_version"]),
            to_version=int(value["to_version"]),
            forward=tuple(str(item) for item in value["forward"]),
            verification_query=str(value["verification_query"]),
            rollback_class=str(value.get("rollback_class", "none")),
            rollback=tuple(str(item) for item in value.get("rollback", [])),
            prerequisites=tuple(str(item) for item in value.get("prerequisites", [])),
            destructive=bool(value.get("destructive", False)),
            checksum=str(value.get("checksum", "")),
        )
        if spec.from_version >= spec.to_version or not spec.forward:
            raise ValueError("migration versions must increase and forward SQL cannot be empty")
        if spec.rollback_class not in {"none", "explicit", "restore-backup"}:
            raise ValueError(f"unsupported rollback class: {spec.rollback_class}")
        expected = sha256_json(spec.payload())
        if spec.checksum and spec.checksum != expected:
            raise RegistryChecksumError(f"migration checksum mismatch: {spec.migration_id}")
        return cls(**{**spec.__dict__, "checksum": expected})


def default_migrations() -> tuple[MigrationSpec, ...]:
    fixture = _fixture_path("mapper-store/v1/fixtures/migrations/catalog.json")
    if fixture:
        return tuple(
            MigrationSpec.from_dict(item) for item in json.loads(fixture.read_text(encoding="utf-8"))
        )
    return (
        MigrationSpec(
            migration_id="catalog-0001-base-ledger",
            from_version=0,
            to_version=1,
            forward=(
                "CREATE TABLE IF NOT EXISTS mapper_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE INDEX IF NOT EXISTS idx_mapper_metadata_key ON mapper_metadata(key)",
            ),
            verification_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='mapper_metadata'",
            rollback_class="explicit",
            rollback=("DROP TABLE IF EXISTS mapper_metadata",),
        ),
        MigrationSpec(
            migration_id="catalog-0002-memory-records",
            from_version=1,
            to_version=2,
            forward=(
                "CREATE TABLE IF NOT EXISTS memory_records (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
                "CREATE INDEX IF NOT EXISTS idx_memory_records_created_at ON memory_records(created_at)",
            ),
            verification_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memory_records'",
            rollback_class="explicit",
            rollback=("DROP TABLE IF EXISTS memory_records",),
            prerequisites=("catalog-0001-base-ledger",),
            destructive=True,
        ),
    )


def negotiate(
    *,
    reader_min: int,
    reader_max: int,
    writer_min: int,
    writer_max: int,
    reader_capabilities: set[str] | None = None,
    writer_capabilities: set[str] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Negotiate a version range and return a stable reason code on failure."""

    overlap_min = max(reader_min, writer_min)
    overlap_max = min(reader_max, writer_max)
    missing = sorted((writer_capabilities or set()) - (reader_capabilities or set()))
    compatible = overlap_min <= overlap_max and not missing
    result = {
        "schema": "simplicio.mapper-store.negotiation/v1",
        "compatible": compatible,
        "reader": {"minimum": reader_min, "maximum": reader_max},
        "writer": {"minimum": writer_min, "maximum": writer_max},
        "minimum_version": overlap_min,
        "maximum_version": overlap_max,
        "missing_capabilities": missing,
        "reason_code": None if compatible else REASON_INCOMPATIBLE_WRITER,
    }
    if not compatible and strict:
        raise IncompatibleWriterError(canonical_json(result))
    return result


@dataclass
class MigrationEngine:
    database: Path | str
    manifest: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_MANIFEST))
    migrations: tuple[MigrationSpec, ...] = field(default_factory=default_migrations)
    backup_dir: Path | str | None = None
    writer: WriterIdentity | None = None
    fault_hook: Callable[[str, MigrationSpec], None] | None = None
    min_free_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        self.database = Path(self.database).expanduser().absolute()
        self.manifest = json.loads(canonical_json(self.manifest))
        required_manifest = {
            "schema",
            "registry_version",
            "manifest_id",
            "namespaces",
            "capabilities",
            "legacy_policy",
        }
        if self.manifest.get("schema") != SCHEMA_REGISTRY or not required_manifest.issubset(self.manifest):
            raise ValueError("unsupported schema registry")
        if set(self.manifest["namespaces"]) != {"semantic", "operations", "memory", "catalog"}:
            raise ValueError("schema registry namespaces are incomplete")
        self.migrations = tuple(MigrationSpec.from_dict(item.as_dict()) for item in self.migrations)
        self._by_id = {item.migration_id: item for item in self.migrations}
        if len(self._by_id) != len(self.migrations):
            raise ValueError("migration ids must be unique")
        self.writer = self.writer or WriterIdentity.create("simplicio_mapper.schema_registry")

    @property
    def manifest_hash(self) -> str:
        return sha256_json(self.manifest)

    @property
    def lock_path(self) -> Path:
        return self.database.with_name(self.database.name + ".migration.lock")

    def _open(self) -> StoreConnection:
        return StoreConnection.open(self.database, StoreProfile.migration(), writer_identity=self.writer)

    def current_version(self) -> int:
        reject_network_path(self.database)
        reject_symlink_components(self.database)
        if not self.database.is_file():
            return 0
        try:
            with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
                return int(store.execute("PRAGMA user_version").fetchone()[0])
        except (OSError, sqlite3.Error, StoreError) as error:
            raise RegistryError(f"cannot read schema version: {error}") from error

    def _ensure_metadata(self, store: StoreConnection) -> None:
        with transaction(store, "EXCLUSIVE") as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS mapper_schema_registry (id INTEGER PRIMARY KEY CHECK(id=1), manifest_hash TEXT NOT NULL, registry_version INTEGER NOT NULL)"
            )
            tx.execute(
                "CREATE TABLE IF NOT EXISTS migration_ledger (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_schema TEXT NOT NULL, migration_id TEXT NOT NULL, checksum TEXT NOT NULL, event TEXT NOT NULL, from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)"
            )
            tx.execute(
                "CREATE TRIGGER IF NOT EXISTS migration_ledger_no_update BEFORE UPDATE ON migration_ledger BEGIN SELECT RAISE(ABORT, 'migration ledger is append-only'); END"
            )
            tx.execute(
                "CREATE TRIGGER IF NOT EXISTS migration_ledger_no_delete BEFORE DELETE ON migration_ledger BEGIN SELECT RAISE(ABORT, 'migration ledger is append-only'); END"
            )
            existing = tx.execute(
                "SELECT manifest_hash, registry_version FROM mapper_schema_registry WHERE id=1"
            ).fetchone()
            if existing is None:
                tx.execute(
                    "INSERT INTO mapper_schema_registry(id, manifest_hash, registry_version) VALUES (1, ?, ?)",
                    (self.manifest_hash, int(self.manifest["registry_version"])),
                )
            elif existing[0] != self.manifest_hash or int(existing[1]) != int(
                self.manifest["registry_version"]
            ):
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)

    def _events(self, store: StoreConnection, migration_id: str | None = None) -> list[dict[str, Any]]:
        try:
            query = "SELECT event_schema, seq, migration_id, checksum, event, from_version, to_version, actor, occurred_at, payload, previous_hash, event_hash FROM migration_ledger"
            params: tuple[Any, ...] = ()
            query += " ORDER BY seq"
            rows = store.execute(query, params).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return []
            raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE) from error
        try:
            events = [
                {
                    "event_schema": row[0],
                    "seq": row[1],
                    "migration_id": row[2],
                    "checksum": row[3],
                    "event": row[4],
                    "from_version": row[5],
                    "to_version": row[6],
                    "actor": row[7],
                    "occurred_at": row[8],
                    "payload": json.loads(row[9]),
                    "previous_hash": row[10],
                    "event_hash": row[11],
                }
                for row in rows
            ]
        except (TypeError, ValueError, sqlite3.Error) as error:
            raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE) from error
        previous_hash = ""
        for event in events:
            if (
                event["event_schema"] != MIGRATION_EVENT_SCHEMA
                or event["previous_hash"] != previous_hash
                or event["event_hash"]
                != sha256_json(
                    {
                        "event_schema": event["event_schema"],
                        "migration_id": event["migration_id"],
                        "checksum": event["checksum"],
                        "event": event["event"],
                        "from_version": event["from_version"],
                        "to_version": event["to_version"],
                        "actor": event["actor"],
                        "occurred_at": event["occurred_at"],
                        "payload": event["payload"],
                        "previous_hash": event["previous_hash"],
                    }
                )
            ):
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            previous_hash = event["event_hash"]
        return [event for event in events if migration_id is None or event["migration_id"] == migration_id]

    def _insert_event(self, tx: Any, spec: MigrationSpec, event: str, payload: dict[str, Any]) -> None:
        occurred_at = _utc_now()
        previous = tx.execute("SELECT event_hash FROM migration_ledger ORDER BY seq DESC LIMIT 1").fetchone()
        previous_hash = str(previous[0]) if previous else ""
        material = {
            "event_schema": MIGRATION_EVENT_SCHEMA,
            "migration_id": spec.migration_id,
            "checksum": spec.identity,
            "event": event,
            "from_version": spec.from_version,
            "to_version": spec.to_version,
            "actor": self.writer.component,
            "occurred_at": occurred_at,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        tx.execute(
            "INSERT INTO migration_ledger(event_schema, migration_id, checksum, event, from_version, to_version, actor, occurred_at, payload, previous_hash, event_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                MIGRATION_EVENT_SCHEMA,
                spec.migration_id,
                spec.identity,
                event,
                spec.from_version,
                spec.to_version,
                self.writer.component,
                occurred_at,
                canonical_json(payload),
                previous_hash,
                sha256_json(material),
            ),
        )

    def _append_event(self, spec: MigrationSpec, event: str, payload: dict[str, Any]) -> None:
        with self._open() as store:
            self._ensure_metadata(store)
            with transaction(store, "EXCLUSIVE") as tx:
                self._insert_event(tx, spec, event, payload)

    def _validate_ledger(self) -> None:
        if not self.database.is_file():
            return
        with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
            current = self.current_version()
            tables = {
                row[0]
                for row in store.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('mapper_schema_registry', 'migration_ledger')"
                ).fetchall()
            }
            registry_columns = {
                row[1] for row in store.execute("PRAGMA table_info(mapper_schema_registry)").fetchall()
            }
            ledger_columns = {
                row[1] for row in store.execute("PRAGMA table_info(migration_ledger)").fetchall()
            }
            expected_registry = {"id", "manifest_hash", "registry_version"}
            expected_ledger = {
                "seq",
                "event_schema",
                "migration_id",
                "checksum",
                "event",
                "from_version",
                "to_version",
                "actor",
                "occurred_at",
                "payload",
                "previous_hash",
                "event_hash",
            }
            if "mapper_schema_registry" in tables and registry_columns != expected_registry:
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            if "migration_ledger" in tables and ledger_columns != expected_ledger:
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            if current == 0 and tables and tables != {"mapper_schema_registry", "migration_ledger"}:
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            if current > 0 and tables and tables != {"mapper_schema_registry", "migration_ledger"}:
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            trigger_definitions = {
                row[0]: " ".join(str(row[1] or "").lower().split())
                for row in store.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name IN ('migration_ledger_no_update', 'migration_ledger_no_delete')"
                ).fetchall()
            }
            expected_triggers = {
                "migration_ledger_no_update": "create trigger migration_ledger_no_update before update on migration_ledger begin select raise(abort, 'migration ledger is append-only'); end",
                "migration_ledger_no_delete": "create trigger migration_ledger_no_delete before delete on migration_ledger begin select raise(abort, 'migration ledger is append-only'); end",
            }
            if (
                tables == {"mapper_schema_registry", "migration_ledger"}
                and trigger_definitions != expected_triggers
            ):
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            if "mapper_schema_registry" in tables:
                try:
                    manifest = store.execute(
                        "SELECT manifest_hash, registry_version FROM mapper_schema_registry WHERE id=1"
                    ).fetchone()
                except sqlite3.OperationalError as error:
                    raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE) from error
            else:
                manifest = None
            if manifest is None and tables:
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            if manifest is not None and (
                manifest[0] != self.manifest_hash
                or int(manifest[1]) != int(self.manifest["registry_version"])
            ):
                raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
            for event in self._events(store):
                spec = self._by_id.get(event["migration_id"])
                if spec is None or event["checksum"] != spec.identity:
                    raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)

    def _assert_ready_state(self, current: int) -> None:
        if current == 0:
            if self.database.is_file():
                with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
                    row = store.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table', 'index') AND name IN ('mapper_metadata', 'memory_records')"
                    ).fetchone()
                if row and row[0]:
                    raise RegistryError("schema objects exist while user_version is zero")
            return
        with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
            events = self._events(store)
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            latest[event["migration_id"]] = event
        for spec in self.migrations:
            if spec.to_version <= current:
                event = latest.get(spec.migration_id)
                if event is None or event["event"] != "receipt":
                    raise RegistryError(f"migration receipt missing: {spec.migration_id}")
                if not self._verify(spec):
                    raise RegistryError(f"migration verification failed: {spec.migration_id}")

    def preflight(self, *, required_capabilities: set[str] | None = None) -> dict[str, Any]:
        try:
            reject_network_path(self.database)
            reject_symlink_components(self.database)
        except Exception as error:
            raise MigrationPreflightError(f"unsafe migration path: {self.database}") from error
        parent = self.database.parent
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        usage = shutil.disk_usage(parent)
        sqlite_ok = sqlite3.sqlite_version_info >= (3, 35, 0)
        connection = sqlite3.connect(":memory:")
        try:
            compile_options = {str(row[0]).upper() for row in connection.execute("PRAGMA compile_options")}
        finally:
            connection.close()
        fts5 = "ENABLE_FTS5" in compile_options
        sqlite_vec = any("SQLITE_VEC" in item or "VECTOR" in item for item in compile_options)
        capabilities = {
            "sqlite",
            "wal" if sqlite_ok else "",
            "fts5" if fts5 else "",
            "sqlite-vec" if sqlite_vec else "",
        } - {""}
        missing = sorted((required_capabilities or set()) - capabilities)
        report = {
            "schema": "simplicio.mapper-store.preflight/v1",
            "database": str(self.database),
            "permissions": {"parent_exists": parent.is_dir(), "parent_writable": os.access(parent, os.W_OK)},
            "disk": {
                "free_bytes": usage.free,
                "required_bytes": self.min_free_bytes,
                "sufficient": usage.free >= self.min_free_bytes,
            },
            "sqlite": {"version": sqlite3.sqlite_version, "minimum": "3.35.0", "supported": sqlite_ok},
            "capabilities": {name: name in capabilities for name in ("sqlite", "wal", "fts5", "sqlite-vec")},
            "missing_capabilities": missing,
            "lock": self._lock_snapshot(),
            "ok": bool(
                os.access(parent, os.W_OK) and usage.free >= self.min_free_bytes and sqlite_ok and not missing
            ),
        }
        if not report["ok"]:
            raise MigrationPreflightError(canonical_json(report))
        return report

    def _verify(self, spec: MigrationSpec) -> bool:
        with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
            row = store.execute(spec.verification_query).fetchone()
            return bool(row and row[0])

    def _backup(self, spec: MigrationSpec) -> dict[str, Any]:
        directory = Path(self.backup_dir) if self.backup_dir else self.database.parent / "backups"
        reject_network_path(self.database)
        reject_symlink_components(self.database)
        reject_network_path(directory)
        reject_symlink_components(directory)
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        backup_path = (
            directory / f"{self.database.name}.{spec.from_version}-{spec.to_version}.{uuid4().hex}.sqlite"
        )
        if backup_path.exists() or backup_path.is_symlink():
            raise RegistryError(f"backup destination already exists: {backup_path}")
        backup_path.touch(mode=0o600, exist_ok=False)
        backup_path.chmod(0o600)
        source = sqlite3.connect(self.database)
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()
        with sqlite3.connect(backup_path) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0]).lower()
        if integrity != "ok":
            raise RegistryError(f"backup integrity check failed: {backup_path}")
        digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        receipt = {"path": str(backup_path), "sha256": digest, "size": backup_path.stat().st_size}
        manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
        manifest_path.write_text(
            canonical_json({"schema": "simplicio.mapper-store.backup/v1", **receipt}) + "\n", encoding="utf-8"
        )
        manifest_path.chmod(0o600)
        return {**receipt, "manifest": str(manifest_path)}

    def _verified_backup_path(self, receipt: dict[str, Any] | None) -> Path:
        if not receipt or not isinstance(receipt.get("path"), str):
            raise RegistryError("restore-backup requires a verified backup receipt")
        path = Path(receipt["path"]).expanduser().absolute()
        reject_network_path(path)
        reject_symlink_components(path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get("sha256"):
            raise RegistryChecksumError(REASON_CHECKSUM_DIVERGENCE)
        return path

    def _fault(self, stage: str, spec: MigrationSpec) -> None:
        if self.fault_hook:
            self.fault_hook(stage, spec)

    def _lock_snapshot(self) -> dict[str, Any]:
        if not self.lock_path.exists():
            return {"path": str(self.lock_path), "owner": None, "stale": False}
        try:
            owner = json.loads(self.lock_path.read_text(encoding="utf-8"))
            pid = int(owner.get("pid", 0))
            try:
                os.kill(pid, 0)
                stale = False
            except (OSError, ValueError):
                stale = True
            return {"path": str(self.lock_path), "owner": owner, "stale": stale}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {"path": str(self.lock_path), "owner": None, "stale": True}

    def plan(self, target_version: int | None = None) -> dict[str, Any]:
        current = self.current_version()
        self._validate_ledger()
        target = (
            target_version
            if target_version is not None
            else max((item.to_version for item in self.migrations), default=current)
        )
        if target < 0:
            raise ValueError("target version must be non-negative")
        steps = [item.as_dict() for item in self.migrations if current <= item.from_version < target]
        return {
            "schema": "simplicio.mapper-store.migration-plan/v1",
            "database": str(self.database),
            "manifest_hash": self.manifest_hash,
            "current_version": current,
            "target_version": target,
            "steps": steps,
            "blocked": current > target
            or any(item["from_version"] != current + index for index, item in enumerate(steps)),
        }

    def status(self) -> dict[str, Any]:
        current = self.current_version()
        self._validate_ledger()
        events: list[dict[str, Any]] = []
        if self.database.is_file():
            with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
                events = self._events(store)
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            latest[event["migration_id"]] = event
        return {
            "schema": "simplicio.mapper-store.migration-status/v1",
            "database": str(self.database),
            "manifest_hash": self.manifest_hash,
            "current_version": current,
            "latest": latest,
            "ledger_events": len(events),
            "lock": self._lock_snapshot(),
        }

    def apply(
        self,
        target_version: int | None = None,
        *,
        required_capabilities: set[str] | None = None,
        reader_min: int = 1,
        reader_max: int = 2,
        writer_min: int = 1,
        writer_max: int = 2,
        reader_capabilities: set[str] | None = None,
        writer_capabilities: set[str] | None = None,
    ) -> dict[str, Any]:
        target = (
            target_version if target_version is not None else max(item.to_version for item in self.migrations)
        )
        if target < 0:
            raise ValueError("target version must be non-negative")
        if self.current_version() > target:
            raise RegistryError(
                f"database schema version {self.current_version()} is newer than target {target}"
            )
        negotiation = negotiate(
            reader_min=reader_min,
            reader_max=reader_max,
            writer_min=writer_min,
            writer_max=writer_max,
            reader_capabilities=reader_capabilities,
            writer_capabilities=writer_capabilities,
        )
        if not negotiation["minimum_version"] <= target <= negotiation["maximum_version"]:
            raise IncompatibleWriterError(
                canonical_json(
                    {
                        **negotiation,
                        "compatible": False,
                        "reason_code": REASON_INCOMPATIBLE_WRITER,
                        "target_version": target,
                    }
                )
            )
        planned = self.current_version()
        while planned < target:
            planned_spec = next((item for item in self.migrations if item.from_version == planned), None)
            if planned_spec is None:
                raise RegistryError(f"no migration from schema version {planned}")
            if (
                planned_spec.to_version <= planned
                or planned_spec.to_version > target
                or not negotiation["minimum_version"]
                <= planned_spec.to_version
                <= negotiation["maximum_version"]
            ):
                raise IncompatibleWriterError(
                    canonical_json(
                        {
                            **negotiation,
                            "compatible": False,
                            "reason_code": REASON_INCOMPATIBLE_WRITER,
                            "target_version": planned_spec.to_version,
                        }
                    )
                )
            planned = planned_spec.to_version
        self.preflight(required_capabilities=required_capabilities)
        owner = f"{self.writer.component}:{self.writer.instance_id}"
        try:
            with StoreFileLock(self.lock_path, owner=owner):
                self._validate_ledger()
                with self._open() as store:
                    self._ensure_metadata(store)
                self._validate_ledger()
                applied: list[str] = []
                while True:
                    current = self.current_version()
                    with StoreConnection.open(
                        self.database, StoreProfile.read_only(), immutable=False
                    ) as recovery_store:
                        recovery_events = self._events(recovery_store)
                    for candidate in self.migrations:
                        candidate_events = [
                            event
                            for event in recovery_events
                            if event["migration_id"] == candidate.migration_id
                        ]
                        latest_candidate = candidate_events[-1] if candidate_events else None
                        if latest_candidate and latest_candidate["event"] == "rollback_intent":
                            if current == candidate.from_version:
                                had_receipt = any(
                                    event["event"] == "receipt" for event in candidate_events[:-1]
                                )
                                if not had_receipt:
                                    raise AmbiguousMigrationError(REASON_AMBIGUOUS_MIGRATION)
                                if self._verify(candidate):
                                    raise AmbiguousMigrationError(REASON_AMBIGUOUS_MIGRATION)
                                self._append_event(
                                    candidate,
                                    "rollback",
                                    {
                                        "result": "recovered",
                                        "backup": latest_candidate["payload"].get("backup"),
                                    },
                                )
                            elif current != candidate.to_version:
                                raise AmbiguousMigrationError(REASON_AMBIGUOUS_MIGRATION)
                            else:
                                payload = latest_candidate["payload"]
                                with self._open() as store, transaction(store, "EXCLUSIVE") as tx:
                                    for statement in candidate.rollback:
                                        tx.execute(statement)
                                    tx.execute(f"PRAGMA user_version = {candidate.from_version}")
                                    self._insert_event(
                                        tx,
                                        candidate,
                                        "rollback",
                                        {"result": "recovered", "backup": payload.get("backup")},
                                    )
                        elif any(event["event"] == "ddl" for event in candidate_events) and not any(
                            event["event"] == "receipt" for event in candidate_events
                        ):
                            raise AmbiguousMigrationError(REASON_AMBIGUOUS_MIGRATION)
                    current = self.current_version()
                    self._assert_ready_state(current)
                    if self.current_version() >= target:
                        self._assert_ready_state(self.current_version())
                        return {
                            **self.status(),
                            "status": "ready",
                            "applied": applied,
                            "negotiation": negotiation,
                        }
                    spec = next((item for item in self.migrations if item.from_version == current), None)
                    if spec is None:
                        raise RegistryError(f"no migration from schema version {current}")
                    if (
                        spec.to_version > target
                        or not negotiation["minimum_version"]
                        <= spec.to_version
                        <= negotiation["maximum_version"]
                    ):
                        raise IncompatibleWriterError(
                            canonical_json(
                                {
                                    **negotiation,
                                    "compatible": False,
                                    "reason_code": REASON_INCOMPATIBLE_WRITER,
                                    "target_version": spec.to_version,
                                }
                            )
                        )
                    with StoreConnection.open(
                        self.database, StoreProfile.read_only(), immutable=False
                    ) as read_store:
                        events = self._events(read_store, spec.migration_id)
                        all_events = self._events(read_store)
                    latest_by_id: dict[str, dict[str, Any]] = {}
                    for event in all_events:
                        latest_by_id[event["migration_id"]] = event
                    receipts = {
                        migration_id
                        for migration_id, event in latest_by_id.items()
                        if event["event"] == "receipt"
                    }
                    missing_prerequisites = sorted(set(spec.prerequisites) - receipts)
                    if missing_prerequisites:
                        raise RegistryError(f"prerequisites not applied: {', '.join(missing_prerequisites)}")
                    if events and events[-1]["event"] == "receipt":
                        if current < spec.to_version:
                            raise RegistryError(
                                f"ledger receipt is ahead of schema version: {spec.migration_id}"
                            )
                        applied.append(spec.migration_id)
                        continue
                    backup = self._backup(spec) if spec.destructive else None
                    self._append_event(spec, "intent", {"result": "prepared", "backup": backup})
                    self._fault("after_intent", spec)
                    with self._open() as store, transaction(store, "EXCLUSIVE") as tx:
                        for statement in spec.forward:
                            tx.execute(statement)
                        tx.execute(f"PRAGMA user_version = {spec.to_version}")
                        verified = tx.execute(spec.verification_query).fetchone()
                        if not verified or not verified[0]:
                            raise AmbiguousMigrationError(REASON_AMBIGUOUS_MIGRATION)
                        self._insert_event(tx, spec, "ddl", {"result": "committed", "backup": backup})
                        self._insert_event(
                            tx,
                            spec,
                            "receipt",
                            {"result": "verified", "verified": True, "backup": backup},
                        )
                    self._fault("after_ddl", spec)
                    self._fault("after_receipt", spec)
                    applied.append(spec.migration_id)
                return {
                    **self.status(),
                    "status": "ready",
                    "applied": applied,
                    "negotiation": negotiation,
                }
        except StoreLockError as error:
            raise MigrationPreflightError(f"migration lock unavailable: {self.lock_path}") from error

    def verify(self) -> dict[str, Any]:
        current = self.current_version()
        checks: list[dict[str, Any]] = []
        ledger_error: str | None = None
        try:
            self._validate_ledger()
            self._assert_ready_state(current)
        except RegistryError as error:
            ledger_error = str(error)
        for spec in self.migrations:
            if current >= spec.to_version:
                try:
                    valid = self._verify(spec)
                except (OSError, sqlite3.Error, StoreError) as error:
                    checks.append({"migration_id": spec.migration_id, "valid": False, "error": str(error)})
                    continue
                checks.append({"migration_id": spec.migration_id, "valid": valid, "checksum": spec.identity})
        valid = (
            ledger_error is None
            and current <= max((item.to_version for item in self.migrations), default=current)
            and all(item["valid"] for item in checks)
        )
        return {
            "schema": "simplicio.mapper-store.migration-verify/v1",
            "database": str(self.database),
            "current_version": current,
            "valid": valid,
            "ledger_error": ledger_error,
            "checks": checks,
        }

    def rollback(
        self,
        *,
        reader_min: int = 1,
        reader_max: int = 2,
        writer_min: int = 1,
        writer_max: int = 2,
        reader_capabilities: set[str] | None = None,
        writer_capabilities: set[str] | None = None,
    ) -> dict[str, Any]:
        negotiation = negotiate(
            reader_min=reader_min,
            reader_max=reader_max,
            writer_min=writer_min,
            writer_max=writer_max,
            reader_capabilities=reader_capabilities,
            writer_capabilities=writer_capabilities,
        )
        current = self.current_version()
        candidates = [item for item in self.migrations if item.to_version == current]
        if not candidates:
            raise RegistryError(f"no migration to rollback from schema version {current}")
        spec = candidates[0]
        if spec.rollback_class == "none" or not spec.rollback:
            if spec.rollback_class != "restore-backup":
                raise RegistryError(f"rollback is not supported for {spec.migration_id}")
        if not negotiation["minimum_version"] <= spec.from_version <= negotiation["maximum_version"]:
            raise IncompatibleWriterError(
                canonical_json(
                    {
                        **negotiation,
                        "compatible": False,
                        "reason_code": REASON_INCOMPATIBLE_WRITER,
                        "target_version": spec.from_version,
                    }
                )
            )
        self._validate_ledger()
        self._assert_ready_state(current)
        owner = f"{self.writer.component}:{self.writer.instance_id}"
        with StoreFileLock(self.lock_path, owner=owner):
            backup = self._backup(spec)
            if spec.rollback_class == "restore-backup":
                with StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False) as store:
                    events = self._events(store, spec.migration_id)
                restore_receipt = next(
                    (
                        event["payload"].get("backup")
                        for event in reversed(events)
                        if event["event"] == "receipt"
                    ),
                    None,
                )
                restore_path = self._verified_backup_path(restore_receipt)
                shutil.copy2(restore_path, self.database)
                with self._open() as store:
                    self._ensure_metadata(store)
                self._append_event(
                    spec,
                    "rollback_intent",
                    {"result": "prepared", "backup": backup, "restore_backup": restore_receipt},
                )
                with self._open() as store, transaction(store, "EXCLUSIVE") as tx:
                    tx.execute(f"PRAGMA user_version = {spec.from_version}")
                    self._insert_event(
                        tx,
                        spec,
                        "rollback",
                        {"result": "rolled_back", "rollback_class": spec.rollback_class, "backup": backup},
                    )
            else:
                self._append_event(spec, "rollback_intent", {"result": "prepared", "backup": backup})
                with self._open() as store, transaction(store, "EXCLUSIVE") as tx:
                    for statement in spec.rollback:
                        tx.execute(statement)
                    tx.execute(f"PRAGMA user_version = {spec.from_version}")
                    self._insert_event(
                        tx,
                        spec,
                        "rollback",
                        {"result": "rolled_back", "rollback_class": spec.rollback_class, "backup": backup},
                    )
        return {
            **self.status(),
            "status": "rolled_back",
            "rolled_back": spec.migration_id,
            "negotiation": negotiation,
        }


def registry_fixture() -> dict[str, Any]:
    """Return the JSON fixture shared by Python and Rust conformance tests."""

    manifest = DEFAULT_MANIFEST
    fixture = _fixture_path("mapper-store/v1/fixtures/registry/manifest.json")
    if fixture:
        manifest = json.loads(fixture.read_text(encoding="utf-8"))
    return {
        "manifest": manifest,
        "manifest_sha256": sha256_json(manifest),
        "schema": SCHEMA_REGISTRY,
    }
