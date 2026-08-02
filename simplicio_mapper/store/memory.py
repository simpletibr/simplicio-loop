"""Canonical cross-agent memory and Markdown compatibility adapter.

Markdown is an optional, auditable interchange surface.  SQLite owns the
canonical entry metadata while :class:`SemanticStore` owns FTS/vector indexes
and ranking; memory never maintains a second search index or copies vectors.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connection import StoreConnection, StoreError, WriterIdentity
from .locks import StoreFileLock
from .profiles import StoreProfile
from .semantic import (
    SEMANTIC_API_SCHEMA,
    SemanticStore,
    SemanticStoreError,
    _deterministic_embedding,
    _redact,
    _redact_value,
)
from .transactions import transaction

MEMORY_SCHEMA = "simplicio.mapper-store.memory/v1"
MEMORY_API_SCHEMA = "simplicio.mapper-store.memory-api/v1"
MEMORY_VALIDATION_SCHEMA = "simplicio.mapper-store.memory-validation/v1"
MEMORY_HANDOFF_SCHEMA = "simplicio.mapper-store.handoff/v1"
MEMORY_SNAPSHOT_SCHEMA = "simplicio.mapper-store.memory-snapshot/v1"
_ENTRY_HEADER = re.compile(r"^##\s+(.+?)\s+—\s+(.+?)\s*$")
_MAX_CONTENT = 200_000
_MAX_ENTRIES = 100_000


class MemoryStoreError(StoreError):
    """Typed memory failure with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise MemoryStoreError("JSON_INVALID") from error


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha(value: Any) -> str:
    return _sha_text(_canonical(value))


def _slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug or "untitled"


def memory_dir() -> Path:
    override = os.environ.get("SIMPLICIO_MEMORY_DIR")
    if override:
        return Path(override).expanduser()
    return (Path(os.environ.get("HOME", str(Path.home()))) / ".simplicio" / "memory").expanduser()


def _split_sections(text: str) -> list[str]:
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    return [part for part in parts if part.strip()]


def _parse_markdown(path: Path, text: str) -> tuple[str, list[dict[str, Any]], list[dict[str, str]]]:
    lines = text.splitlines()
    errors: list[dict[str, str]] = []
    topic = ""
    if lines and lines[0].startswith("# "):
        topic = lines[0][2:].strip()
    else:
        errors.append({"code": "missing_topic_header", "path": str(path)})
        topic = path.stem
    entries: list[dict[str, Any]] = []
    for ordinal, section in enumerate(_split_sections(text)):
        section_lines = section.splitlines()
        if not section_lines or not section_lines[0].startswith("## "):
            continue
        match = _ENTRY_HEADER.match(section_lines[0])
        if not match:
            errors.append({"code": "invalid_entry_header", "path": str(path), "ordinal": str(ordinal)})
            continue
        timestamp, actor = match.groups()
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append({"code": "invalid_timestamp", "path": str(path), "ordinal": str(ordinal)})
            continue
        tags: list[str] = []
        body_lines = section_lines[1:]
        if body_lines and body_lines[0].lower().startswith("tags:"):
            tags = [tag.strip() for tag in body_lines[0][5:].split(",") if tag.strip()]
            body_lines = body_lines[1:]
        content = "\n".join(body_lines).strip()
        if not content:
            errors.append({"code": "empty_entry", "path": str(path), "ordinal": str(ordinal)})
            continue
        entries.append(
            {"ordinal": ordinal, "timestamp": timestamp, "actor": actor, "tags": tags, "content": content}
        )
    return topic, entries, errors


def _markdown_stable_id(item: Mapping[str, Any], topic: str) -> str:
    """Derive an import identity from entry content, not its section ordinal."""
    identity = {
        "path": str(item["path"]),
        "topic": topic,
        "timestamp": str(item["timestamp"]),
        "actor": str(item["actor"]),
        "tags": list(item.get("tags", [])),
        "content_hash": _sha_text(str(item["content"]).strip()),
    }
    return f"memory:markdown:{_sha(identity)[:32]}"


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(base.resolve(strict=False)).as_posix()
    except ValueError as error:
        raise MemoryStoreError("PATH_OUTSIDE_ROOT", str(path)) from error


