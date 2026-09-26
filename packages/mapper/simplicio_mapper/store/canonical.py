"""The canonical MapperStore facade.

Mapper is the only writer and schema owner for the memory and operations
databases.  Runtime, Fast, Loop and MCP integrations use
:class:`MapperStoreReader`; that class intentionally exposes no mutating API.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .connection import StoreError
from .contracts import (
    MAPPER_STORE_ABSORB_SCHEMA,
    MAPPER_STORE_API_SCHEMA,
    MAPPER_STORE_CAPABILITY_SCHEMA,
    MAPPER_STORE_CONFORMANCE_SCHEMA,
    MAPPER_STORE_READERS,
    MAPPER_STORE_RECORD_SCHEMA,
    MAPPER_STORE_SCHEMA,
    MAPPER_STORE_WRITER,
)
from .memory import (
    MEMORY_SCHEMA,
    MemoryStore,
    MemoryStoreError,
    _canonical,
    _redact,
    _redact_value,
    _sha_text,
)
from .operations import OPERATIONS_SCHEMA, OperationsStore, OperationsStoreError
from .paths import StorePathError, reject_network_path, reject_symlink_components
from .semantic import SEMANTIC_SCHEMA, SemanticStoreError

_CANONICAL_MEMORY = "memory.sqlite"
_CANONICAL_OPERATIONS = "operations.sqlite"
_RECORD_TYPES = frozenset(
    {
        "mapper-run",
        "mapper-change",
        "repository-generation",
        "precedent",
        "recipe",
        "decision",
        "execution-outcome",
    }
)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _path_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(path: str | os.PathLike[str]) -> Path:
    reject_network_path(path)
    reject_symlink_components(path)
    candidate = Path(path).expanduser().absolute()
    if candidate.is_symlink():
        raise StorePathError(f"symlink store path is not allowed: {candidate}")
    return candidate


class MapperStoreError(StoreError):
    """Typed canonical-facade failure."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


