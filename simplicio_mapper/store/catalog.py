"""Ecosystem data catalog — Mapper owns every durable bank under SIMPLICIO_DATA_DIR.

Policy: Mapper is the sole data centralizer. Runtime, loop, fast, and host tools
may write only through paths resolved from this catalog (or SIMPLICIO_DATA_DIR).
Legacy locations under ~/.simplicio/** are absorb sources, not canonical roots.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .paths import StoreLocation, resolve_store_location

CATALOG_API_SCHEMA = "simplicio.mapper-store.data-catalog/v1"
CATALOG_MANIFEST_NAME = "ecosystem-data-catalog.json"

# Single memory SoT (see store/unify.py). Legacy neural is absorb-only.
CANONICAL_MEMORY_DB = "memory.sqlite"
LEGACY_NEURAL_DB = "simplicio-memory.sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_root(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> StoreLocation:
    return resolve_store_location(
        data_dir=data_dir,
        environ=environ,
        home=Path.home(),
        allow_temp=False,
    )


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        return {
            "path": str(path),
            "exists": True,
            "kind": "directory",
            "entries": len(files),
            "size": size,
        }
    return {
        "path": str(path),
        "exists": True,
        "kind": "file",
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sqlite_summary(path: Path) -> dict[str, Any]:
    meta = _file_meta(path)
    if not meta.get("exists") or path.is_dir():
        return meta
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
            integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0]).lower()
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            counts: dict[str, int] = {}
            for table in tables[:40]:
                try:
                    counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                except sqlite3.Error:
                    counts[table] = -1
        meta["integrity"] = integrity
        meta["tables"] = tables
        meta["row_counts"] = counts
    except sqlite3.Error as error:
        meta["integrity"] = "error"
        meta["error"] = str(error)
    return meta


@dataclass(frozen=True)
class BankSpec:
    """One ecosystem durable store owned by Mapper."""

    bank_id: str
    relative: str  # path under SIMPLICIO_DATA_DIR
    kind: str  # sqlite | jsonl | json | directory | file
    owners: tuple[str, ...]
    description: str
    legacy: tuple[str, ...]  # relative to home/.simplicio or absolute-style tokens
    required: bool = False

    def canonical(self, root: Path) -> Path:
        return root / self.relative

    def legacy_candidates(self, home: Path) -> list[Path]:
        base = home / ".simplicio"
        out: list[Path] = []
        for token in self.legacy:
            if token.startswith("~/"):
                out.append((home / token[2:]).expanduser())
            elif token.startswith("REPO:"):
                # Resolved only when absorb is given a repo_root.
                continue
            else:
                out.append(base / token)
        return out


# Canonical ecosystem inventory — extend here when a new durable bank is introduced.
ECOSYSTEM_BANKS: tuple[BankSpec, ...] = (
    BankSpec(
        bank_id="mapper-memory",
        relative=CANONICAL_MEMORY_DB,
        kind="sqlite",
        owners=("mapper", "runtime", "loop", "fast", "mcp"),
        description=(
            "CANONICAL single SoT: MapperStore memory + semantic + FTS5 "
            f"({CANONICAL_MEMORY_DB}). Runtime/MCP read this file only."
        ),
        legacy=("memory.sqlite",),
        required=True,
    ),
    BankSpec(
        bank_id="neural",
        relative=LEGACY_NEURAL_DB,
        kind="sqlite",
        owners=("mapper", "runtime"),
        description=(
            "Legacy neural schema (memory_items); absorb source bridged into "
            f"{CANONICAL_MEMORY_DB} by `data unify`. Not the Runtime MCP SoT."
        ),
        legacy=("memory/simplicio-memory.sqlite",),
        required=False,
    ),
    BankSpec(
        bank_id="operations",
        relative="operations.sqlite",
        kind="sqlite",
        owners=("mapper", "runtime", "loop"),
        description="Operations ledger / agent-store journal (Mapper ops namespace)",
        legacy=("data/operations.sqlite", "ops/operations.sqlite"),
        required=False,
    ),
    BankSpec(
        bank_id="agents",
        relative="agents.sqlite",
        kind="sqlite",
        owners=("runtime", "loop"),
        description="Agent registry (absorbed from repo .simplicio/agents.db)",
        legacy=("agents.db", "agents.sqlite"),
        required=False,
    ),
    BankSpec(
        bank_id="interactions",
        relative="memory/interactions.jsonl",
        kind="jsonl",
        owners=("runtime",),
        description="Runtime conversation interaction log",
        legacy=("memory/interactions.jsonl",),
        required=False,
    ),
    BankSpec(
        bank_id="journal-index",
        relative="memory/journal-index.json",
        kind="json",
        owners=("runtime",),
        description="Runtime journal index sidecar",
        legacy=("memory/journal-index.json",),
        required=False,
    ),
    BankSpec(
        bank_id="checkpoints",
        relative="checkpoints",
        kind="directory",
        owners=("runtime", "loop"),
        description="Runtime/loop checkpoint snapshots",
        legacy=("checkpoints",),
        required=False,
    ),
    BankSpec(
        bank_id="cache",
        relative="cache",
        kind="directory",
        owners=("mapper", "runtime", "fast"),
        description="Shared cache (orientation index, pypi versions, diskcache)",
        legacy=("cache",),
        required=False,
    ),
    BankSpec(
        bank_id="ops-events",
        relative="ops/events.jsonl",
        kind="jsonl",
        owners=("runtime", "loop"),
        description="Ops event stream",
        legacy=("ops/events.jsonl",),
        required=False,
    ),
    BankSpec(
        bank_id="ledger-savings",
        relative="ledger/savings-events.jsonl",
        kind="jsonl",
        owners=("mapper", "loop"),
        description="Token/savings ledger events",
        legacy=("ledger/savings-events.jsonl",),
        required=False,
    ),
    BankSpec(
        bank_id="mcp-connections",
        relative="mcp/connections.jsonl",
        kind="jsonl",
        owners=("runtime",),
        description="MCP connection audit log",
        legacy=("mcp/connections.jsonl",),
        required=False,
    ),
    BankSpec(
        bank_id="ghost-records",
        relative="ghost/records.jsonl",
        kind="jsonl",
        owners=("runtime",),
        description="Ghost/recovery records",
        legacy=("ghost/records.jsonl",),
        required=False,
    ),
    BankSpec(
        bank_id="operator-check",
        relative="operator-check.json",
        kind="json",
        owners=("loop",),
        description="Operator pin / TTL check receipt",
        legacy=("operator-check.json",),
        required=False,
    ),
    BankSpec(
        bank_id="runtime-resource-map",
        relative="runtime-resource-map.json",
        kind="json",
        owners=("runtime",),
        description="Runtime resource map cache",
        legacy=("runtime-resource-map.json",),
        required=False,
    ),
    BankSpec(
        bank_id="economy-parallel-env",
        relative="economy-parallel-env.json",
        kind="json",
        owners=("loop",),
        description="Economy/parallel env snapshot",
        legacy=("economy-parallel-env.json",),
        required=False,
    ),
    BankSpec(
        bank_id="neural-schema-sql",
        relative="memory/memory-schema.sql",
        kind="file",
        owners=("mapper", "runtime"),
        description="Packaged neural schema copy for offline tools",
        legacy=("memory/memory-schema.sql",),
        required=False,
    ),
)


def bank_by_id(bank_id: str) -> BankSpec | None:
    for bank in ECOSYSTEM_BANKS:
        if bank.bank_id == bank_id:
            return bank
    return None


def layout_tree() -> dict[str, Any]:
    """Document the canonical Mapper data root layout."""
    return {
        "schema": CATALOG_API_SCHEMA,
        "root_env": "SIMPLICIO_CORE_DATA_DIR / SIMPLICIO_DATA_DIR",
        "default_root": "~/.simplicio/data",
        "policy": (
            "All durable files live under .simplicio. Core/Runtime memory is "
            "~/.simplicio/data; each project isolates under "
            "<repo>/.simplicio/data/<slug> so banks never mix."
        ),
        "scopes": {
            "core_runtime": {
                "root": "~/.simplicio/data",
                "memory": "~/.simplicio/data/memory.sqlite",
                "env": ["SIMPLICIO_CORE_DATA_DIR", "SIMPLICIO_DATA_DIR", "SIMPLICIO_MEMORY_DB"],
            },
            "project": {
                "root": "<repo>/.simplicio/data/<project_slug>",
                "memory": "<repo>/.simplicio/data/<project_slug>/memory.sqlite",
                "slug_from": [
                    "SIMPLICIO_PROJECT",
                    "git remote origin name",
                    "host workspace (Codex/Cursor/Claude/Gemini)",
                    "directory name",
                ],
                "env": ["SIMPLICIO_PROJECT", "SIMPLICIO_PROJECT_DATA_DIR", "SIMPLICIO_PROJECT_MEMORY_DB"],
            },
        },
        "canonical_memory": {
            "path": CANONICAL_MEMORY_DB,
            "schema": "simplicio.mapper-store.memory/v1 + semantic + FTS5",
            "core_env": "SIMPLICIO_MEMORY_DB → ~/.simplicio/data/memory.sqlite",
            "project_env": "SIMPLICIO_PROJECT_MEMORY_DB → <repo>/.simplicio/data/<slug>/memory.sqlite",
        },
        "banks": [
            {
                "id": b.bank_id,
                "path": b.relative,
                "kind": b.kind,
                "owners": list(b.owners),
                "required": b.required,
                "description": b.description,
                "legacy_sources": list(b.legacy),
            }
            for b in ECOSYSTEM_BANKS
        ],
        "mapper_fast_integration": {
            "note": (
                "Mapper extracts (project-map/context-snapshot); Fast builds disposable "
                ".sfast under <repo>/.simplicio/fast/. Core Runtime memory stays in "
                "~/.simplicio/data; project memory under <repo>/.simplicio/data/<slug>."
            ),
            "commands": [
                "simplicio-mapper status .",
                "simplicio-mapper data status --repo .",
                "simplicio-mapper data unify --repo .",
                "simplicio-mapper fast-handoff .",
                "simplicio-fast build . -o .simplicio/fast/project.sfast",
            ],
            "dependency": "simplicio-fast depends on simplicio-mapper>=0.26.11,<0.27",
        },
        "repo_scoped_artifacts": {
            "note": (
                "Working copies stay under <repo>/.simplicio/ (project-map, fast, "
                "orchestrator). Durable project DBs live under .simplicio/data/<slug>."
            ),
            "examples": [
                ".simplicio/project-map.json",
                ".simplicio/precedent-index.json",
                ".simplicio/fast/project.sfast",
                ".simplicio/data/<slug>/memory.sqlite",
                ".simplicio/orchestrator/",
            ],
        },
    }


def _inspect_bank(bank: BankSpec, root: Path, home: Path) -> dict[str, Any]:
    canonical = bank.canonical(root)
    if bank.kind == "sqlite":
        at_root = _sqlite_summary(canonical)
    else:
        at_root = _file_meta(canonical)
    legacy_hits = []
    for path in bank.legacy_candidates(home):
        if path.exists():
            legacy_hits.append(_file_meta(path) if bank.kind != "sqlite" else _sqlite_summary(path))
    status = "ready" if at_root.get("exists") else ("legacy_only" if legacy_hits else "missing")
    if bank.required and not at_root.get("exists"):
        status = "required_missing" if not legacy_hits else "needs_absorb"
    return {
        "id": bank.bank_id,
        "kind": bank.kind,
        "relative": bank.relative,
        "owners": list(bank.owners),
        "required": bank.required,
        "description": bank.description,
        "status": status,
        "canonical": at_root,
        "legacy": legacy_hits,
    }


def data_status(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    home: str | Path | None = None,
) -> dict[str, Any]:
    location = _resolve_root(data_dir=data_dir, environ=environ)
    home_path = Path(home).expanduser() if home else Path.home()
    banks = [_inspect_bank(b, location.root, home_path) for b in ECOSYSTEM_BANKS]
    ready = sum(1 for b in banks if b["status"] == "ready")
    needs = sum(1 for b in banks if b["status"] in {"needs_absorb", "legacy_only"})
    missing_required = [b["id"] for b in banks if b["status"] == "required_missing"]
    return {
        "schema": CATALOG_API_SCHEMA,
        "status": "ready" if not missing_required else "incomplete",
        "data_root": str(location.root),
        "root_source": location.source,
        "root_exists": location.exists,
        "banks_total": len(banks),
        "banks_ready": ready,
        "banks_need_absorb": needs,
        "required_missing": missing_required,
        "banks": banks,
        "manifest": str(location.root / CATALOG_MANIFEST_NAME),
        "occurred_at": _now(),
    }


def _copy_path(src: Path, dest: Path, *, backup: bool) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup_path = None
    if backup and dest.exists():
        stamp = uuid4().hex[:8]
        if dest.is_dir():
            backup_path = dest.with_name(f"{dest.name}.backup.{stamp}")
            if backup_path.exists():
                shutil.rmtree(backup_path)
            shutil.copytree(dest, backup_path)
        else:
            backup_path = dest.with_name(f"{dest.name}.backup.{stamp}")
            shutil.copy2(dest, backup_path)
    if src.is_dir():
        if dest.exists():
            # merge: copy newer/missing files
            for path in src.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(src)
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists() or path.stat().st_mtime > target.stat().st_mtime:
                        shutil.copy2(path, target)
        else:
            shutil.copytree(src, dest)
    else:
        # Prefer sqlite backup API for databases when possible
        if src.suffix == ".sqlite" or src.name.endswith(".db"):
            with closing(sqlite3.connect(src)) as source, closing(sqlite3.connect(dest)) as destination:
                source.backup(destination)
                destination.commit()
                integrity = str(destination.execute("PRAGMA quick_check").fetchone()[0]).lower()
                if integrity != "ok":
                    raise RuntimeError(f"ABSORB_CORRUPT:{src}:{integrity}")
        else:
            shutil.copy2(src, dest)
    return {
        "source": str(src),
        "destination": str(dest),
        "backup": str(backup_path) if backup_path else None,
        "source_meta": _file_meta(src),
        "destination_meta": _file_meta(dest),
    }


def absorb_bank(
    bank_id: str,
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    home: str | Path | None = None,
    source: str | Path | None = None,
    backup: bool = True,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    bank = bank_by_id(bank_id)
    if bank is None:
        raise KeyError(f"unknown bank: {bank_id}")
    location = _resolve_root(data_dir=data_dir, environ=environ)
    location.ensure_root()
    home_path = Path(home).expanduser() if home else Path.home()
    dest = bank.canonical(location.root)

    if source is not None:
        src = Path(source).expanduser().absolute()
    else:
        candidates = bank.legacy_candidates(home_path)
        if repo_root is not None:
            repo = Path(repo_root).expanduser().absolute()
            candidates.extend(
                [
                    repo / ".simplicio" / "agents.db",
                    repo / ".simplicio" / "data" / "operations.sqlite",
                    repo / ".simplicio" / "orchestrator" / "agent-slots.sqlite",
                    repo / ".simplicio" / "cache" / "cache.db",
                ]
            )
        src = next((p for p in candidates if p.exists()), None)
        if src is None:
            return {
                "schema": CATALOG_API_SCHEMA,
                "status": "skipped",
                "bank_id": bank_id,
                "reason": "SOURCE_MISSING",
                "tried": [str(p) for p in candidates],
                "destination": str(dest),
            }

    if dest.exists() and dest.is_file() and src.is_file():
        # skip identical content
        if _sha256_file(src) and _sha256_file(src) == _sha256_file(dest):
            return {
                "schema": CATALOG_API_SCHEMA,
                "status": "unchanged",
                "bank_id": bank_id,
                "source": str(src),
                "destination": str(dest),
            }

    report = _copy_path(src, dest, backup=backup)
    # Neural bank: apply packaged migrations after absorb
    if bank_id == "neural":
        try:
            from .neural.bank import apply_migrations

            with closing(sqlite3.connect(dest)) as conn:
                applied = apply_migrations(conn)
                conn.commit()
            report["migrations_applied_now"] = applied
        except Exception as error:  # noqa: BLE001 — absorb should not hard-fail on migrate drift
            report["migrations_error"] = str(error)

    return {
        "schema": CATALOG_API_SCHEMA,
        "status": "absorbed",
        "bank_id": bank_id,
        **report,
        "occurred_at": _now(),
    }


def absorb_all(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    home: str | Path | None = None,
    backup: bool = True,
    repo_root: str | Path | None = None,
    bank_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Absorb every catalogued bank that has a legacy source into Mapper root."""
    location = _resolve_root(data_dir=data_dir, environ=environ)
    location.ensure_root()
    selected = list(bank_ids) if bank_ids is not None else [b.bank_id for b in ECOSYSTEM_BANKS]
    results = []
    for bank_id in selected:
        results.append(
            absorb_bank(
                bank_id,
                data_dir=location.root,
                environ=environ,
                home=home,
                backup=backup,
                repo_root=repo_root,
            )
        )
    from .unify import env_hints, unify_memory

    # Always bridge legacy neural into canonical MapperStore after absorb.
    unify_report = unify_memory(
        data_dir=location.root,
        environ=environ,
        absorb_legacy_home=False,
        rebuild_fts=True,
    )
    status = data_status(data_dir=location.root, environ=environ, home=home)
    hints = env_hints(data_dir=location.root)
    manifest = {
        "schema": CATALOG_API_SCHEMA,
        "version": 2,
        "data_root": str(location.root),
        "updated_at": _now(),
        "policy": (
            "Mapper centralizes all ecosystem durable data under this root. "
            f"Canonical memory SoT is {CANONICAL_MEMORY_DB} (MapperStore+FTS5)."
        ),
        "canonical_memory": str(location.root / CANONICAL_MEMORY_DB),
        "banks": status["banks"],
        "last_absorb": results,
        "unify": {
            "status": unify_report.get("status"),
            "semantic_items": unify_report.get("semantic_items"),
            "memory_entries": unify_report.get("memory_entries"),
            "fts": unify_report.get("fts"),
        },
        "env": hints,
    }
    manifest_path = location.root / CATALOG_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema": CATALOG_API_SCHEMA,
        "status": "complete",
        "data_root": str(location.root),
        "manifest": str(manifest_path),
        "canonical_memory": str(location.root / CANONICAL_MEMORY_DB),
        "unify": manifest["unify"],
        "absorbed": [r for r in results if r.get("status") == "absorbed"],
        "unchanged": [r for r in results if r.get("status") == "unchanged"],
        "skipped": [r for r in results if r.get("status") == "skipped"],
        "summary": {
            "banks_ready": status["banks_ready"],
            "banks_total": status["banks_total"],
            "required_missing": status["required_missing"],
        },
        "env_hints": manifest["env"],
        "occurred_at": _now(),
    }


def ensure_mapper_memory(
    *,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ensure MapperStore memory.sqlite exists at the data root."""
    from .memory import MemoryStore

    location = _resolve_root(data_dir=data_dir, environ=environ)
    location.ensure_root()
    db_path = location.database("memory.sqlite")
    markdown_root = location.root / "memory-markdown"
    markdown_root.mkdir(parents=True, exist_ok=True)
    result = MemoryStore(db_path, markdown_root=markdown_root).initialize()
    return {
        "schema": CATALOG_API_SCHEMA,
        "status": "ready",
        "bank_id": "mapper-memory",
        "database": str(db_path),
        "init": result if isinstance(result, dict) else {"ok": True},
        "occurred_at": _now(),
    }


__all__ = [
    "CATALOG_API_SCHEMA",
    "CATALOG_MANIFEST_NAME",
    "ECOSYSTEM_BANKS",
    "BankSpec",
    "absorb_all",
    "absorb_bank",
    "bank_by_id",
    "data_status",
    "ensure_mapper_memory",
    "layout_tree",
]
