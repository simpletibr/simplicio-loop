"""Authoritative semantic store with honest FTS/vector/hybrid recall.

The relational tables are the source of truth. FTS5 is a rebuildable index and
vector recall is explicitly reported as brute-force unless a future adapter
binds a verified sqlite-vec index.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connection import StoreConnection, StoreError, WriterIdentity
from .locks import StoreFileLock
from .profiles import StoreProfile
from .transactions import transaction

SEMANTIC_SCHEMA = "simplicio.mapper-store.semantic-store/v1"
SEMANTIC_API_SCHEMA = "simplicio.mapper-store.semantic-api/v1"
_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|authorization|password|client[_-]?secret|secret)\s*[:=]\s*['\"]?[^\s,;'\"]+|(?<![\w])Bearer\s+[A-Za-z0-9._~+/=-]+|(?<![\w])(?:sk|ghp|xox[baprs])-[A-Za-z0-9_-]+"
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|authorization|password|client[_-]?secret|secret)"
)
_MAX_CHUNKS = 4096
_MAX_JSON_CHARS = 200_000
_MAX_QUERY_CHARS = 20_000
_MAX_EMBEDDING_DIMENSIONS = 8_192


class SemanticStoreError(StoreError):
    """Typed semantic-store failure with a machine-readable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _redact(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY_RE.search(str(key)) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    return value


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0


def _fts_score(rank: float) -> float:
    relevance = max(0.0, -rank)
    return relevance / (1.0 + relevance)


def _deterministic_embedding(text: str, dimensions: int) -> list[float]:
    tokens = sorted(set(re.findall(r"[\w]{3,}", text.casefold(), flags=re.UNICODE)))
    values = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(dimensions):
            values[index] += digest[index % len(digest)] / 127.5 - 1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [round(value / norm, 8) for value in values]


class SemanticStore:
    """SQLite-backed semantic data and rebuildable retrieval indexes."""

    def __init__(
        self,
        database: str | Path,
        *,
        writer: WriterIdentity | None = None,
        max_content_chars: int = 200_000,
        auto_create: bool = True,
    ) -> None:
        if max_content_chars < 1:
            raise ValueError("max_content_chars must be positive")
        self.database = Path(database).expanduser().absolute()
        self.max_content_chars = max_content_chars
        self.writer = writer or WriterIdentity.create("simplicio_mapper.semantic_store")
        self.auto_create = auto_create
        self.lock_path = self.database.with_name(self.database.name + ".semantic.lock")

    def _open(self, *, read_only: bool = False) -> StoreConnection:
        if read_only:
            return StoreConnection.open(self.database, StoreProfile.read_only(), immutable=False)
        return StoreConnection.open(self.database, StoreProfile.read_write(), writer_identity=self.writer)

    @staticmethod
    def _capabilities(store: StoreConnection) -> dict[str, Any]:
        compile_options = {
            str(row[0]).upper() for row in store.connection.execute("PRAGMA compile_options").fetchall()
        }
        modules = {
            str(row[0]).casefold() for row in store.connection.execute("SELECT name FROM pragma_module_list")
        }
        fts5 = "ENABLE_FTS5" in compile_options
        sqlite_vec = any(name.startswith(("vec", "sqlite_vec")) for name in modules)
        return {
            "fts5": fts5,
            "sqlite_vec": sqlite_vec,
            "vector_backend": "brute-force",
            "ann_claimed": False,
            "fallback_reason": None if sqlite_vec else "SQLITE_VEC_UNAVAILABLE",
        }

    def capabilities(self) -> dict[str, Any]:
        with self._open(read_only=True) as store:
            capabilities = self._capabilities(store)
        return {"schema": SEMANTIC_API_SCHEMA, "capabilities": capabilities}

    def _ensure_schema(self, store: StoreConnection) -> dict[str, Any]:
        capabilities = self._capabilities(store)
        with transaction(store, "EXCLUSIVE") as tx:
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_store_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_items (
                    stable_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    supersedes_id TEXT,
                    tombstone INTEGER NOT NULL DEFAULT 0 CHECK(tombstone IN (0, 1)),
                    updated_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    stable_id TEXT NOT NULL REFERENCES semantic_items(stable_id),
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    tombstone INTEGER NOT NULL DEFAULT 0 CHECK(tombstone IN (0, 1)),
                    UNIQUE(stable_id, ordinal)
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_relations (
                    relation_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, target_id, kind)
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_embeddings (
                    stable_id TEXT NOT NULL REFERENCES semantic_items(stable_id),
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
                    vector_json TEXT NOT NULL,
                    vector_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(stable_id, model)
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_models (
                    model TEXT PRIMARY KEY,
                    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
                    revision TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_provenance (
                    provenance_id TEXT PRIMARY KEY,
                    stable_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_revisions (
                    revision_id TEXT PRIMARY KEY,
                    stable_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    superseded_by TEXT
                )"""
            )
            tx.execute(
                """CREATE TABLE IF NOT EXISTS semantic_tombstones (
                    stable_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    provenance_json TEXT NOT NULL
                )"""
            )
            tx.execute(
                "INSERT OR REPLACE INTO semantic_store_meta(key, value) VALUES ('schema', ?)",
                (SEMANTIC_SCHEMA,),
            )
            tx.execute(
                "INSERT OR REPLACE INTO semantic_store_meta(key, value) VALUES ('capabilities', ?)",
                (_canonical(capabilities),),
            )
            if capabilities["fts5"]:
                tx.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts USING fts5(stable_id UNINDEXED, chunk_id UNINDEXED, content, tokenize='unicode61')"
                )
                tx.execute(
                    """CREATE TRIGGER IF NOT EXISTS semantic_chunks_ai AFTER INSERT ON semantic_chunks
                    WHEN NEW.tombstone = 0 BEGIN
                        INSERT INTO semantic_fts(stable_id, chunk_id, content) VALUES (NEW.stable_id, NEW.chunk_id, NEW.content);
                    END"""
                )
                tx.execute(
                    """CREATE TRIGGER IF NOT EXISTS semantic_chunks_au AFTER UPDATE ON semantic_chunks BEGIN
                        DELETE FROM semantic_fts WHERE chunk_id = OLD.chunk_id;
                        INSERT INTO semantic_fts(stable_id, chunk_id, content)
                        SELECT NEW.stable_id, NEW.chunk_id, NEW.content WHERE NEW.tombstone = 0;
                    END"""
                )
                tx.execute(
                    """CREATE TRIGGER IF NOT EXISTS semantic_chunks_ad AFTER DELETE ON semantic_chunks BEGIN
                        DELETE FROM semantic_fts WHERE chunk_id = OLD.chunk_id;
                    END"""
                )
                tx.execute(
                    """INSERT INTO semantic_fts(stable_id, chunk_id, content)
                       SELECT stable_id, chunk_id, content FROM semantic_chunks
                       WHERE tombstone=0 AND NOT EXISTS (
                           SELECT 1 FROM semantic_fts f WHERE f.chunk_id=semantic_chunks.chunk_id
                       )"""
                )
        return capabilities

    def initialize(self) -> dict[str, Any]:
        if not self.auto_create:
            raise SemanticStoreError("STORE_READ_ONLY", "initialization disabled")
        with StoreFileLock(self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}"):
            with self._open() as store:
                capabilities = self._ensure_schema(store)
        return {"schema": SEMANTIC_API_SCHEMA, "status": "ready", "capabilities": capabilities}

    def _ensure_ready(self, store: StoreConnection) -> dict[str, Any]:
        if self.auto_create:
            return self._ensure_schema(store)
        try:
            row = store.execute("SELECT value FROM semantic_store_meta WHERE key='schema'").fetchone()
        except sqlite3.Error as error:
            raise SemanticStoreError("STORE_NOT_INITIALIZED") from error
        if not row or row[0] != SEMANTIC_SCHEMA:
            raise SemanticStoreError("SEMANTIC_SCHEMA_INVALID")
        return self._capabilities(store)

    @staticmethod
    def _json_object(value: Mapping[str, Any] | None, name: str) -> str:
        if value is None:
            return "{}"
        try:
            payload = _canonical(_redact_value(dict(value)))
        except (TypeError, ValueError) as error:
            raise SemanticStoreError("PROVENANCE_INVALID", name) from error
        if len(payload) > _MAX_JSON_CHARS:
            raise SemanticStoreError("PROVENANCE_LIMIT", name)
        return payload

    def _check_embedding(
        self, tx: Any, embedding: Sequence[float] | None, model: str | None, dimensions: int | None
    ) -> tuple[str | None, int | None, str | None]:
        if embedding is None:
            if model is not None or dimensions is not None:
                raise SemanticStoreError("EMBEDDING_INVALID")
            return None, None, None
        if not model or any(
            not isinstance(value, (int, float)) or not math.isfinite(value) for value in embedding
        ):
            raise SemanticStoreError("EMBEDDING_INVALID")
        actual_dimensions = len(embedding)
        if not actual_dimensions or actual_dimensions > _MAX_EMBEDDING_DIMENSIONS:
            raise SemanticStoreError("EMBEDDING_LIMIT")
        if dimensions is not None and dimensions != actual_dimensions:
            raise SemanticStoreError("EMBEDDING_DIMENSION_MISMATCH")
        existing = tx.execute(
            "SELECT model, dimensions FROM semantic_models WHERE active=1 ORDER BY model"
        ).fetchone()
        if existing and existing[0] == model and int(existing[1]) != actual_dimensions:
            raise SemanticStoreError("EMBEDDING_DIMENSION_MISMATCH")
        if existing and existing[0] != model:
            raise SemanticStoreError("EMBEDDING_MODEL_MISMATCH")
        tx.execute(
            "INSERT OR IGNORE INTO semantic_models(model, dimensions, revision, created_at) VALUES (?, ?, ?, ?)",
            (model, actual_dimensions, "1", _now()),
        )
        vector = [float(value) for value in embedding]
        return model, actual_dimensions, _sha(vector)

    def upsert(
        self,
        stable_id: str,
        content: str,
        *,
        kind: str = "document",
        source: str = "unknown",
        provenance: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        chunks: Iterable[Mapping[str, Any]] | None = None,
        embedding: Sequence[float] | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        observed_at: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        supersedes_id: str | None = None,
        redact: bool = True,
    ) -> dict[str, Any]:
        if (
            not isinstance(content, str)
            or not isinstance(stable_id, str)
            or not isinstance(kind, str)
            or not isinstance(source, str)
        ):
            raise SemanticStoreError("IDENTITY_INVALID")
        if not stable_id.strip() or not kind.strip() or not source.strip():
            raise SemanticStoreError("IDENTITY_INVALID")
        if not redact:
            raise SemanticStoreError("REDACTION_REQUIRED")
        normalized_content = _redact(content)
        if len(normalized_content) > self.max_content_chars:
            raise SemanticStoreError("CONTENT_LIMIT")
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        observed = observed_at or _now()
        valid_start = valid_from or observed
        provenance_json = self._json_object(provenance, "provenance")
        metadata_json = self._json_object(metadata, "metadata")
        prepared_chunks: list[dict[str, Any]] = []
        if chunks is None:
            chunks = [{"content": normalized_content, "chunk_id": f"{stable_id}:0"}]
        for ordinal, chunk in enumerate(chunks):
            if ordinal >= _MAX_CHUNKS:
                raise SemanticStoreError("CHUNK_LIMIT")
            if not isinstance(chunk, Mapping):
                raise SemanticStoreError("CHUNK_INVALID", str(ordinal))
            chunk_content = _redact(str(chunk.get("content", "")))
            if len(chunk_content) > self.max_content_chars:
                raise SemanticStoreError("CONTENT_LIMIT", f"chunk {ordinal}")
            chunk_id = str(chunk.get("chunk_id") or f"{stable_id}:{ordinal}")
            chunk_provenance = self._json_object(chunk.get("provenance"), "chunk provenance")
            prepared_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "ordinal": ordinal,
                    "content": chunk_content,
                    "content_hash": hashlib.sha256(chunk_content.encode("utf-8")).hexdigest(),
                    "provenance_json": chunk_provenance,
                }
            )
        if not prepared_chunks:
            prepared_chunks = [
                {
                    "chunk_id": f"{stable_id}:0",
                    "ordinal": 0,
                    "content": normalized_content,
                    "content_hash": hashlib.sha256(normalized_content.encode("utf-8")).hexdigest(),
                    "provenance_json": "{}",
                }
            ]
        safe_source = _redact(source)
        safe_kind = _redact(kind)
        with StoreFileLock(self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}"):
            with self._open() as store:
                capabilities = self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    checked_model, checked_dimensions, vector_hash = self._check_embedding(
                        tx, embedding, model, dimensions
                    )
                    existing = tx.execute(
                        "SELECT content_hash, tombstone, created_at, kind, source, provenance_json, metadata_json, observed_at, valid_from, valid_to, supersedes_id, content FROM semantic_items WHERE stable_id=?",
                        (stable_id,),
                    ).fetchone()
                    existing_chunk_rows = (
                        tx.execute(
                            "SELECT chunk_id, ordinal, content, content_hash, provenance_json FROM semantic_chunks WHERE stable_id=? ORDER BY ordinal",
                            (stable_id,),
                        ).fetchall()
                        if existing
                        else []
                    )
                    existing_chunks = [(row[0], int(row[1]), row[3], row[4]) for row in existing_chunk_rows]
                    content_same = bool(existing and existing[0] == content_hash)
                    effective_observed = (
                        existing[7] if existing and observed_at is None and content_same else observed
                    )
                    effective_valid_start = (
                        existing[8] if existing and valid_from is None and content_same else valid_start
                    )
                    effective_valid_to = (
                        existing[9] if existing and valid_to is None and content_same else valid_to
                    )
                    effective_supersedes_id = (
                        existing[10] if existing and supersedes_id is None and content_same else supersedes_id
                    )
                    effective_chunks = (
                        [
                            {
                                "chunk_id": row[0],
                                "ordinal": int(row[1]),
                                "content": row[2],
                                "content_hash": row[3],
                                "provenance_json": row[4],
                            }
                            for row in existing_chunk_rows
                        ]
                        if chunks is None and content_same
                        else prepared_chunks
                    )
                    chunks_match = existing_chunks == [
                        (item["chunk_id"], item["ordinal"], item["content_hash"], item["provenance_json"])
                        for item in effective_chunks
                    ]
                    effective_provenance_json = (
                        existing[5] if existing and provenance is None else provenance_json
                    )
                    effective_metadata_json = existing[6] if existing and metadata is None else metadata_json
                    supplied_embedding_match = True
                    if checked_model and checked_dimensions and vector_hash:
                        stored_embedding = tx.execute(
                            "SELECT dimensions, vector_hash FROM semantic_embeddings WHERE stable_id=? AND model=?",
                            (stable_id, checked_model),
                        ).fetchone()
                        supplied_embedding_match = bool(
                            stored_embedding
                            and int(stored_embedding[0]) == checked_dimensions
                            and stored_embedding[1] == vector_hash
                        )
                    base_fields_match = bool(
                        existing
                        and existing[0] == content_hash
                        and not existing[1]
                        and existing[3:]
                        == (
                            safe_kind,
                            safe_source,
                            effective_provenance_json,
                            effective_metadata_json,
                            effective_observed,
                            effective_valid_start,
                            effective_valid_to,
                            effective_supersedes_id,
                            normalized_content,
                        )
                    )
                    if base_fields_match and chunks_match and supplied_embedding_match:
                        return {
                            "schema": SEMANTIC_API_SCHEMA,
                            "status": "unchanged",
                            "stable_id": stable_id,
                            "content_hash": content_hash,
                            "capabilities": capabilities,
                        }
                    now = _now()
                    status = "inserted" if not existing else "revived" if existing[1] else "updated"
                    if existing and existing[0] != content_hash:
                        revision_id = f"{stable_id}:{existing[0]}"
                        tx.execute(
                            "INSERT OR REPLACE INTO semantic_revisions(revision_id, stable_id, content_hash, content, observed_at, superseded_by) VALUES (?, ?, ?, ?, ?, ?)",
                            (revision_id, stable_id, existing[0], existing[11], observed, content_hash),
                        )
                    tx.execute(
                        """INSERT INTO semantic_items(stable_id, kind, source, content, content_hash, provenance_json, metadata_json,
                           created_at, observed_at, valid_from, valid_to, supersedes_id, tombstone, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                           ON CONFLICT(stable_id) DO UPDATE SET kind=excluded.kind, source=excluded.source, content=excluded.content,
                           content_hash=excluded.content_hash, provenance_json=excluded.provenance_json, metadata_json=excluded.metadata_json,
                           observed_at=excluded.observed_at, valid_from=excluded.valid_from, valid_to=excluded.valid_to,
                           supersedes_id=excluded.supersedes_id, tombstone=0, updated_at=excluded.updated_at""",
                        (
                            stable_id,
                            safe_kind,
                            safe_source,
                            normalized_content,
                            content_hash,
                            effective_provenance_json,
                            effective_metadata_json,
                            existing[2] if existing else now,
                            effective_observed,
                            effective_valid_start,
                            effective_valid_to,
                            effective_supersedes_id,
                            now,
                        ),
                    )
                    tx.execute("DELETE FROM semantic_chunks WHERE stable_id=?", (stable_id,))
                    for chunk in effective_chunks:
                        tx.execute(
                            "INSERT INTO semantic_chunks(chunk_id, stable_id, ordinal, content, content_hash, provenance_json, tombstone) VALUES (?, ?, ?, ?, ?, ?, 0)",
                            (
                                chunk["chunk_id"],
                                stable_id,
                                chunk["ordinal"],
                                chunk["content"],
                                chunk["content_hash"],
                                chunk["provenance_json"],
                            ),
                        )
                    if existing and existing[0] != content_hash and not checked_model:
                        tx.execute("DELETE FROM semantic_embeddings WHERE stable_id=?", (stable_id,))
                    if checked_model and checked_dimensions and vector_hash:
                        tx.execute(
                            "INSERT INTO semantic_embeddings(stable_id, model, dimensions, vector_json, vector_hash, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(stable_id, model) DO UPDATE SET dimensions=excluded.dimensions, vector_json=excluded.vector_json, vector_hash=excluded.vector_hash, created_at=excluded.created_at",
                            (
                                stable_id,
                                checked_model,
                                checked_dimensions,
                                _canonical([float(value) for value in embedding or []]),
                                vector_hash,
                                now,
                            ),
                        )
                    provenance_id = f"{stable_id}:{content_hash}"
                    tx.execute(
                        "INSERT OR REPLACE INTO semantic_provenance(provenance_id, stable_id, source, source_hash, payload_json, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            provenance_id,
                            stable_id,
                            safe_source,
                            content_hash,
                            effective_provenance_json,
                            observed,
                        ),
                    )
        return {
            "schema": SEMANTIC_API_SCHEMA,
            "status": status,
            "stable_id": stable_id,
            "content_hash": content_hash,
            "source": safe_source,
            "capabilities": capabilities,
        }

    def tombstone(
        self, stable_id: str, *, reason: str = "deleted", provenance: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise SemanticStoreError("TOMBSTONE_INVALID")
        with StoreFileLock(self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}"):
            with self._open() as store:
                capabilities = self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    row = tx.execute(
                        "SELECT content_hash FROM semantic_items WHERE stable_id=?", (stable_id,)
                    ).fetchone()
                    if not row:
                        raise SemanticStoreError("ITEM_NOT_FOUND", stable_id)
                    now = _now()
                    payload = self._json_object(provenance, "provenance")
                    tx.execute(
                        "UPDATE semantic_items SET tombstone=1, updated_at=? WHERE stable_id=?",
                        (now, stable_id),
                    )
                    tx.execute("UPDATE semantic_chunks SET tombstone=1 WHERE stable_id=?", (stable_id,))
                    tx.execute(
                        "INSERT OR REPLACE INTO semantic_tombstones(stable_id, content_hash, reason, deleted_at, provenance_json) VALUES (?, ?, ?, ?, ?)",
                        (stable_id, row[0], _redact(reason), now, payload),
                    )
                    tx.execute(
                        "DELETE FROM semantic_relations WHERE source_id=? OR target_id=?",
                        (stable_id, stable_id),
                    )
                    tx.execute("DELETE FROM semantic_embeddings WHERE stable_id=?", (stable_id,))
        return {
            "schema": SEMANTIC_API_SCHEMA,
            "status": "tombstoned",
            "stable_id": stable_id,
            "capabilities": capabilities,
        }

    def delete(
        self, stable_id: str, *, reason: str = "deleted", provenance: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Tombstone an item while retaining its audit history."""

        return self.tombstone(stable_id, reason=reason, provenance=provenance)

    def upsert_relation(
        self,
        source_id: str,
        target_id: str,
        kind: str,
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not source_id or not target_id or not kind:
            raise SemanticStoreError("RELATION_INVALID")
        relation_id = _sha({"source_id": source_id, "target_id": target_id, "kind": kind})
        payload = self._json_object(provenance, "provenance")
        with StoreFileLock(self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}"):
            with self._open() as store:
                capabilities = self._ensure_ready(store)
                with transaction(store, "IMMEDIATE") as tx:
                    endpoint_count = tx.execute(
                        "SELECT COUNT(*) FROM semantic_items WHERE stable_id IN (?, ?) AND tombstone=0",
                        (source_id, target_id),
                    ).fetchone()[0]
                    if endpoint_count != 2:
                        raise SemanticStoreError("RELATION_ENDPOINT_MISSING")
                    tx.execute(
                        "INSERT INTO semantic_relations(relation_id, source_id, target_id, kind, provenance_json, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(source_id, target_id, kind) DO UPDATE SET provenance_json=excluded.provenance_json",
                        (relation_id, source_id, target_id, kind, payload, _now()),
                    )
        return {
            "schema": SEMANTIC_API_SCHEMA,
            "status": "upserted",
            "relation_id": relation_id,
            "capabilities": capabilities,
        }

    def _fts_rows(self, store: StoreConnection, query: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = store.execute(
                """SELECT f.stable_id, f.chunk_id, f.content, bm25(semantic_fts) AS rank,
                   i.source, i.content_hash, c.provenance_json, i.observed_at, i.updated_at
                   FROM semantic_fts f JOIN semantic_items i ON i.stable_id=f.stable_id
                   JOIN semantic_chunks c ON c.chunk_id=f.chunk_id
                   WHERE semantic_fts MATCH ? AND i.tombstone=0 ORDER BY rank, f.stable_id, f.chunk_id LIMIT ?""",
                (query, limit),
            ).fetchall()
        except sqlite3.Error as error:
            raise SemanticStoreError("QUERY_INVALID", str(error)) from error
        return [
            {
                "stable_id": row[0],
                "chunk_id": row[1],
                "snippet": row[2],
                "fts_score": _fts_score(float(row[3])),
                "source": row[4],
                "content_hash": row[5],
                "provenance": json.loads(row[6]),
                "observed_at": row[7],
                "updated_at": row[8],
            }
            for row in rows
        ]

    def recall(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        limit: int = 10,
        query_embedding: Sequence[float] | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> dict[str, Any]:
        if mode not in {"fts", "vector", "hybrid"}:
            raise SemanticStoreError("MODE_INVALID", mode)
        if limit < 1 or limit > 1000:
            raise SemanticStoreError("LIMIT_INVALID")
        if not isinstance(query, str) or len(query) > _MAX_QUERY_CHARS:
            raise SemanticStoreError("QUERY_LIMIT")
        safe_query = _redact(query)
        with self._open(read_only=True) as store:
            capabilities = self._capabilities(store)
            if mode in {"fts", "hybrid"} and not capabilities["fts5"]:
                if mode == "fts":
                    raise SemanticStoreError("FTS5_UNAVAILABLE")
            fts = (
                self._fts_rows(store, safe_query, limit * 4)
                if mode in {"fts", "hybrid"} and capabilities["fts5"]
                else []
            )
            vector = query_embedding
            active_model = store.execute(
                "SELECT model, dimensions FROM semantic_models WHERE active=1 ORDER BY model LIMIT 1"
            ).fetchone()
            if vector is not None:
                if not model and active_model:
                    model, dimensions = str(active_model[0]), int(active_model[1])
                if not model and not active_model:
                    raise SemanticStoreError("EMBEDDING_MODEL_REQUIRED")
                if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
                    raise SemanticStoreError("EMBEDDING_INVALID")
                if len(vector) < 1 or len(vector) > _MAX_EMBEDDING_DIMENSIONS:
                    raise SemanticStoreError("EMBEDDING_LIMIT")
                if active_model and model != active_model[0]:
                    raise SemanticStoreError("EMBEDDING_MODEL_MISMATCH")
                if active_model and len(vector) != int(active_model[1]):
                    raise SemanticStoreError("EMBEDDING_DIMENSION_MISMATCH")
            if mode in {"vector", "hybrid"} and vector is None:
                row = active_model
                if row and (model is None or model == row[0]):
                    model, dimensions = str(row[0]), int(row[1])
                    vector = _deterministic_embedding(safe_query, dimensions)
            vector_rows: dict[str, float] = {}
            if vector is not None:
                if dimensions is not None and len(vector) != dimensions:
                    raise SemanticStoreError("EMBEDDING_DIMENSION_MISMATCH")
                rows = store.execute(
                    "SELECT e.stable_id, e.vector_json FROM semantic_embeddings e JOIN semantic_items i ON i.stable_id=e.stable_id WHERE i.tombstone=0 AND (? IS NULL OR e.model=?)",
                    (model, model),
                ).fetchall()
                for stable_id, vector_json in rows:
                    vector_rows[str(stable_id)] = _cosine(vector, json.loads(vector_json))
            by_id: dict[str, dict[str, Any]] = {}
            for row in fts:
                by_id.setdefault(row["stable_id"], row)
            for stable_id, score in vector_rows.items():
                by_id.setdefault(stable_id, {"stable_id": stable_id})["vector_score"] = round(score, 8)
            for row in by_id.values():
                row.setdefault("fts_score", 0.0)
                row.setdefault("vector_score", 0.0)
                if "source" not in row:
                    source = store.execute(
                        "SELECT source, content_hash, provenance_json, observed_at, updated_at FROM semantic_items WHERE stable_id=?",
                        (row["stable_id"],),
                    ).fetchone()
                    if source:
                        row.update(
                            {
                                "source": source[0],
                                "content_hash": source[1],
                                "provenance": json.loads(source[2]),
                                "observed_at": source[3],
                                "updated_at": source[4],
                            }
                        )
                row["hybrid_score"] = round(
                    (row["fts_score"] + row["vector_score"]) / 2.0
                    if row["fts_score"] and row["vector_score"]
                    else max(row["fts_score"], row["vector_score"]),
                    8,
                )
            score_key = {"fts": "fts_score", "vector": "vector_score", "hybrid": "hybrid_score"}[mode]
            results = sorted(
                by_id.values(),
                key=lambda row: (-row.get(score_key, 0.0), row["stable_id"], row.get("chunk_id", "")),
            )[:limit]
        return {
            "schema": SEMANTIC_API_SCHEMA,
            "query": safe_query,
            "mode": mode,
            "method": (
                "fts5"
                if mode == "fts"
                else "brute-force"
                if mode == "vector" or (mode == "hybrid" and not capabilities["fts5"])
                else "hybrid"
            ),
            "ann_claimed": False,
            "results": results,
            "capabilities": capabilities,
        }

    def rebuild(self) -> dict[str, Any]:
        with StoreFileLock(self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}"):
            with self._open() as store:
                capabilities = self._ensure_ready(store)
                if not capabilities["fts5"]:
                    raise SemanticStoreError("FTS5_UNAVAILABLE")
                with transaction(store, "EXCLUSIVE") as tx:
                    tx.execute("DELETE FROM semantic_fts")
                    tx.execute(
                        "INSERT INTO semantic_fts(stable_id, chunk_id, content) SELECT stable_id, chunk_id, content FROM semantic_chunks WHERE tombstone=0"
                    )
                    count = tx.execute("SELECT COUNT(*) FROM semantic_fts").fetchone()[0]
        return {
            "schema": SEMANTIC_API_SCHEMA,
            "status": "rebuilt",
            "fts_rows": int(count),
            "capabilities": capabilities,
        }

    def verify(self) -> dict[str, Any]:
        with StoreFileLock(self.lock_path, owner=f"{self.writer.component}:{self.writer.instance_id}"):
            with self._open(read_only=True) as store:
                capabilities = self._capabilities(store)
                try:
                    item_count = int(
                        store.execute("SELECT COUNT(*) FROM semantic_items WHERE tombstone=0").fetchone()[0]
                    )
                    tombstone_count = int(
                        store.execute("SELECT COUNT(*) FROM semantic_tombstones").fetchone()[0]
                    )
                    orphan_chunks = int(
                        store.execute(
                            "SELECT COUNT(*) FROM semantic_chunks c LEFT JOIN semantic_items i ON i.stable_id=c.stable_id WHERE i.stable_id IS NULL"
                        ).fetchone()[0]
                    )
                    fts_count = (
                        int(store.execute("SELECT COUNT(*) FROM semantic_fts").fetchone()[0])
                        if capabilities["fts5"]
                        else None
                    )
                    orphan_fts = (
                        int(
                            store.execute(
                                "SELECT COUNT(*) FROM semantic_fts f LEFT JOIN semantic_chunks c ON c.chunk_id=f.chunk_id WHERE c.chunk_id IS NULL OR c.tombstone=1"
                            ).fetchone()[0]
                        )
                        if capabilities["fts5"]
                        else 0
                    )
                    fts_mismatch = (
                        int(
                            store.execute(
                                """SELECT COUNT(*) FROM semantic_fts f
                                   LEFT JOIN semantic_chunks c ON c.chunk_id=f.chunk_id
                                   WHERE c.chunk_id IS NULL OR c.tombstone=1
                                      OR f.stable_id != c.stable_id OR f.content != c.content"""
                            ).fetchone()[0]
                        )
                        if capabilities["fts5"]
                        else 0
                    )
                    missing_fts = (
                        int(
                            store.execute(
                                """SELECT COUNT(*) FROM semantic_chunks c
                                   LEFT JOIN semantic_fts f ON f.chunk_id=c.chunk_id
                                   WHERE c.tombstone=0 AND f.chunk_id IS NULL"""
                            ).fetchone()[0]
                        )
                        if capabilities["fts5"]
                        else 0
                    )
                except sqlite3.Error as error:
                    return {
                        "schema": SEMANTIC_API_SCHEMA,
                        "valid": False,
                        "reason_code": "SEMANTIC_SCHEMA_INVALID",
                        "items": 0,
                        "tombstones": 0,
                        "fts_rows": None,
                        "orphan_fts": 0,
                        "capabilities": capabilities,
                        "error": str(error),
                    }
        valid = orphan_chunks == 0 and orphan_fts == 0 and fts_mismatch == 0 and missing_fts == 0
        return {
            "schema": SEMANTIC_API_SCHEMA,
            "valid": valid,
            "reason_code": None if valid else "INDEX_OUT_OF_SYNC",
            "items": item_count,
            "tombstones": tombstone_count,
            "fts_rows": fts_count,
            "orphan_fts": orphan_fts,
            "capabilities": capabilities,
        }

    def _live_chunk_count(self) -> int:
        with self._open(read_only=True) as store:
            return int(store.execute("SELECT COUNT(*) FROM semantic_chunks WHERE tombstone=0").fetchone()[0])


__all__ = ["SEMANTIC_API_SCHEMA", "SEMANTIC_SCHEMA", "SemanticStore", "SemanticStoreError"]