class MapperStore:
    """Canonical ownership boundary for Mapper memory and operations."""

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        data_dir: str | os.PathLike[str] | None = None,
        memory_database: str | os.PathLike[str] | None = None,
        operations_database: str | os.PathLike[str] | None = None,
        auto_create: bool = True,
        repository_id: str | None = None,
        generation: str | None = None,
    ) -> None:
        selected = data_dir or root
        if memory_database is not None:
            memory_path = _safe_path(memory_database)
            selected = selected or memory_path.parent
        elif selected is not None and Path(selected).suffix == ".sqlite":
            memory_path = _safe_path(selected)
            selected = memory_path.parent
        else:
            selected = _safe_path(selected or (Path.home() / ".simplicio-loop" / "data"))
            memory_path = selected / _CANONICAL_MEMORY
        self.root = _safe_path(selected)
        self.memory_database = memory_path
        self.operations_database = _safe_path(operations_database or self.root / _CANONICAL_OPERATIONS)
        self.auto_create = auto_create
        self.repository_id = repository_id
        self.generation = generation
        self.memory = MemoryStore(self.memory_database, auto_create=auto_create)
        self.operations = OperationsStore(self.operations_database, auto_create=auto_create)

    def initialize(self) -> dict[str, Any]:
        """Create both canonical stores through their owning domain APIs."""
        if not self.auto_create:
            raise MapperStoreError("STORE_READ_ONLY")
        self._preflight_existing()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        memory = self.memory.initialize()
        operations = self.operations.initialize()
        return {
            "schema": MAPPER_STORE_API_SCHEMA,
            "store_schema": MAPPER_STORE_SCHEMA,
            "status": "ready",
            "writer_authority": MAPPER_STORE_WRITER,
            "paths": self._paths(),
            "memory": memory,
            "operations": operations,
            "capabilities": self.capabilities(),
        }

    def _ensure_initialized(self) -> None:
        if not self.status()["valid"]:
            self.initialize()

    def _preflight_existing(self) -> None:
        for name, meta, schema, version in (
            ("memory", self._meta(self.memory_database, "memory_store_meta"), MEMORY_SCHEMA, "1"),
            ("semantic", self._meta(self.memory_database, "semantic_store_meta"), SEMANTIC_SCHEMA, "1"),
            ("operations", self._meta(self.operations_database, "operations_meta"), OPERATIONS_SCHEMA, "1"),
        ):
            expected = {
                "schema": schema,
                "store_schema": MAPPER_STORE_SCHEMA,
                "schema_version": version,
                "write_authority": MAPPER_STORE_WRITER,
            }
            if meta and any(meta.get(key) not in {None, value} for key, value in expected.items()):
                raise MapperStoreError("STORE_SCHEMA_DRIFT", name)

    def _require_ready(self) -> None:
        if not self.status()["valid"]:
            raise MapperStoreError("STORE_NOT_READY")

    def read_only(self) -> MapperStoreReader:
        return MapperStoreReader(
            self.root,
            memory_database=self.memory_database,
            operations_database=self.operations_database,
            repository_id=self.repository_id,
            generation=self.generation,
        )

    def _paths(self) -> dict[str, str]:
        return {"root": str(self.root), "memory": str(self.memory_database), "operations": str(self.operations_database)}

    def _meta(self, database: Path, table: str) -> dict[str, str]:
        if not database.is_file():
            return {}
        try:
            # ``immutable=1`` would ignore a live WAL and make status stale.
            with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
                query = (
                    "SELECT key,value FROM memory_store_meta"
                    if table == "memory_store_meta"
                    else "SELECT key,value FROM semantic_store_meta"
                    if table == "semantic_store_meta"
                    else "SELECT key,value FROM operations_meta"
                )
                return {str(row[0]): str(row[1]) for row in connection.execute(query)}
        except sqlite3.Error:
            return {}

    def status(self) -> dict[str, Any]:
        memory_meta = self._meta(self.memory_database, "memory_store_meta")
        semantic_meta = self._meta(self.memory_database, "semantic_store_meta")
        operations_meta = self._meta(self.operations_database, "operations_meta")
        memory_ready = self._meta_ready(
            memory_meta, MEMORY_SCHEMA, version="1"
        )
        semantic_ready = self._meta_ready(
            semantic_meta, SEMANTIC_SCHEMA, version="1"
        )
        operations_ready = self._meta_ready(
            operations_meta, OPERATIONS_SCHEMA, version="1"
        )
        return {
            "schema": MAPPER_STORE_API_SCHEMA,
            "store_schema": MAPPER_STORE_SCHEMA,
            "status": "ready" if memory_ready and semantic_ready and operations_ready else "not-ready",
            "valid": memory_ready and semantic_ready and operations_ready,
            "writer_authority": MAPPER_STORE_WRITER,
            "paths": self._paths(),
            "memory": {"exists": self.memory_database.is_file(), "schema": memory_meta.get("schema"), "version": memory_meta.get("schema_version")},
            "semantic": {"exists": self.memory_database.is_file(), "schema": semantic_meta.get("schema"), "version": semantic_meta.get("schema_version")},
            "operations": {"exists": self.operations_database.is_file(), "schema": operations_meta.get("schema"), "version": operations_meta.get("schema_version")},
            "legacy_read_only_markers": sorted(str(path) for path in self.root.glob("*.mapper-store-read-only.json")),
        }

    @staticmethod
    def _meta_ready(meta: Mapping[str, str], schema: str, *, version: str) -> bool:
        return bool(
            meta
            and meta.get("schema") == schema
            and meta.get("store_schema") == MAPPER_STORE_SCHEMA
            and meta.get("schema_version") == version
            and meta.get("write_authority") == MAPPER_STORE_WRITER
        )

    def capabilities(self) -> dict[str, Any]:
        semantic: dict[str, Any]
        ready = self.status()["valid"]
        if ready and self.memory_database.is_file():
            try:
                semantic = self.memory.semantic.capabilities().get("capabilities", {})
            except (StoreError, SemanticStoreError, sqlite3.Error):
                semantic = {"available": False, "reason": "STORE_NOT_READY"}
        else:
            semantic = {"available": False, "reason": "STORE_NOT_READY"}
        if ready:
            semantic = {"available": True, **semantic}
        return {
            "schema": MAPPER_STORE_CAPABILITY_SCHEMA,
            "store_schema": MAPPER_STORE_SCHEMA,
            "status": "ready" if ready else "not-ready",
            "available": ready,
            "writer_authority": MAPPER_STORE_WRITER,
            "readers": list(MAPPER_STORE_READERS),
            "clients": {reader: {"mode": "read-only", "ddl": False, "writes": False} for reader in MAPPER_STORE_READERS},
            "memory": {"canonical": True, "database": str(self.memory_database), "semantic_index_owner": "mapper"},
            "operations": {"canonical": True, "database": str(self.operations_database), "semantic_index_owner": None},
            "semantic": semantic,
            "migration": {"legacy_absorb": True, "idempotent": True, "deletes_legacy": False, "requires_explicit_cleanup": True},
            "precedents": {"stored_state": "candidate", "approval_by_storage": False, "applicability_evidence_required": True},
        }

    def conformance(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        status = self.status()
        for name, path in (("memory", self.memory_database), ("operations", self.operations_database)):
            checks.append({"name": f"{name}_canonical_path", "ok": path.name == f"{name}.sqlite"})
            checks.append({"name": f"{name}_exists", "ok": path.is_file()})
        checks.extend(
            [
                {"name": "memory_schema", "ok": status["memory"]["schema"] == MEMORY_SCHEMA},
                {"name": "semantic_schema", "ok": status["semantic"]["schema"] == SEMANTIC_SCHEMA},
                {"name": "operations_schema", "ok": status["operations"]["schema"] == OPERATIONS_SCHEMA},
                {"name": "writer_authority", "ok": status["writer_authority"] == MAPPER_STORE_WRITER},
                {"name": "canonical_markers", "ok": bool(status["valid"])},
            ]
        )
        if status["valid"]:
            try:
                validation = self.memory.validate()
                checks.append({"name": "memory_references", "ok": bool(validation["ok"]), "errors": validation["errors"]})
            except (StoreError, MemoryStoreError, sqlite3.Error) as error:
                checks.append({"name": "memory_references", "ok": False, "error": str(error)})
        ok = all(bool(item["ok"]) for item in checks)
        return {
            "schema": MAPPER_STORE_CONFORMANCE_SCHEMA,
            "store_schema": MAPPER_STORE_SCHEMA,
            "status": "conformant" if ok else "nonconformant",
            "ok": ok,
            "checks": checks,
            "capabilities": self.capabilities(),
        }

    @staticmethod
    def stable_id_for(record_type: str, repository_id: str | None, generation: str | None, identity: Any = None) -> str:
        if not isinstance(record_type, str) or not record_type.strip():
            raise MapperStoreError("RECORD_TYPE_INVALID")
        return f"mapper:{record_type}:{_digest({'repository_id': repository_id, 'generation': generation, 'identity': identity})[:40]}"

    def record(
        self,
        record_type: str,
        payload: Any,
        *,
        repository_id: str | None = None,
        generation: str | None = None,
        source: str = "mapper",
        producer: str = "mapper",
        version: str = "1",
        consent: Mapping[str, Any] | None = None,
        source_hash: str | None = None,
        source_path: str | None = None,
        stable_id: str | None = None,
        applicability_evidence: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
        provenance_extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(record_type, str) or not record_type.strip():
            raise MapperStoreError("RECORD_TYPE_INVALID")
        for value, name in ((source, "source"), (producer, "producer"), (version, "version")):
            if not isinstance(value, str) or not value.strip():
                raise MapperStoreError("PROVENANCE_INVALID", name)
        if record_type == "precedent" and not applicability_evidence:
            raise MapperStoreError("APPLICABILITY_EVIDENCE_REQUIRED")
        repository_id = repository_id if repository_id is not None else self.repository_id
        generation = generation if generation is not None else self.generation
        try:
            content = _canonical(payload) if not isinstance(payload, str) else payload
        except (TypeError, ValueError) as error:
            raise MapperStoreError("RECORD_PAYLOAD_INVALID") from error
        stable_id = stable_id or self.stable_id_for(record_type, repository_id, generation, payload)
        provenance = {
            **dict(_redact_value(dict(provenance_extra or {}))),
            "source": _redact(source),
            "producer": _redact(producer),
            "version": _redact(version),
            "repository_id": repository_id,
            "generation": generation,
            "source_path": source_path,
            "source_hash": source_hash or _sha_text(content),
            "record_schema": MAPPER_STORE_RECORD_SCHEMA,
        }
        metadata: dict[str, Any] = {
            "record_type": record_type,
            "payload": payload,
            "provenance": provenance,
            "repository_id": repository_id,
            "generation": generation,
            "producer": producer,
            "version": version,
        }
        if applicability_evidence is not None:
            metadata["applicability_evidence"] = dict(applicability_evidence)
            metadata["approval_status"] = "candidate"
        self._ensure_initialized()
        stored = self.memory.store(
            record_type,
            content,
            actor=producer,
            source=source,
            source_path=source_path,
            source_hash=source_hash or _sha_text(content),
            metadata=metadata,
            consent=consent,
            observed_at=observed_at,
            stable_id=stable_id,
        )
        safe_consent = dict(_redact_value(dict(consent or {})))
        return {"schema": MAPPER_STORE_RECORD_SCHEMA, "record_type": record_type, "provenance": provenance, "consent": safe_consent, **stored}

    def record_run(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        return self.record("mapper-run", payload, **kwargs)

    def record_change(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        return self.record("mapper-change", payload, **kwargs)

    def record_generation(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        return self.record("repository-generation", payload, **kwargs)

    record_repository_generation = record_generation

    def record_precedent(self, payload: Any, *, applicability_evidence: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.record("precedent", payload, applicability_evidence=applicability_evidence, **kwargs)

    def record_recipe(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        return self.record("recipe", payload, **kwargs)

    def record_decision(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        return self.record("decision", payload, **kwargs)

    def record_execution_outcome(self, payload: Any, **kwargs: Any) -> dict[str, Any]:
        return self.record("execution-outcome", payload, **kwargs)

    record_outcome = record_execution_outcome

    def tombstone(self, stable_id: str, *, reason: str = "deleted") -> dict[str, Any]:
        """Tombstone memory and semantic data through the Mapper-owned facade."""
        self._ensure_initialized()
        return self.memory.tombstone(stable_id, reason=reason)

    def append_event(
        self, run_id: str, event_type: str, payload: Mapping[str, Any], *, expected_seq: int | None = None
    ) -> dict[str, Any]:
        """Append an auditable operations event through the canonical facade."""
        self._ensure_initialized()
        return self.operations.append_event(run_id, event_type, payload, expected_seq=expected_seq)

    def replay(self, run_id: str) -> dict[str, Any]:
        self._require_ready()
        return self.operations.replay(run_id)

    def compact(self, run_id: str, through_seq: int, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Compact the Mapper-owned operations journal with its receipt boundary."""
        self._ensure_initialized()
        return self.operations.compact(run_id, through_seq, snapshot)

    def operations_status(self, task_id: str | None = None) -> dict[str, Any]:
        self._require_ready()
        return self.operations.status(task_id)

    def read_record(self, stable_id: str) -> dict[str, Any]:
        self._require_ready()
        with self.memory._open(read_only=True) as store:
            try:
                row = store.execute(
                    "SELECT stable_id,topic,content,content_hash,source,source_path,source_hash,actor,tags_json,metadata_json,consent_json,observed_at,tombstone FROM memory_entries WHERE stable_id=?",
                    (stable_id,),
                ).fetchone()
            except sqlite3.Error as error:
                raise MapperStoreError("STORE_NOT_READY") from error
        if not row:
            raise MapperStoreError("RECORD_NOT_FOUND", stable_id)
        metadata = _read_json(row[9], {})
        payload = metadata.get("payload", row[2]) if isinstance(metadata, dict) else row[2]
        return {
            "schema": MAPPER_STORE_RECORD_SCHEMA,
            "stable_id": row[0],
            "record_type": metadata.get("record_type", row[1]) if isinstance(metadata, dict) else row[1],
            "payload": payload,
            "content": row[2],
            "content_hash": row[3],
            "source": row[4],
            "source_path": row[5],
            "source_hash": row[6],
            "producer": metadata.get("producer", row[7]) if isinstance(metadata, dict) else row[7],
            "metadata": metadata,
            "provenance": metadata.get("provenance", {}) if isinstance(metadata, dict) else {},
            "consent": _read_json(row[10], {}),
            "observed_at": row[11],
            "tombstone": bool(row[12]),
        }

    def list_records(self, record_type: str | None = None, *, limit: int = 1000) -> list[dict[str, Any]]:
        if limit < 1 or limit > 10000:
            raise MapperStoreError("LIMIT_INVALID")
        self._require_ready()
        with self.memory._open(read_only=True) as store:
            rows = store.execute(
                "SELECT stable_id FROM memory_entries ORDER BY stable_id LIMIT ?", (limit,)
            ).fetchall()
        records = [self.read_record(str(row[0])) for row in rows]
        if record_type is not None:
            records = [record for record in records if record["record_type"] == record_type]
        return records[:limit]

    def absorb_legacy(self, source: str | os.PathLike[str], *, mark_read_only: bool = True) -> dict[str, Any]:
        """Absorb legacy ``simplicio-memory.sqlite`` without deleting it."""
        source_path = _safe_path(source)
        if not source_path.is_file():
            raise MapperStoreError("LEGACY_SOURCE_MISSING", str(source_path))
        if source_path == self.memory_database or source_path == self.operations_database:
            raise MapperStoreError("LEGACY_SOURCE_IS_CANONICAL")
        if source_path.with_name(source_path.name + ".writer.lock").exists():
            raise MapperStoreError("LEGACY_SOURCE_WRITERS_ACTIVE")
        source_hash = _path_sha(source_path)
        migration_id = f"legacy-absorb:{_digest({'source': str(source_path), 'source_hash': source_hash, 'memory': str(self.memory_database), 'operations': str(self.operations_database)})[:40]}"
        if self.operations_database.is_file():
            try:
                replay = self.operations.replay(migration_id)
                if replay["events"]:
                    previous = dict(replay["events"][-1]["payload"]["report"])
                    previous["status"] = "unchanged"
                    previous["imported"] = 0
                    previous["unchanged"] = previous.get("rows_seen", 0)
                    previous["replayed"] = True
                    marker = source_path.with_name(source_path.name + ".mapper-store-read-only.json")
                    if marker.is_file():
                        previous["legacy_read_only_marker"] = str(marker)
                    return previous
            except (OperationsStoreError, sqlite3.Error):
                pass
        try:
            # Keep WAL frames visible while still opening the legacy source in
            # SQLite read-only mode; immutable=1 would silently hide them.
            connection = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0]).lower()
            if integrity != "ok":
                raise MapperStoreError("LEGACY_SOURCE_CORRUPT", integrity)
            table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_items'").fetchone()
            if not table:
                raise MapperStoreError("LEGACY_SCHEMA_INVALID", "memory_items")
            rows = connection.execute("SELECT * FROM memory_items ORDER BY id, stable_id").fetchall()
        except sqlite3.Error as error:
            raise MapperStoreError("LEGACY_SOURCE_UNREADABLE", str(error)) from error
        finally:
            try:
                connection.close()
            except UnboundLocalError:
                pass
        self.initialize()
        imported = unchanged = 0
        lineage = {"source_path": str(source_path), "source_sha256": source_hash, "migration_id": migration_id}
        for row in rows:
            raw = {key: row[key] for key in row.keys()}
            record_type = str(raw.get("kind") or "legacy-record")
            legacy_stable_id = str(raw.get("stable_id") or "")
            stable_id = legacy_stable_id or f"legacy:{_digest({'source_hash': source_hash, 'row_id': raw.get('id'), 'record': raw})[:40]}"
            metadata = _read_json(raw.get("metadata"), {})
            provenance = _read_json(raw.get("provenance"), {})
            if not isinstance(metadata, dict):
                metadata = {"legacy_metadata_raw": raw.get("metadata")}
            if not isinstance(provenance, dict):
                provenance = {"legacy_provenance_raw": raw.get("provenance")}
            payload = {"legacy_record": raw, "content": raw.get("content", ""), "title": raw.get("title", "")}
            content = _canonical(payload)
            expected_hash = _sha_text(content)
            existing = None
            if self.memory_database.is_file():
                with self.memory._open(read_only=True) as store:
                    existing = store.execute("SELECT content_hash FROM memory_entries WHERE stable_id=?", (stable_id,)).fetchone()
            if existing and str(existing[0]) != expected_hash:
                raise MapperStoreError("LEGACY_ID_CONFLICT", stable_id)
            combined_provenance = {
                **provenance,
                "source": provenance.get("source", raw.get("source", "legacy")),
                "producer": provenance.get("producer", "legacy-simplicio-memory"),
                "version": provenance.get("version", "legacy"),
                "repository_id": metadata.get("repository_id") or provenance.get("repository_id"),
                "generation": metadata.get("generation") or provenance.get("generation"),
                "legacy": {**lineage, "row_id": raw.get("id"), "stable_id": legacy_stable_id or None, "kind": record_type},
            }
            result = self.record(
                record_type,
                payload,
                repository_id=combined_provenance.get("repository_id"),
                generation=combined_provenance.get("generation"),
                source=str(raw.get("source") or "legacy-simplicio-memory"),
                producer=str(combined_provenance.get("producer")),
                version=str(combined_provenance.get("version")),
                consent=(metadata.get("consent") or provenance.get("consent"))
                if isinstance(metadata.get("consent") or provenance.get("consent"), dict)
                else {},
                source_hash=str(raw.get("source_hash") or source_hash),
                source_path=str(raw.get("artifact_path")) if raw.get("artifact_path") else None,
                stable_id=stable_id,
                provenance_extra={"legacy": combined_provenance["legacy"]},
            )
            if result["status"] == "unchanged":
                unchanged += 1
            else:
                imported += 1
        conformance = self.conformance()
        if not conformance["ok"]:
            raise MapperStoreError("MIGRATION_VERIFY_FAILED", json.dumps(conformance, sort_keys=True))
        marker = source_path.with_name(source_path.name + ".mapper-store-read-only.json")
        report = {
            "schema": MAPPER_STORE_ABSORB_SCHEMA,
            "status": "absorbed" if imported else "unchanged",
            "migration_id": migration_id,
            "source_lineage": lineage,
            "rows_seen": len(rows),
            "imported": imported,
            "unchanged": unchanged,
            "legacy_read_only": bool(mark_read_only),
            "legacy_cleanup": "explicit-policy-required",
            "canonical": self._paths(),
        }
        if mark_read_only:
            report["legacy_read_only_marker"] = str(marker)
        self.operations.append_event(migration_id, "legacy_absorb", {"report": report})
        if mark_read_only:
            marker.write_text(json.dumps({"schema": MAPPER_STORE_ABSORB_SCHEMA, "source_sha256": source_hash, "migration_id": migration_id, "policy": "read-only; no automatic deletion", "canonical": self._paths()}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return report

    absorb = absorb_legacy


class MapperStoreReader:
    """Read-only client contract for Runtime, Fast, Loop and MCP."""

    def __init__(self, root: str | os.PathLike[str] | None = None, **kwargs: Any) -> None:
        self._store = MapperStore(root, auto_create=False, **kwargs)

    def status(self) -> dict[str, Any]:
        return self._store.status()

    def capabilities(self) -> dict[str, Any]:
        return self._store.capabilities()

    def conformance(self) -> dict[str, Any]:
        return self._store.conformance()

    def recall(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self._store._require_ready()
        return self._store.memory.recall(query, **kwargs)

    def read_record(self, stable_id: str) -> dict[str, Any]:
        return self._store.read_record(stable_id)

    def list_records(self, record_type: str | None = None, *, limit: int = 1000) -> list[dict[str, Any]]:
        return self._store.list_records(record_type, limit=limit)

    def operations_status(self, task_id: str | None = None) -> dict[str, Any]:
        return self._store.operations.status(task_id)


__all__ = ["MapperStore", "MapperStoreError", "MapperStoreReader"]