def _git(base: Path, *args: str) -> bool:
    if shutil.which("git") is None:
        return False
    try:
        result = subprocess.run(
            ["git", *args], cwd=base, capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


class MarkdownGitAdapter:
    """Compatibility adapter for the Dev CLI Markdown + optional git layout."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().absolute()
        self.notes = self.root / "notes"

    def initialize(self) -> dict[str, Any]:
        created = not self.root.exists()
        self.notes.mkdir(parents=True, exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# simplicio cross-vendor memory\n\n"
                f"Schema: `{MEMORY_SCHEMA}`\n\n"
                "Markdown is an auditable compatibility surface for the canonical MapperStore.\n",
                encoding="utf-8",
            )
        git_initialized = (self.root / ".git").is_dir() or _git(self.root, "init", "-q")
        return {
            "schema": MEMORY_SCHEMA,
            "dir": str(self.root),
            "created": created,
            "git_initialized": git_initialized,
        }

    def read(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if not self.notes.is_dir():
            return [], [{"code": "missing_notes_dir", "path": str(self.notes)}]
        entries: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for path in sorted(self.notes.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                errors.append({"code": "read_failed", "path": str(path), "detail": str(error)})
                continue
            topic, parsed, parse_errors = _parse_markdown(path, text)
            errors.extend(parse_errors)
            source_hash = _sha_text(text)
            relative = _safe_relative(path, self.root)
            for item in parsed:
                item.update({"topic": topic, "path": relative, "source_hash": source_hash})
                entries.append(item)
        return entries, errors

    def commit(self, message: str) -> bool:
        return _git(self.root, "add", "-A") and _git(self.root, "commit", "-q", "-m", message)


class MemoryStore:
    """Canonical memory database with Markdown import/export and handoff APIs."""

    def __init__(
        self,
        database: str | Path | None = None,
        *,
        markdown_root: str | Path | None = None,
        writer: WriterIdentity | None = None,
        auto_create: bool = True,
        max_content_chars: int = _MAX_CONTENT,
    ) -> None:
        self.markdown_root = (
            Path(markdown_root).expanduser().absolute() if markdown_root is not None else None
        )
        if database is None:
            database = (self.markdown_root or memory_dir()) / "memory.sqlite"
        self.database = Path(database).expanduser().absolute()
        if max_content_chars < 1:
            raise ValueError("max_content_chars must be positive")
        self.max_content_chars = min(max_content_chars, _MAX_CONTENT)
        self.writer = writer or WriterIdentity.create("simplicio_mapper.memory_store")
        self.auto_create = auto_create
        self.lock_path = self.database.with_name(self.database.name + ".memory.lock")
        self.semantic = SemanticStore(
            self.database,
            writer=WriterIdentity.create("simplicio_mapper.memory_semantic", self.writer.instance_id),
            auto_create=auto_create,
            max_content_chars=self.max_content_chars,
        )

    def _open(self, *, read_only: bool = False) -> StoreConnection:
        if read_only:
            return StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False)
        return StoreConnection.open(self.database, StoreProfile.read_write(), writer_identity=self.writer)

    def _ensure_schema(self, store: StoreConnection) -> None:
        with transaction(store, "EXCLUSIVE") as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS memory_store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS memory_entries (
                    stable_id TEXT PRIMARY KEY, topic TEXT NOT NULL, content TEXT NOT NULL,
                    content_hash TEXT NOT NULL, source TEXT NOT NULL, source_path TEXT,
                    source_hash TEXT, actor TEXT NOT NULL, tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL, consent_json TEXT NOT NULL,
                    retention_until TEXT, observed_at TEXT NOT NULL, created_at TEXT NOT NULL,
                    supersedes_id TEXT, tombstone INTEGER NOT NULL DEFAULT 0 CHECK(tombstone IN (0,1))
                )"""
            )
            tx.execute("CREATE INDEX IF NOT EXISTS idx_memory_entries_topic ON memory_entries(topic)")
            tx.execute("CREATE INDEX IF NOT EXISTS idx_memory_entries_source ON memory_entries(source_path)")
            tx.execute(
                """CREATE TABLE IF NOT EXISTS memory_outcomes (
                    outcome_id TEXT PRIMARY KEY, stable_id TEXT NOT NULL, outcome TEXT NOT NULL,
                    actor TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS memory_handoffs (
                    handoff_id TEXT PRIMARY KEY, packet_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                "INSERT OR REPLACE INTO memory_store_meta(key,value) VALUES ('schema', ?)", (MEMORY_SCHEMA,)
            )

    def initialize(self) -> dict[str, Any]:
        if not self.auto_create:
            raise MemoryStoreError("STORE_READ_ONLY")
        if self.markdown_root is not None:
            adapter = MarkdownGitAdapter(self.markdown_root)
            markdown = adapter.initialize()
        else:
            markdown = None
        self.semantic.initialize()
        with StoreFileLock(
            self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}", blocking=True
        ):
            with self._open() as store:
                self._ensure_schema(store)
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": "ready",
            "database": str(self.database),
            "markdown": markdown,
        }

    def _ensure_ready(self, store: StoreConnection) -> None:
        if self.auto_create:
            self._ensure_schema(store)
            return
        try:
            row = store.execute("SELECT value FROM memory_store_meta WHERE key='schema'").fetchone()
        except Exception as error:
            raise MemoryStoreError("STORE_NOT_INITIALIZED") from error
        if not row or row[0] != MEMORY_SCHEMA:
            raise MemoryStoreError("MEMORY_SCHEMA_INVALID")

    @staticmethod
    def _json(value: Mapping[str, Any] | None, name: str) -> str:
        try:
            safe = _redact_value(dict(value or {}))
            result = _canonical(safe)
        except (TypeError, ValueError, MemoryStoreError) as error:
            raise MemoryStoreError("JSON_INVALID", name) from error
        if len(result) > 200_000:
            raise MemoryStoreError("JSON_LIMIT", name)
        return result

    def store(
        self,
        topic: str,
        content: str,
        *,
        tags: list[str] | None = None,
        actor: str = "unknown-agent",
        source: str = "mapper-memory",
        source_path: str | None = None,
        source_hash: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        consent: Mapping[str, Any] | None = None,
        retention_until: str | None = None,
        observed_at: str | None = None,
        supersedes_id: str | None = None,
        stable_id: str | None = None,
        export_markdown: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(topic, str) or not topic.strip() or not isinstance(content, str):
            raise MemoryStoreError("IDENTITY_INVALID")
        if (
            not isinstance(actor, str)
            or not actor.strip()
            or not isinstance(source, str)
            or not source.strip()
        ):
            raise MemoryStoreError("IDENTITY_INVALID")
        safe_content = _redact(content.strip())
        if not safe_content:
            raise MemoryStoreError("CONTENT_EMPTY")
        if len(safe_content) > self.max_content_chars:
            raise MemoryStoreError("CONTENT_LIMIT")
        safe_topic, safe_actor, safe_source = (
            _redact(topic.strip()),
            _redact(actor.strip()),
            _redact(source.strip()),
        )
        normalized_tags = sorted({_redact(str(tag).strip()) for tag in (tags or []) if str(tag).strip()})
        content_hash = _sha_text(safe_content)
        identity = {
            "topic": safe_topic,
            "content_hash": content_hash,
            "actor": safe_actor,
            "source": safe_source,
        }
        stable_id = stable_id or f"memory:{_sha(identity)[:40]}"
        observed = observed_at or _now()
        metadata_json = self._json(metadata, "metadata")
        consent_json = self._json(consent, "consent")
        safe_metadata = dict(_redact_value(dict(metadata or {})))
        safe_metadata.update({"topic": safe_topic, "tags": normalized_tags})
        provenance = {
            "source": safe_source,
            "actor": safe_actor,
            "source_path": source_path,
            "source_hash": source_hash,
        }
        if self.markdown_root is not None:
            MarkdownGitAdapter(self.markdown_root).initialize()
        model, dimensions = self._embedding_contract()
        with StoreFileLock(
            self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}", blocking=True
        ):
            self.semantic.upsert(
                stable_id,
                safe_content,
                kind="memory",
                source=safe_source,
                provenance=provenance,
                metadata=safe_metadata,
                embedding=_deterministic_embedding(safe_content, dimensions),
                model=model,
                dimensions=dimensions,
                observed_at=observed,
                supersedes_id=supersedes_id,
            )
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    existing = tx.execute(
                        "SELECT content_hash,tombstone,created_at FROM memory_entries WHERE stable_id=?",
                        (stable_id,),
                    ).fetchone()
                    if existing and existing[0] == content_hash and not existing[1]:
                        status = "unchanged"
                    else:
                        status = (
                            "revived" if existing and existing[1] else "updated" if existing else "inserted"
                        )
                        tx.execute(
                            """INSERT INTO memory_entries(stable_id,topic,content,content_hash,source,source_path,source_hash,
                               actor,tags_json,metadata_json,consent_json,retention_until,observed_at,created_at,supersedes_id,tombstone)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                               ON CONFLICT(stable_id) DO UPDATE SET topic=excluded.topic,content=excluded.content,
                               content_hash=excluded.content_hash,source=excluded.source,source_path=excluded.source_path,
                               source_hash=excluded.source_hash,actor=excluded.actor,tags_json=excluded.tags_json,
                               metadata_json=excluded.metadata_json,consent_json=excluded.consent_json,
                               retention_until=excluded.retention_until,observed_at=excluded.observed_at,
                               supersedes_id=excluded.supersedes_id,tombstone=0""",
                            (
                                stable_id,
                                safe_topic,
                                safe_content,
                                content_hash,
                                safe_source,
                                source_path,
                                source_hash,
                                safe_actor,
                                _canonical(normalized_tags),
                                metadata_json,
                                consent_json,
                                retention_until,
                                observed,
                                existing[2] if existing else observed,
                                supersedes_id,
                            ),
                        )
        if export_markdown and self.markdown_root is not None:
            self.export_markdown(self.markdown_root)
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": status,
            "stable_id": stable_id,
            "content_hash": content_hash,
        }

    def _embedding_contract(self) -> tuple[str, int]:
        """Use the already-active semantic model when one exists."""
        default = ("memory-lexical-v1", 128)
        if not self.database.exists():
            return default
        try:
            with self.semantic._open(read_only=True) as store:
                row = store.execute(
                    "SELECT model, dimensions FROM semantic_models WHERE active=1 ORDER BY model LIMIT 1"
                ).fetchone()
        except (StoreError, SemanticStoreError, sqlite3.Error):
            return default
        return (str(row[0]), int(row[1])) if row else default

    def _existing_markdown_id(self, item: Mapping[str, Any]) -> str | None:
        """Keep an old ordinal-based ID when upgrading an existing store."""
        content_hash = _sha_text(_redact(str(item["content"]).strip()))
        try:
            with self._open(read_only=True) as store:
                row = store.execute(
                    """SELECT stable_id FROM memory_entries
                       WHERE source='markdown' AND source_path=? AND content_hash=? AND tombstone=0
                       ORDER BY created_at, stable_id LIMIT 1""",
                    (str(item["path"]), content_hash),
                ).fetchone()
        except (OSError, StoreError, sqlite3.Error):
            return None
        return str(row[0]) if row else None

    def import_markdown(self, root: str | Path | None = None, *, strict: bool = False) -> dict[str, Any]:
        adapter = MarkdownGitAdapter(root or self.markdown_root or memory_dir())
        adapter.initialize()
        parsed, errors = adapter.read()
        if strict and errors:
            raise MemoryStoreError("MARKDOWN_INVALID", json.dumps(errors, sort_keys=True))
        imported = 0
        unchanged = 0
        for item in parsed[:_MAX_ENTRIES]:
            stable_id = self._existing_markdown_id(item) or _markdown_stable_id(item, str(item["topic"]))
            result = self.store(
                item["topic"],
                item["content"],
                tags=item["tags"],
                actor=item["actor"],
                source="markdown",
                source_path=item["path"],
                source_hash=item["source_hash"],
                observed_at=item["timestamp"],
                stable_id=stable_id,
            )
            if result["status"] == "unchanged":
                unchanged += 1
            else:
                imported += 1
        if len(parsed) > _MAX_ENTRIES:
            errors.append({"code": "ENTRY_LIMIT", "path": str(adapter.root)})
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": "imported",
            "imported": imported,
            "unchanged": unchanged,
            "errors": errors,
            "entries": len(parsed),
        }

    def export_markdown(
        self, destination: str | Path | None = None, *, commit: bool = False
    ) -> dict[str, Any]:
        target = Path(destination or self.markdown_root or memory_dir()).expanduser().absolute()
        adapter = MarkdownGitAdapter(target)
        adapter.initialize()
        with self._open(read_only=True) as store:
            rows = store.execute(
                "SELECT topic,content,actor,tags_json,observed_at,stable_id FROM memory_entries WHERE tombstone=0 ORDER BY topic,created_at,stable_id"
            ).fetchall()
        grouped: dict[str, list[tuple[Any, ...]]] = {}
        for row in rows:
            grouped.setdefault(_slugify(str(row[0])), []).append(row)
        written: list[str] = []
        for slug, items in grouped.items():
            topic = str(items[0][0])
            text = f"# {topic}\n\n"
            for item in items:
                tags = json.loads(item[3])
                text += f"## {item[4]} — {item[2]}\n"
                if tags:
                    text += "tags: " + ", ".join(tags) + "\n"
                text += f"\n{item[1].strip()}\n\n"
            path = adapter.notes / f"{slug}.md"
            path.write_text(text, encoding="utf-8")
            written.append(str(path))
        committed = adapter.commit("memory: export canonical MapperStore") if commit else False
        return {"schema": MEMORY_API_SCHEMA, "status": "exported", "files": written, "committed": committed}

    def recall(
        self, query: str, *, limit: int = 5, mode: str = "hybrid", query_embedding: list[float] | None = None
    ) -> dict[str, Any]:
        semantic_mode = "fts" if mode == "fts5" else mode
        if semantic_mode not in {"fts", "vector", "hybrid"}:
            raise MemoryStoreError("MODE_INVALID", mode)
        result = self.semantic.recall(
            query, mode=semantic_mode, limit=min(1000, max(limit * 8, limit)), query_embedding=query_embedding
        )
        now = datetime.now(timezone.utc)
        with self._open(read_only=True) as store:
            rows = store.execute(
                "SELECT stable_id,topic,actor,tags_json,metadata_json,consent_json,retention_until,source_path,source_hash,content,tombstone FROM memory_entries"
            ).fetchall()
        by_id = {str(row[0]): row for row in rows}
        results: list[dict[str, Any]] = []
        score_key = (
            "fts_score"
            if semantic_mode == "fts"
            else "vector_score"
            if semantic_mode == "vector"
            else "hybrid_score"
        )
        for item in result["results"]:
            row = by_id.get(str(item["stable_id"]))
            if not row or row[10] or (row[6] and _expired(str(row[6]), now)):
                continue
            enriched = dict(item)
            enriched.update(
                {
                    "topic": row[1],
                    "actor": row[2],
                    "tags": json.loads(row[3]),
                    "metadata": json.loads(row[4]),
                    "consent": json.loads(row[5]),
                    "source_path": row[7],
                    "source_hash": row[8],
                    "content": row[9],
                }
            )
            enriched["score"] = item.get(score_key, 0.0)
            results.append(enriched)
            if len(results) >= limit:
                break
        result.update({"schema": MEMORY_API_SCHEMA, "mode": mode, "requested_mode": mode, "results": results})
        return result

    def outcome(
        self,
        stable_id: str,
        outcome: str,
        *,
        actor: str = "unknown-agent",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not stable_id or not outcome.strip():
            raise MemoryStoreError("IDENTITY_INVALID")
        outcome_identity = {"stable_id": stable_id, "outcome": outcome, "actor": actor}
        outcome_id = f"outcome:{_sha(outcome_identity)[:40]}"
        with StoreFileLock(
            self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}", blocking=True
        ):
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    if not tx.execute(
                        "SELECT 1 FROM memory_entries WHERE stable_id=? AND tombstone=0", (stable_id,)
                    ).fetchone():
                        raise MemoryStoreError("ENTRY_NOT_FOUND", stable_id)
                    tx.execute(
                        "INSERT OR IGNORE INTO memory_outcomes VALUES (?,?,?,?,?,?)",
                        (
                            outcome_id,
                            stable_id,
                            _redact(outcome.strip()),
                            _redact(actor),
                            self._json(metadata, "metadata"),
                            _now(),
                        ),
                    )
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": "recorded",
            "outcome_id": outcome_id,
            "stable_id": stable_id,
        }

    def handoff(
        self,
        query: str,
        *,
        limit: int = 5,
        mode: str = "hybrid",
        from_agent: str = "unknown",
        to_agent: str = "unknown",
        persist: bool = True,
    ) -> dict[str, Any]:
        recalled = self.recall(query, limit=limit, mode=mode)
        validation = self.validate()
        body = {
            "schema": MEMORY_HANDOFF_SCHEMA,
            "version": 1,
            "query": _redact(query),
            "from_agent": _redact(from_agent),
            "to_agent": _redact(to_agent),
            "validation": {"ok": validation["ok"], "errors": validation["errors"]},
            "results": recalled["results"],
        }
        body["packet_hash"] = _sha(body)
        if persist:
            with StoreFileLock(
                self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}", blocking=True
            ):
                with self._open() as store:
                    self._ensure_ready(store)
                    with transaction(store, "IMMEDIATE") as tx:
                        tx.execute(
                            "INSERT OR REPLACE INTO memory_handoffs VALUES (?,?,?,?)",
                            (
                                f"handoff:{body['packet_hash'][:40]}",
                                body["packet_hash"],
                                _canonical(body),
                                _now(),
                            ),
                        )
        return body

    def validate_handoff(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        if packet.get("schema") not in {MEMORY_HANDOFF_SCHEMA, "simplicio.memory-handoff/v1"}:
            errors.append({"code": "HANDOFF_SCHEMA_INVALID"})
        for key in ("query", "from_agent", "to_agent", "results"):
            if key not in packet:
                errors.append({"code": "HANDOFF_FIELD_MISSING", "field": key})
        if "packet_hash" in packet:
            candidate = dict(packet)
            expected = candidate.pop("packet_hash")
            if _sha(candidate) != expected:
                errors.append({"code": "HANDOFF_HASH_INVALID"})
        return {"schema": MEMORY_VALIDATION_SCHEMA, "ok": not errors, "errors": errors}

    def validate(self) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        try:
            with self._open(read_only=True) as store:
                count = int(
                    store.execute("SELECT COUNT(*) FROM memory_entries WHERE tombstone=0").fetchone()[0]
                )
                orphan_memory = int(
                    store.execute(
                        "SELECT COUNT(*) FROM memory_entries e LEFT JOIN semantic_items i ON i.stable_id=e.stable_id WHERE e.tombstone=0 AND i.stable_id IS NULL"
                    ).fetchone()[0]
                )
                orphan_semantic = int(
                    store.execute(
                        "SELECT COUNT(*) FROM semantic_items i LEFT JOIN memory_entries e ON e.stable_id=i.stable_id WHERE i.kind='memory' AND i.tombstone=0 AND e.stable_id IS NULL"
                    ).fetchone()[0]
                )
                if orphan_memory:
                    errors.append({"code": "SEMANTIC_REFERENCE_MISSING", "count": str(orphan_memory)})
                if orphan_semantic:
                    errors.append({"code": "MEMORY_REFERENCE_MISSING", "count": str(orphan_semantic)})
        except (StoreError, SemanticStoreError, MemoryStoreError, sqlite3.Error) as error:
            errors.append({"code": getattr(error, "reason_code", "STORE_INVALID"), "detail": str(error)})
            count = 0
        if self.markdown_root is not None and self.markdown_root.exists():
            adapter = MarkdownGitAdapter(self.markdown_root)
            markdown_entries, markdown_errors = adapter.read()
            errors.extend(markdown_errors)
            with self._open(read_only=True) as store:
                source_rows = store.execute(
                    "SELECT source_path, source_hash FROM memory_entries WHERE source='markdown' AND tombstone=0"
                ).fetchall()
            current_hashes = {str(item["path"]): str(item["source_hash"]) for item in markdown_entries}
            for source_path, source_hash in source_rows:
                if (
                    source_path
                    and source_hash
                    and current_hashes.get(str(source_path))
                    not in {
                        None,
                        str(source_hash),
                    }
                ):
                    warnings.append({"code": "SOURCE_CHANGED", "path": str(source_path)})
        return {
            "schema": MEMORY_VALIDATION_SCHEMA,
            "ok": not errors,
            "database": str(self.database),
            "entries": count,
            "errors": errors,
            "warnings": warnings,
            "semantic_schema": SEMANTIC_API_SCHEMA,
        }

    def export_snapshot(self, path: str | Path) -> dict[str, Any]:
        with self._open(read_only=True) as store:
            entries = [
                dict(
                    zip(
                        (
                            "stable_id",
                            "topic",
                            "content",
                            "content_hash",
                            "source",
                            "source_path",
                            "source_hash",
                            "actor",
                            "tags_json",
                            "metadata_json",
                            "consent_json",
                            "retention_until",
                            "observed_at",
                            "created_at",
                            "supersedes_id",
                            "tombstone",
                        ),
                        row,
                        strict=True,
                    )
                )
                for row in store.execute("SELECT * FROM memory_entries ORDER BY stable_id").fetchall()
            ]
            outcomes = [
                dict(
                    zip(
                        ("outcome_id", "stable_id", "outcome", "actor", "metadata_json", "created_at"),
                        row,
                        strict=True,
                    )
                )
                for row in store.execute("SELECT * FROM memory_outcomes ORDER BY outcome_id").fetchall()
            ]
        payload = {"schema": MEMORY_SNAPSHOT_SCHEMA, "version": 1, "entries": entries, "outcomes": outcomes}
        payload["snapshot_hash"] = _sha(payload)
        destination = Path(path).expanduser().absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_canonical(payload) + "\n", encoding="utf-8")
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": "exported",
            "path": str(destination),
            "snapshot_hash": payload["snapshot_hash"],
            "entries": len(entries),
        }

    def restore_snapshot(self, path: str | Path) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MemoryStoreError("SNAPSHOT_INVALID") from error
        if payload.get("schema") != MEMORY_SNAPSHOT_SCHEMA:
            raise MemoryStoreError("SNAPSHOT_SCHEMA_INVALID")
        digest = payload.pop("snapshot_hash", None)
        if not digest or _sha(payload) != digest:
            raise MemoryStoreError("SNAPSHOT_HASH_INVALID")
        for item in payload.get("entries", []):
            self.store(
                item["topic"],
                item["content"],
                tags=json.loads(item["tags_json"]),
                actor=item["actor"],
                source=item["source"],
                source_path=item["source_path"],
                source_hash=item["source_hash"],
                metadata=json.loads(item["metadata_json"]),
                consent=json.loads(item["consent_json"]),
                retention_until=item["retention_until"],
                observed_at=item["observed_at"],
                supersedes_id=item["supersedes_id"],
                stable_id=item["stable_id"],
            )
        for item in payload.get("outcomes", []):
            self.outcome(
                item["stable_id"],
                item["outcome"],
                actor=item["actor"],
                metadata=json.loads(item["metadata_json"]),
            )
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": "restored",
            "entries": len(payload.get("entries", [])),
            "snapshot_hash": digest,
        }

    export = export_snapshot
    restore = restore_snapshot

    def purge_expired(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._open(read_only=True) as store:
            rows = store.execute(
                "SELECT stable_id,retention_until FROM memory_entries WHERE tombstone=0 AND retention_until IS NOT NULL"
            ).fetchall()
            ids = [str(row[0]) for row in rows if _expired(str(row[1]), now)]
        for stable_id in ids:
            self.tombstone(stable_id, reason="retention_expired")
        return {"schema": MEMORY_API_SCHEMA, "status": "purged", "count": len(ids)}

    def tombstone(self, stable_id: str, *, reason: str = "deleted") -> dict[str, Any]:
        with StoreFileLock(
            self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}", blocking=True
        ):
            with self._open() as store:
                self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    changed = tx.execute(
                        "UPDATE memory_entries SET tombstone=1 WHERE stable_id=? AND tombstone=0",
                        (stable_id,),
                    ).rowcount
        if changed:
            self.semantic.tombstone(stable_id, reason=reason)
        return {
            "schema": MEMORY_API_SCHEMA,
            "status": "tombstoned" if changed else "unchanged",
            "stable_id": stable_id,
        }


def _expired(value: str, now: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    return parsed <= now


def init_memory(*, root: str | Path | None = None, database: str | Path | None = None) -> dict[str, Any]:
    base = Path(root).expanduser().absolute() if root is not None else memory_dir()
    return MemoryStore(database or base / "memory.sqlite", markdown_root=base).initialize()


def store_memory(
    topic: str,
    content: str,
    *,
    tags: list[str] | None = None,
    root: str | Path | None = None,
    actor: str = "unknown-agent",
) -> dict[str, Any]:
    base = Path(root).expanduser().absolute() if root is not None else memory_dir()
    return MemoryStore(base / "memory.sqlite", markdown_root=base).store(
        topic, content, tags=tags, actor=actor
    )


def recall_memory(
    query: str, *, limit: int = 5, root: str | Path | None = None, mode: str = "hybrid"
) -> list[dict[str, Any]]:
    base = Path(root).expanduser().absolute() if root is not None else memory_dir()
    if not (base / "memory.sqlite").exists():
        return []
    return MemoryStore(base / "memory.sqlite", markdown_root=base, auto_create=False).recall(
        query, limit=limit, mode=mode
    )["results"]


def validate_memory(*, root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root).expanduser().absolute() if root is not None else memory_dir()
    if not (base / "memory.sqlite").exists():
        return {
            "schema": MEMORY_VALIDATION_SCHEMA,
            "ok": False,
            "database": str(base / "memory.sqlite"),
            "entries": 0,
            "errors": [{"code": "missing_store"}],
            "warnings": [],
        }
    return MemoryStore(base / "memory.sqlite", markdown_root=base, auto_create=False).validate()


def build_handoff(
    query: str,
    *,
    limit: int = 5,
    root: str | Path | None = None,
    from_agent: str = "unknown",
    to_agent: str = "unknown",
) -> dict[str, Any]:
    base = Path(root).expanduser().absolute() if root is not None else memory_dir()
    return MemoryStore(base / "memory.sqlite", markdown_root=base, auto_create=False).handoff(
        query, limit=limit, from_agent=from_agent, to_agent=to_agent
    )


__all__ = [
    "MEMORY_API_SCHEMA",
    "MEMORY_HANDOFF_SCHEMA",
    "MEMORY_SCHEMA",
    "MEMORY_SNAPSHOT_SCHEMA",
    "MEMORY_VALIDATION_SCHEMA",
    "MarkdownGitAdapter",
    "MemoryStore",
    "MemoryStoreError",
    "build_handoff",
    "init_memory",
    "memory_dir",
    "recall_memory",
    "store_memory",
    "validate_memory",
]
