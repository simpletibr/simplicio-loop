"""Bootstrap, migrate, seed and absorb the neural SQLite bank into Mapper data root."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..paths import resolve_store_location

NEURAL_API_SCHEMA = "simplicio.mapper-store.neural/v1"
NEURAL_DB_NAME = "simplicio-memory.sqlite"
_ASSETS = Path(__file__).resolve().parent / "assets"
_MIGRATIONS_DIR = _ASSETS / "migrations"
_SEEDS_DIR = _ASSETS / "seeds"
_SEED_PART = re.compile(r"^part-([0-9]+)\.sql$")
_SCHEMA = _ASSETS / "memory-schema.sql"

# Runtime catalog order (matches crates/simplicio-memory store bootstrap).
_MIGRATION_ORDER = (
    "0001_initial",
    "0002_conversation_feedback_loop",
    "0003_expanded_kinds_and_gates",
    "0004_skills_registry",
    "0005_wesley_operating_memory",
    "0006_orca_absorption",
    "0007_skill_capability_index",
    "0008_skill_capability_index_unique",
    "0009_snake_benchmark_baseline",
    "0010_claude-code_absorption",
    "0011_codex_absorption",
    "0012_cursor_absorption",
    "0013_vscode_absorption",
    "0014_hermes_absorption",
    "0015_gemini-cli_absorption",
    "0016_kiro_absorption",
    "0017_antigravity_absorption",
    "0018_seed_provenance",
)


class NeuralBankError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_neural_root(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
):
    """Resolve Mapper data root; default home/data when env unset (CLI contract)."""
    return resolve_store_location(
        data_dir=data_dir,
        environ=environ,
        home=Path.home(),
        allow_temp=False,
    )


def neural_database_path(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    """Canonical neural DB path under Mapper data root."""
    location = _resolve_neural_root(data_dir=data_dir, environ=environ)
    return location.database(NEURAL_DB_NAME)


def _strip_transaction_wrappers(sql: str) -> str:
    cleaned = []
    for line in sql.splitlines():
        upper = line.strip().upper()
        if upper in set(['BEGIN;', 'COMMIT;', 'BEGIN TRANSACTION;']):
            continue
        if 'ADD COLUMN IF NOT EXISTS' in upper:
            line = re.sub(r'ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS', 'ADD COLUMN', line, flags=re.I)
        cleaned.append(line)
    return chr(10).join(cleaned)


def _seed_parts() -> list[Path]:
    """Packaged seed parts (part-01.sql, part-02.sql, ...) in load order.

    The numbering must be contiguous from 01: a gap means a part is missing and loading the rest
    would silently produce a partial seed, so it fails closed instead.
    """
    if not _SEEDS_DIR.is_dir():
        return []
    found: dict[int, Path] = {}
    for path in _SEEDS_DIR.iterdir():
        match = _SEED_PART.match(path.name)
        if not match:
            continue
        number = int(match.group(1))
        # Only the canonical two-digit name: `part-1.sql` would otherwise be dropped silently and
        # the seed would load partially. The canonical name is unique per number, so no duplicate.
        if path.name != f"part-{number:02d}.sql":
            raise NeuralBankError("SEEDS_INVALID", f"non-canonical or duplicate seed part {path.name}")
        found[number] = path
    if not found:
        return []
    missing = sorted(set(range(1, max(found) + 1)) - set(found))
    if missing:
        raise NeuralBankError("SEEDS_INCOMPLETE", f"missing part numbers {missing} in {_SEEDS_DIR}")
    return [found[number] for number in sorted(found)]


def _migration_files() -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        stem = path.stem
        found[stem] = path
    ordered: list[tuple[str, Path]] = []
    for mid in _MIGRATION_ORDER:
        if mid in found:
            ordered.append((mid, found[mid]))
    # include any extra numbered migrations not in the catalog
    for stem, path in sorted(found.items()):
        if stem not in _MIGRATION_ORDER and re.match(r"^\d{4}_", stem):
            ordered.append((stem, path))
    return ordered



def _is_idempotent_schema_error(error: BaseException) -> bool:
    msg = str(error).lower()
    return (
        "duplicate column" in msg
        or "already exists" in msg
        or "duplicate column name" in msg
    )


def _exec_statements_tolerant(conn: sqlite3.Connection, sql: str) -> None:
    """Run SQL statement-wise; ignore duplicate-column / already-exists errors."""
    buf: list[str] = []
    in_trigger = False
    for line in sql.splitlines():
        upper = line.strip().upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        buf.append(line)
        finished = False
        if in_trigger and (upper == "END;" or upper.endswith("END;")):
            finished = True
            in_trigger = False
        elif (not in_trigger) and upper.endswith(";") and not upper.startswith("--"):
            finished = True
        if not finished:
            continue
        stmt = "\n".join(buf).strip()
        buf = []
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as error:
            if _is_idempotent_schema_error(error):
                continue
            raise
    if buf:
        stmt = "\n".join(buf).strip()
        if not stmt:
            return
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as error:
            if not _is_idempotent_schema_error(error):
                raise


def _exec_migration(conn: sqlite3.Connection, sql: str) -> None:
    """Apply one migration file. Prefer executescript; fall back if schema drift."""
    try:
        conn.executescript(sql)
        return
    except sqlite3.OperationalError as error:
        if not _is_idempotent_schema_error(error):
            raise
    _exec_statements_tolerant(conn, sql)

def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply pending SQL migrations idempotently; return applied ids this call."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied: list[str] = []
    for mid, path in _migration_files():
        row = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE id = ?", (mid,)
        ).fetchone()
        if row:
            continue
        sql = _strip_transaction_wrappers(path.read_text(encoding="utf-8"))
        try:
            _exec_migration(conn, sql)
        except sqlite3.Error as error:
            raise NeuralBankError("MIGRATION_FAILED", f"{mid}: {error}") from error
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(id) VALUES (?)",
            (mid,),
        )
        applied.append(mid)
    return applied


def bootstrap_neural(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    apply_seeds: bool = False,
) -> dict[str, Any]:
    """Create Mapper-owned neural DB, apply migrations, optionally load seeds."""
    location = _resolve_neural_root(data_dir=data_dir, environ=environ)
    location.ensure_root()
    db_path = location.database(NEURAL_DB_NAME)
    created = not db_path.is_file()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=3000")
        applied = apply_migrations(conn)
        seed_report = None
        if apply_seeds and _seed_parts():
            seed_report = seed_neural(conn)
        conn.commit()
        migrations = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM schema_migrations ORDER BY id"
            ).fetchall()
        ]
        item_count = 0
        try:
            item_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            )
        except sqlite3.Error:
            item_count = 0
    return {
        "schema": NEURAL_API_SCHEMA,
        "status": "ready",
        "database": str(db_path),
        "data_root": str(location.root),
        "source": location.source,
        "created": created,
        "migrations_applied_now": applied,
        "migrations_present": migrations,
        "memory_items": item_count,
        "seeds": seed_report,
        "assets": {
            "migrations_dir": str(_MIGRATIONS_DIR),
            "seeds": str(_SEEDS_DIR) if _seed_parts() else None,
            "memory_schema": str(_SCHEMA) if _SCHEMA.is_file() else None,
        },
        "occurred_at": _now(),
    }


def seed_neural(conn: sqlite3.Connection) -> dict[str, Any]:
    """Load the packaged seed parts in order (INSERT OR IGNORE).

    Parts are cut at statement boundaries, so each one runs on its own and the sequence is the
    same statements in the same order as one file. `sha256` is over the concatenated bytes.
    """
    parts = _seed_parts()
    if not parts:
        raise NeuralBankError("SEEDS_MISSING", str(_SEEDS_DIR))
    before = 0
    try:
        before = int(conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0])
    except sqlite3.Error:
        before = 0
    digest = hashlib.sha256()
    for part in parts:
        data = part.read_bytes()
        digest.update(data)
        sql = _strip_transaction_wrappers(data.decode("utf-8"))
        try:
            conn.executescript(sql)
        except sqlite3.Error as error:
            raise NeuralBankError("SEED_FAILED", f"{part.name}: {error}") from error
    after = int(conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0])
    return {
        "path": str(_SEEDS_DIR),
        "parts": [part.name for part in parts],
        "items_before": before,
        "items_after": after,
        "sha256": digest.hexdigest(),
    }


def absorb_runtime_neural(
    *,
    source: str | Path | None = None,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    backup: bool = True,
) -> dict[str, Any]:
    """Copy Runtime neural DB into Mapper data root (centralizer).

    Default source: ~/.simplicio-loop/memory/simplicio-memory.sqlite
    Destination: <SIMPLICIO_DATA_DIR or ~/data>/simplicio-memory.sqlite
    """
    env = os.environ if environ is None else environ
    if source is None:
        home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
        source_path = home / ".simplicio-loop" / "memory" / "simplicio-memory.sqlite"
    else:
        source_path = Path(source).expanduser().absolute()
    if not source_path.is_file():
        raise NeuralBankError("SOURCE_MISSING", str(source_path))

    location = _resolve_neural_root(data_dir=data_dir, environ=environ)
    location.ensure_root()
    dest = location.database(NEURAL_DB_NAME)
    backup_path = None
    if backup and dest.is_file():
        backup_path = dest.with_name(f"{dest.stem}.backup.{uuid4().hex[:8]}{dest.suffix}")
        shutil.copy2(dest, backup_path)

    # Verified sqlite backup API when possible (atomic-ish), else file copy.
    with closing(sqlite3.connect(source_path)) as src, closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)
        dst.commit()
        integrity = str(dst.execute("PRAGMA quick_check").fetchone()[0]).lower()
        if integrity != "ok":
            raise NeuralBankError("ABSORB_CORRUPT", integrity)
        # ensure migrations catalog is present after import
        applied = apply_migrations(dst)
        dst.commit()
        item_count = 0
        try:
            item_count = int(dst.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0])
        except sqlite3.Error:
            item_count = 0
        migrations = [
            r[0]
            for r in dst.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
        ]

    return {
        "schema": NEURAL_API_SCHEMA,
        "status": "absorbed",
        "source": str(source_path),
        "source_sha256": _sha256_file(source_path),
        "destination": str(dest),
        "destination_sha256": _sha256_file(dest),
        "backup": str(backup_path) if backup_path else None,
        "data_root": str(location.root),
        "memory_items": item_count,
        "migrations_present": migrations,
        "migrations_applied_now": applied,
        "occurred_at": _now(),
    }


def neural_status(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    location = _resolve_neural_root(data_dir=data_dir, environ=environ)
    db_path = location.database(NEURAL_DB_NAME)
    if not db_path.is_file():
        return {
            "schema": NEURAL_API_SCHEMA,
            "status": "missing",
            "database": str(db_path),
            "data_root": str(location.root),
            "source": location.source,
            "exists": False,
        }
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower()
        migrations: list[str] = []
        try:
            migrations = [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM schema_migrations ORDER BY id"
                ).fetchall()
            ]
        except sqlite3.Error:
            migrations = []
        items = 0
        try:
            items = int(conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0])
        except sqlite3.Error:
            items = 0
    return {
        "schema": NEURAL_API_SCHEMA,
        "status": "ready" if integrity == "ok" else "corrupt",
        "database": str(db_path),
        "data_root": str(location.root),
        "source": location.source,
        "exists": True,
        "size": db_path.stat().st_size,
        "sha256": _sha256_file(db_path),
        "integrity": integrity,
        "memory_items": items,
        "migrations_present": migrations,
        "packaged_migrations": [m for m, _ in _migration_files()],
        "packaged_seeds": str(_SEEDS_DIR) if _seed_parts() else None,
        "occurred_at": _now(),
    }
