"""Unify ecosystem memory onto a single MapperStore SQLite (memory.sqlite).

Policy (always-on):
- Canonical SoT: ``$SIMPLICIO_DATA_DIR/memory.sqlite`` (MapperStore schema).
- Legacy neural ``simplicio-memory.sqlite`` is an absorb/import source only.
- FTS5 (semantic_fts) is mandatory after unify; sqlite-vec remains optional.
- ``unify_memory`` is idempotent: re-run is safe and fills gaps.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import MemoryStore
from .paths import resolve_store_location

UNIFY_API_SCHEMA = "simplicio.mapper-store.memory-unify/v1"
CANONICAL_DB_NAME = "memory.sqlite"
LEGACY_NEURAL_DB_NAME = "simplicio-memory.sqlite"
POINTER_NAME = "CANONICAL_MEMORY.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _resolve_root(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
):
    return resolve_store_location(
        data_dir=data_dir,
        environ=environ,
        home=Path.home(),
        allow_temp=False,
    )


def canonical_memory_path(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    return _resolve_root(data_dir=data_dir, environ=environ).database(CANONICAL_DB_NAME)


def legacy_neural_path(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    return _resolve_root(data_dir=data_dir, environ=environ).database(LEGACY_NEURAL_DB_NAME)


def env_hints(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    location = _resolve_root(data_dir=data_dir, environ=environ)
    root = str(location.root)
    canonical = str(location.database(CANONICAL_DB_NAME))
    return {
        "SIMPLICIO_DATA_DIR": root,
        # Canonical SoT for Runtime/MCP/memory tools (MapperStore file).
        "SIMPLICIO_MEMORY_DB": canonical,
        "SIMPLICIO_MAPPER_MEMORY_DB": canonical,
    }


def _schema_ready(db_path: Path) -> bool:
    """True when MapperStore meta tables already exist (no writer lock needed)."""
    if not db_path.is_file():
        return False
    try:
        with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
            conn.execute("SELECT 1 FROM memory_store_meta WHERE key='schema'").fetchone()
            conn.execute("SELECT 1 FROM semantic_store_meta LIMIT 1").fetchone()
            return True
    except sqlite3.Error:
        return False


def ensure_canonical_schema(db_path: Path) -> dict[str, Any]:
    """Create MapperStore schema if missing (idempotent).

    Skips exclusive initialize when schema is already present so Runtime/MCP
    concurrent readers do not trip Windows lock contention.
    """
    db_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if _schema_ready(db_path):
        return {"database": str(db_path), "init": {"ok": True, "skipped": "schema_ready"}}
    markdown_root = db_path.parent / "memory-markdown"
    markdown_root.mkdir(parents=True, exist_ok=True)
    try:
        report = MemoryStore(db_path, markdown_root=markdown_root).initialize()
        return {"database": str(db_path), "init": report if isinstance(report, dict) else {"ok": True}}
    except Exception as error:  # noqa: BLE001 — degrade if locked; status still useful
        if _schema_ready(db_path):
            return {
                "database": str(db_path),
                "init": {"ok": True, "skipped": "schema_ready_after_lock", "lock_error": str(error)},
            }
        raise


def _count(conn: sqlite3.Connection, sql: str) -> int:
    try:
        return int(conn.execute(sql).fetchone()[0])
    except sqlite3.Error:
        return 0


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def bridge_neural_into_canonical(
    *,
    canonical: Path,
    neural: Path,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Import memory_items from legacy neural DB into MapperStore tables.

    Idempotent via INSERT OR IGNORE / ON CONFLICT upsert on stable_id.
    """
    if not neural.is_file():
        return {
            "status": "skipped",
            "reason": "NEURAL_MISSING",
            "neural": str(neural),
            "imported": 0,
        }
    if not canonical.is_file():
        ensure_canonical_schema(canonical)

    src = sqlite3.connect(f"file:{neural.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(canonical)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.execute("PRAGMA busy_timeout=10000")
    dst.execute("PRAGMA foreign_keys=ON")

    if not _table_exists(src, "memory_items"):
        src.close()
        dst.close()
        return {
            "status": "skipped",
            "reason": "NO_MEMORY_ITEMS_TABLE",
            "neural": str(neural),
            "imported": 0,
        }

    source_total = _count(src, "SELECT COUNT(*) FROM memory_items")
    before_entries = _count(dst, "SELECT COUNT(*) FROM memory_entries")
    before_semantic = _count(dst, "SELECT COUNT(*) FROM semantic_items WHERE tombstone=0")

    # Fast path: already bridged (avoid re-walking 37k+ rows under locks).
    if (
        source_total > 0
        and before_semantic >= source_total
        and before_entries >= source_total
    ):
        src.close()
        dst.close()
        return {
            "status": "unchanged",
            "neural": str(neural),
            "canonical": str(canonical),
            "source_items": source_total,
            "rows_processed": 0,
            "errors": 0,
            "error_samples": [],
            "memory_entries_before": before_entries,
            "memory_entries_after": before_entries,
            "semantic_items_before": before_semantic,
            "semantic_items_after": before_semantic,
            "fts": "skipped_already_synced",
        }

    src_cols = {
        str(r[1])
        for r in src.execute("PRAGMA table_info(memory_items)").fetchall()
    }

    def col(row: sqlite3.Row, name: str, default: Any = None) -> Any:
        if name not in src_cols:
            return default
        try:
            value = row[name]
        except (IndexError, KeyError):
            return default
        return default if value is None else value

    # Select only columns that exist (minimal test DBs omit optional fields).
    preferred = (
        "stable_id",
        "kind",
        "source",
        "title",
        "content",
        "artifact_path",
        "source_hash",
        "metadata",
        "provenance",
        "tags",
        "created_at",
        "updated_at",
    )
    select_cols = [c for c in preferred if c in src_cols]
    if "stable_id" not in select_cols or "content" not in select_cols:
        src.close()
        dst.close()
        return {
            "status": "skipped",
            "reason": "NEURAL_SCHEMA_INCOMPLETE",
            "neural": str(neural),
            "columns": sorted(src_cols),
            "imported": 0,
        }
    q = f"SELECT {', '.join(select_cols)} FROM memory_items"
    cursor = src.execute(q)
    imported = 0
    errors = 0
    error_samples: list[str] = []

    while True:
        chunk = cursor.fetchmany(batch_size)
        if not chunk:
            break
        for row in chunk:
            try:
                content = col(row, "content", "") or ""
                kind = str(col(row, "kind", "note") or "note")[:64]
                source = str(col(row, "source", "neural-import") or "neural-import")[:256]
                stable_id = col(row, "stable_id") or _sha(f"{kind}:{source}:{content[:200]}")
                content_hash = col(row, "source_hash") or _sha(content)
                title = col(row, "title", "") or ""
                tags = col(row, "tags", "") or ""
                tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
                tags_json = json.dumps(tag_list, ensure_ascii=False)
                meta_raw = col(row, "metadata")
                if not meta_raw:
                    meta = json.dumps(
                        {"title": title, "imported_from": LEGACY_NEURAL_DB_NAME},
                        ensure_ascii=False,
                    )
                else:
                    try:
                        parsed = json.loads(meta_raw)
                        if isinstance(parsed, dict):
                            parsed.setdefault("title", title)
                            parsed.setdefault("imported_from", LEGACY_NEURAL_DB_NAME)
                            meta = json.dumps(parsed, ensure_ascii=False)
                        else:
                            meta = json.dumps(
                                {
                                    "title": title,
                                    "imported_from": LEGACY_NEURAL_DB_NAME,
                                },
                                ensure_ascii=False,
                            )
                    except json.JSONDecodeError:
                        meta = json.dumps(
                            {"title": title, "imported_from": LEGACY_NEURAL_DB_NAME},
                            ensure_ascii=False,
                        )
                prov = col(row, "provenance", "{}") or "{}"
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                observed = col(row, "updated_at") or col(row, "created_at") or stamp
                created = col(row, "created_at") or observed
                artifact_path = col(row, "artifact_path")

                dst.execute(
                    """
                    INSERT INTO memory_entries(
                        stable_id, topic, content, content_hash, source, source_path, source_hash,
                        actor, tags_json, metadata_json, consent_json, retention_until, observed_at,
                        created_at, supersedes_id, tombstone)
                    VALUES (?,?,?,?,?,?,?,'neural-bridge',?,?, '{}', NULL, ?, ?, NULL, 0)
                    ON CONFLICT(stable_id) DO UPDATE SET
                        topic=excluded.topic, content=excluded.content,
                        content_hash=excluded.content_hash, source=excluded.source,
                        source_path=excluded.source_path, source_hash=excluded.source_hash,
                        tags_json=excluded.tags_json, metadata_json=excluded.metadata_json,
                        observed_at=excluded.observed_at, tombstone=0
                    """,
                    (
                        stable_id,
                        kind,
                        content,
                        content_hash,
                        source,
                        artifact_path,
                        content_hash,
                        tags_json,
                        meta,
                        observed,
                        created,
                    ),
                )
                dst.execute(
                    """
                    INSERT INTO semantic_items(
                        stable_id, kind, source, content, content_hash, provenance_json, metadata_json,
                        created_at, observed_at, valid_from, valid_to, supersedes_id, tombstone, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?, NULL, NULL, 0, ?)
                    ON CONFLICT(stable_id) DO UPDATE SET
                        kind=excluded.kind, source=excluded.source, content=excluded.content,
                        content_hash=excluded.content_hash, provenance_json=excluded.provenance_json,
                        metadata_json=excluded.metadata_json, observed_at=excluded.observed_at,
                        valid_from=excluded.valid_from, valid_to=NULL, tombstone=0,
                        updated_at=excluded.updated_at
                    """,
                    (
                        stable_id,
                        kind,
                        source,
                        content,
                        content_hash,
                        prov,
                        meta,
                        created,
                        observed,
                        observed,
                        observed,
                    ),
                )
                dst.execute("DELETE FROM semantic_chunks WHERE stable_id=?", (stable_id,))
                dst.execute(
                    """
                    INSERT INTO semantic_chunks(
                        chunk_id, stable_id, ordinal, content, content_hash, provenance_json, tombstone)
                    VALUES (?,?,0,?,?,'{}',0)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        content=excluded.content, content_hash=excluded.content_hash, tombstone=0
                    """,
                    (f"{stable_id}:0", stable_id, content, content_hash),
                )
                imported += 1
            except Exception as error:  # noqa: BLE001 — continue import; report samples
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append(str(error))
        dst.commit()

    fts_status = "skipped"
    if _table_exists(dst, "semantic_fts"):
        try:
            dst.execute("INSERT INTO semantic_fts(semantic_fts) VALUES('rebuild')")
            dst.commit()
            fts_status = "rebuild_ok"
        except sqlite3.Error as error:
            fts_status = f"rebuild_failed:{error}"

    after_entries = _count(dst, "SELECT COUNT(*) FROM memory_entries")
    after_semantic = _count(dst, "SELECT COUNT(*) FROM semantic_items WHERE tombstone=0")
    src.close()
    dst.close()

    return {
        "status": "bridged" if imported else "unchanged",
        "neural": str(neural),
        "canonical": str(canonical),
        "source_items": source_total,
        "rows_processed": imported,
        "errors": errors,
        "error_samples": error_samples,
        "memory_entries_before": before_entries,
        "memory_entries_after": after_entries,
        "semantic_items_before": before_semantic,
        "semantic_items_after": after_semantic,
        "fts": fts_status,
    }


def _write_pointer(root: Path, canonical: Path) -> str:
    pointer = root / POINTER_NAME
    body = (
        "# Canonical Simplicio memory SoT (MapperStore)\n"
        f"path={canonical}\n"
        f"schema=simplicio.mapper-store.memory/v1\n"
        f"updated_at={_now()}\n"
        "policy=single-sqlite; FTS5 mandatory; sqlite-vec optional\n"
        f"legacy_neural={LEGACY_NEURAL_DB_NAME} is absorb-only after unify\n"
        f"export SIMPLICIO_MEMORY_DB={canonical}\n"
        f"export SIMPLICIO_DATA_DIR={root}\n"
    )
    pointer.write_text(body, encoding="utf-8")
    return str(pointer)


def unify_memory(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    absorb_legacy_home: bool = True,
    rebuild_fts: bool = True,
) -> dict[str, Any]:
    """Ensure single canonical memory.sqlite is ready, loaded, and searchable.

    Steps:
    1. Ensure MapperStore schema on memory.sqlite
    2. Optionally absorb ~/.simplicio/memory/simplicio-memory.sqlite if present
    3. Bridge legacy neural file into canonical MapperStore tables
    4. Rebuild FTS5
    5. Write pointer + env hints
    """
    location = _resolve_root(data_dir=data_dir, environ=environ)
    location.ensure_root()
    canonical = location.database(CANONICAL_DB_NAME)
    neural = location.database(LEGACY_NEURAL_DB_NAME)

    schema_report = ensure_canonical_schema(canonical)

    absorb_report = None
    if absorb_legacy_home:
        home_neural = Path.home() / ".simplicio" / "memory" / LEGACY_NEURAL_DB_NAME
        if home_neural.is_file():
            # Prefer hub copy; refresh from home if hub missing or smaller
            if (not neural.is_file()) or home_neural.stat().st_size > neural.stat().st_size * 0.9:
                from .neural.bank import absorb_runtime_neural

                try:
                    absorb_report = absorb_runtime_neural(
                        source=home_neural,
                        data_dir=location.root,
                        backup=True,
                    )
                except Exception as error:  # noqa: BLE001
                    absorb_report = {"status": "absorb_error", "error": str(error)}

    bridge_report = bridge_neural_into_canonical(canonical=canonical, neural=neural)

    if rebuild_fts and bridge_report.get("fts") not in {"rebuild_ok"}:
        with closing(sqlite3.connect(canonical)) as conn:
            if _table_exists(conn, "semantic_fts"):
                try:
                    conn.execute("INSERT INTO semantic_fts(semantic_fts) VALUES('rebuild')")
                    conn.commit()
                    bridge_report["fts"] = "rebuild_ok"
                except sqlite3.Error as error:
                    bridge_report["fts"] = f"rebuild_failed:{error}"

    with closing(sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower()
        entries = _count(conn, "SELECT COUNT(*) FROM memory_entries")
        semantic = _count(conn, "SELECT COUNT(*) FROM semantic_items WHERE tombstone=0")
        fts_rows = 0
        if _table_exists(conn, "semantic_fts"):
            # content-table FTS may not support COUNT the same way; try
            try:
                fts_rows = _count(conn, "SELECT COUNT(*) FROM semantic_fts")
            except sqlite3.Error:
                fts_rows = -1

    ready = integrity == "ok" and semantic > 0 and entries > 0
    pointer = _write_pointer(location.root, canonical)
    hints = env_hints(data_dir=location.root)

    # Persist unify receipt next to data root for agents/other projects
    receipt = {
        "schema": UNIFY_API_SCHEMA,
        "status": "ready" if ready else "degraded",
        "data_root": str(location.root),
        "canonical_database": str(canonical),
        "legacy_neural_database": str(neural) if neural.is_file() else None,
        "integrity": integrity,
        "memory_entries": entries,
        "semantic_items": semantic,
        "fts_rows": fts_rows,
        "fts": bridge_report.get("fts"),
        "schema_init": schema_report,
        "absorb": absorb_report,
        "bridge": bridge_report,
        "pointer": pointer,
        "env_hints": hints,
        "policy": {
            "sot": CANONICAL_DB_NAME,
            "legacy_neural": "absorb_and_bridge_only",
            "fts5": "mandatory",
            "sqlite_vec": "optional_same_file",
        },
        "occurred_at": _now(),
    }
    receipt_path = location.root / "memory-unify-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt["receipt"] = str(receipt_path)
    return receipt


def unify_status(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    location = _resolve_root(data_dir=data_dir, environ=environ)
    canonical = location.database(CANONICAL_DB_NAME)
    neural = location.database(LEGACY_NEURAL_DB_NAME)
    if not canonical.is_file():
        return {
            "schema": UNIFY_API_SCHEMA,
            "status": "missing",
            "canonical_database": str(canonical),
            "data_root": str(location.root),
            "env_hints": env_hints(data_dir=location.root),
        }
    with closing(sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower()
        entries = _count(conn, "SELECT COUNT(*) FROM memory_entries")
        semantic = _count(conn, "SELECT COUNT(*) FROM semantic_items WHERE tombstone=0")
        fts_ok = _table_exists(conn, "semantic_fts")
    neural_items = 0
    if neural.is_file():
        try:
            with closing(sqlite3.connect(f"file:{neural.as_posix()}?mode=ro", uri=True)) as conn:
                if _table_exists(conn, "memory_items"):
                    neural_items = _count(conn, "SELECT COUNT(*) FROM memory_items")
        except sqlite3.Error:
            neural_items = -1
    in_sync = semantic >= neural_items if neural_items >= 0 else True
    ready = integrity == "ok" and semantic > 0 and fts_ok
    return {
        "schema": UNIFY_API_SCHEMA,
        "status": "ready" if ready and in_sync else ("drift" if ready else "degraded"),
        "data_root": str(location.root),
        "canonical_database": str(canonical),
        "legacy_neural_database": str(neural) if neural.is_file() else None,
        "integrity": integrity,
        "memory_entries": entries,
        "semantic_items": semantic,
        "legacy_neural_items": neural_items,
        "in_sync_with_legacy": in_sync,
        "fts5": fts_ok,
        "env_hints": env_hints(data_dir=location.root),
        "occurred_at": _now(),
    }


__all__ = [
    "UNIFY_API_SCHEMA",
    "CANONICAL_DB_NAME",
    "LEGACY_NEURAL_DB_NAME",
    "bridge_neural_into_canonical",
    "canonical_memory_path",
    "env_hints",
    "ensure_canonical_schema",
    "legacy_neural_path",
    "unify_memory",
    "unify_status",
]
