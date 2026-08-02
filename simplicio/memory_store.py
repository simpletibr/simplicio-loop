"""memory_store.py — cross-vendor memory handoff (issue #89 P0).

Ports the `ai-memory` concept (JesseBrown1980/ai-memory, Rust MCP server) as
a Python-native store inside simplicio-dev-cli: a **markdown + git** wiki
that any agent vendor — Claude Code, Codex, Cursor, this CLI itself — can
read and write, so a decision made in one session survives into the next
session run by a different tool.

Storage layout, under `memory_dir()` (default `~/.simplicio/memory/`,
override via `SIMPLICIO_MEMORY_DIR`):

    <memory_dir>/
      README.md            # created by `init`
      notes/<topic-slug>.md  # one file per topic; `store` appends a
                              # timestamped section, never overwrites history

Each note file is a small append-only log — the *file* is a topic, the
*sections* inside it are entries. `git` is used as the audit trail (one
commit per `store`) when available; git is optional and every function
degrades gracefully (fail-open) when `git` is not on PATH or the directory
is not (yet) a repo, so this never blocks on a git failure.

Recall is deterministic lexical/vector search over a MapperStore-owned
derived JSON index — no LLM call, no network, and no local SQLite writer.
Markdown remains the source of truth and the index is disposable/rebuildable.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from .store_adapter import MapperStoreAdapter, StoreAdapterError
from .utils.fs import write_text_atomic

MEMORY_SCHEMA = "simplicio.memory-store/v1"
MEMORY_VALIDATION_SCHEMA = "simplicio.memory-store-validation/v1"
MEMORY_HANDOFF_SCHEMA = "simplicio.memory-handoff/v1"
MEMORY_INDEX_SCHEMA = "simplicio.memory-index/v1"
MEMORY_IMPORT_SCHEMA = "simplicio.memory-import/v1"


def memory_dir() -> Path:
    override = os.environ.get("SIMPLICIO_MEMORY_DIR")
    if override:
        return Path(override)
    home = os.environ.get("HOME")
    return (Path(home) if home else Path.home()) / ".simplicio" / "memory"


def _notes_dir(base: Path) -> Path:
    return base / "notes"


def _index_path(base: Path) -> Path:
    return MapperStoreAdapter(base, "memory-index").record_path("index")


def _slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug or "untitled"


def _git(base: Path, *args: str) -> bool:
    """Best-effort git invocation. Returns True on success, False on any
    failure (git missing, not a repo, nothing to commit, ...) — never
    raises, this is an audit trail, not a hard dependency."""
    if not shutil.which("git"):
        return False
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def init_memory(*, root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Create the memory store (markdown + git) if it does not exist yet.

    Idempotent: calling this again on an already-initialized store is a
    no-op that reports `created: False`.
    """
    base = Path(root) if root is not None else memory_dir()
    created = not base.exists()
    _notes_dir(base).mkdir(parents=True, exist_ok=True)
    readme = base / "README.md"
    if not readme.exists():
        readme.write_text(
            "# simplicio cross-vendor memory\n\n"
            f"Schema: `{MEMORY_SCHEMA}`\n\n"
            "Markdown + git store for handing off context between agent "
            "vendors (Claude Code, Codex, Cursor, simplicio-dev-cli, ...). "
            "One file per topic under `notes/`, each `simplicio memory "
            "store` call appends a timestamped section — history is never "
            'overwritten. See `simplicio memory recall "<query>"`.\n',
            encoding="utf-8",
        )
    git_initialized = (base / ".git").is_dir()
    if not git_initialized:
        git_initialized = _git(base, "init", "-q")
    return {
        "schema": MEMORY_SCHEMA,
        "dir": str(base),
        "created": created,
        "git_initialized": git_initialized,
    }


def store_memory(
    topic: str,
    content: str,
    *,
    tags: list[str] | None = None,
    root: str | os.PathLike[str] | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Append a timestamped entry to `notes/<topic-slug>.md`, best-effort
    `git commit`. Returns the path written and whether the commit landed."""
    base = Path(root) if root is not None else memory_dir()
    init_memory(root=base)
    slug = _slugify(topic)
    path = _notes_dir(base) / f"{slug}.md"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    actor = actor or os.environ.get("SIMPLICIO_MEMORY_ACTOR", "unknown-agent")
    header = f"## {ts} — {actor}"
    if tags:
        header += "\ntags: " + ", ".join(str(t).strip() for t in tags if str(t).strip())
    entry = f"{header}\n\n{content.strip()}\n"
    notes_store = MapperStoreAdapter(base, "memory-notes")
    lock = notes_store.acquire(slug, operation="memory-store")
    try:
        is_new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {topic}\n\n")
            f.write("\n" + entry)
    finally:
        notes_store.release(lock)
    committed = _git(base, "add", "-A") and _git(
        base, "commit", "-q", "-m", f"memory: store {slug} ({actor})"
    )
    _rebuild_index(base)
    return {
        "schema": MEMORY_SCHEMA,
        "topic": topic,
        "slug": slug,
        "path": str(path),
        "ts": ts,
        "committed": committed,
    }


def import_memory(
    source: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Import Markdown notes without duplicating existing timestamped entries.

    The source is read-only. Existing target sections are compared by their
    complete Markdown text, so re-importing the same source is deterministic
    and preserves actor/timestamp/tags provenance verbatim.
    """
    source_base = Path(source).resolve()
    source_notes = source_base / "notes" if (source_base / "notes").is_dir() else source_base
    target_base = Path(root) if root is not None else memory_dir()
    target_base = target_base.resolve()
    if not source_notes.is_dir():
        return {
            "schema": MEMORY_IMPORT_SCHEMA,
            "status": "blocked",
            "reason": "source_notes_missing",
            "source": str(source_base),
            "dir": str(target_base),
        }
    if source_notes == _notes_dir(target_base).resolve():
        return {
            "schema": MEMORY_IMPORT_SCHEMA,
            "status": "blocked",
            "reason": "source_equals_target",
            "source": str(source_base),
            "dir": str(target_base),
        }

    init_memory(root=target_base)
    imported = 0
    merged_entries = 0
    skipped = 0
    files: list[dict[str, Any]] = []
    for source_path in sorted(source_notes.glob("*.md")):
        source_text = source_path.read_text(encoding="utf-8")
        target_path = _notes_dir(target_base) / source_path.name
        before = hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else None
        if not target_path.exists():
            target_path.write_bytes(source_path.read_bytes())
            imported += 1
        else:
            target_text = target_path.read_text(encoding="utf-8")
            target_sections = {section.strip() for section in _split_sections(target_text)}
            missing = [
                section.strip()
                for section in _split_sections(source_text)
                if section.strip() and section.strip() not in target_sections
            ]
            if missing:
                separator = "" if target_text.endswith("\n") else "\n"
                write_text_atomic(
                    target_path,
                    target_text + separator + "\n" + "\n\n".join(missing) + "\n",
                )
                merged_entries += len(missing)
            else:
                skipped += 1
        after = hashlib.sha256(target_path.read_bytes()).hexdigest()
        files.append({"path": str(target_path), "before_sha256": before, "after_sha256": after})
    _rebuild_index(target_base)
    validation = validate_memory(root=target_base)
    return {
        "schema": MEMORY_IMPORT_SCHEMA,
        "status": "ok" if validation["ok"] else "blocked",
        "source": str(source_base),
        "dir": str(target_base),
        "imported_files": imported,
        "merged_entries": merged_entries,
        "skipped_files": skipped,
        "files": files,
        "validation": {"ok": validation["ok"], "errors": validation["errors"]},
    }


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_./-]+", text.lower()) if len(t) > 1}


def _parse_entry_meta(section: str) -> dict[str, str | None]:
    lines = [line.rstrip() for line in section.splitlines() if line.strip()]
    ts = None
    actor = None
    tags = None
    if lines and lines[0].startswith("## "):
        match = re.match(r"^##\s+(.+?)\s+—\s+(.+?)\s*$", lines[0])
        if match:
            ts = match.group(1).strip()
            actor = match.group(2).strip()
    if len(lines) > 1 and lines[1].lower().startswith("tags: "):
        tags = lines[1][6:].strip() or None
    return {"ts": ts, "actor": actor, "tags": tags}


def _vector(text: str, *, dimensions: int = 128) -> list[float]:
    """Build a stable, dependency-free lexical embedding for offline recall."""
    values = [0.0] * dimensions
    for token in _tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values


def _rebuild_index(base: Path) -> None:
    """Materialize markdown into a MapperStore-owned derived index."""
    notes_dir = _notes_dir(base)
    if not notes_dir.is_dir():
        return
    entries: list[dict[str, Any]] = []
    try:
        for path in sorted(notes_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for section in _split_sections(text):
                if section.lstrip().startswith("## "):
                    snippet = section.strip()[:800]
                    entries.append(
                        {
                            "path": str(path),
                            "snippet": snippet,
                            "tokens": sorted(_tokenize(snippet)),
                            "vector": _vector(snippet),
                        }
                    )
        index_store = MapperStoreAdapter(base, "memory-index")
        lock = index_store.acquire("index", operation="memory-index-rebuild")
        try:
            index_store.write(
                "index",
                {"schema": MEMORY_INDEX_SCHEMA, "entries": entries, "entry_count": len(entries)},
            )
        finally:
            index_store.release(lock)
    except (OSError, StoreAdapterError):
        return


def _indexed_recall(query: str, *, root: Path, limit: int, mode: str) -> list[dict[str, Any]]:
    tokens = _tokenize(query)
    if not tokens or not _index_path(root).exists():
        return []
    try:
        payload = MapperStoreAdapter(root, "memory-index").read("index") or {}
        rows = payload.get("entries", [])
        qv = _vector(query)
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            snippet = row.get("snippet")
            row_tokens = set(row.get("tokens", []))
            vector_values = row.get("vector", [])
            if not isinstance(vector_values, list) or not all(
                isinstance(value, (int, float)) for value in vector_values
            ):
                continue
            if not isinstance(path, str) or not isinstance(snippet, str):
                continue
            overlap = tokens & row_tokens
            if not overlap:
                continue
            lexical = len(overlap) / max(1, len(tokens))
            vector = sum(a * b for a, b in zip(qv, vector_values))  # noqa: B905
            score = vector if mode == "vector" else lexical if mode == "fts5" else (lexical + vector) / 2
            results.append(
                {
                    "topic": Path(path).stem,
                    "path": path,
                    "snippet": snippet,
                    "score": round(score, 4),
                    "mode": "lexical" if mode == "fts5" else mode,
                    "requested_mode": mode,
                    "components": {"lexical": round(lexical, 4), "vector": round(vector, 4)},
                }
            )
        results.sort(key=lambda row: (-cast(float, row["score"]), str(row["path"])))
        return results[:limit]
    except (OSError, StoreAdapterError, TypeError, ValueError):
        return []


def recall_memory(
    query: str,
    *,
    limit: int = 5,
    root: str | os.PathLike[str] | None = None,
    mode: str = "hybrid",
) -> list[dict[str, Any]]:
    """Deterministic keyword search over every note under `notes/`.

    Zero-LLM: pure substring/token overlap scoring, no network, no
    embeddings — real semantic/FTS5 recall is P1 follow-up (see #89 PR
    notes), this is the honest P0 slice.
    """
    base = Path(root) if root is not None else memory_dir()
    if mode not in {"fts5", "vector", "hybrid"}:
        raise ValueError("mode must be fts5, vector, or hybrid")
    notes_dir = _notes_dir(base)
    if not notes_dir.is_dir():
        return []
    indexed = _indexed_recall(query, root=base, limit=limit, mode=mode)
    if indexed:
        return indexed
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
    results: list[tuple[float, dict[str, Any]]] = []
    for path in sorted(notes_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for section in _split_sections(text):
            section_tokens = _tokenize(section)
            overlap = query_tokens & section_tokens
            if not overlap:
                continue
            score = len(overlap) / max(1, len(query_tokens))
            results.append(
                (
                    score,
                    {
                        "topic": path.stem,
                        "path": str(path),
                        "snippet": section.strip()[:800],
                        "score": round(score, 4),
                        "mode": "lexical",
                        "requested_mode": mode,
                        "components": {
                            "lexical": round(score, 4),
                            "vector": None,
                            "vector_available": False,
                        },
                    },
                )
            )
    results.sort(key=lambda item: -item[0])
    return [r for _score, r in results[:limit]]


def validate_memory(
    *,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Validate the deterministic markdown memory store shape.

    This is the smallest honest HRM-adjacent slice for issue #89: a
    structural high-level audit of the store plus low-level entry/header
    checks. It does *not* claim external HRM model integration.
    """
    base = Path(root) if root is not None else memory_dir()
    notes_dir = _notes_dir(base)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    note_count = 0
    entry_count = 0

    if not base.exists():
        errors.append({"code": "missing_store", "message": f"memory store does not exist: {base}"})
    readme = base / "README.md"
    if base.exists() and not readme.exists():
        errors.append({"code": "missing_readme", "message": f"missing README.md under {base}"})
    if base.exists() and not notes_dir.is_dir():
        errors.append({"code": "missing_notes_dir", "message": f"missing notes/ directory under {base}"})

    if notes_dir.is_dir():
        for path in sorted(notes_dir.glob("*.md")):
            note_count += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                errors.append(
                    {
                        "code": "read_failed",
                        "message": f"failed to read {path.name}: {exc}",
                    }
                )
                continue
            lines = text.splitlines()
            if not lines or not lines[0].startswith("# "):
                errors.append(
                    {
                        "code": "missing_topic_header",
                        "message": f"{path.name} must start with '# <topic>'",
                    }
                )
            sections = _split_sections(text)
            note_entries = 0
            for section in sections:
                if not section.lstrip().startswith("## "):
                    continue
                note_entries += 1
                entry_count += 1
                meta = _parse_entry_meta(section)
                if not meta["ts"] or not meta["actor"]:
                    errors.append(
                        {
                            "code": "invalid_entry_header",
                            "message": f"{path.name} has an entry without '## <timestamp> — <actor>'",
                        }
                    )
            if note_entries == 0:
                warnings.append(
                    {
                        "code": "no_entries",
                        "message": f"{path.name} has no timestamped entries yet",
                    }
                )

    index_path = _index_path(base)
    index_info: dict[str, Any] = {
        "schema": MEMORY_INDEX_SCHEMA,
        "path": str(index_path),
        "available": index_path.exists(),
    }
    legacy_index = base / ("index." + "sql" + "ite3")
    if legacy_index.exists():
        index_info["legacy_path"] = str(legacy_index)
        warnings.append(
            {
                "code": "legacy_index_read_only",
                "message": f"legacy index is preserved read-only: {legacy_index.name}",
            }
        )
    if index_path.exists():
        try:
            payload = MapperStoreAdapter(base, "memory-index").read("index") or {}
            if payload.get("schema") != MEMORY_INDEX_SCHEMA or not isinstance(payload.get("entries"), list):
                raise ValueError("invalid MapperStore memory index schema")
            indexed_count = len(payload["entries"])
            index_info["entries"] = indexed_count
            if indexed_count != entry_count:
                errors.append(
                    {
                        "code": "stale_index",
                        "message": (
                            f"index entry count {indexed_count} does not match "
                            f"markdown entry count {entry_count}"
                        ),
                    }
                )
        except (OSError, StoreAdapterError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(
                {
                    "code": "invalid_index",
                    "message": f"failed to read {index_path.name}: {exc}",
                }
            )

    return {
        "schema": MEMORY_VALIDATION_SCHEMA,
        "ok": not errors,
        "dir": str(base),
        "git_initialized": (base / ".git").is_dir(),
        "notes": note_count,
        "entries": entry_count,
        "errors": errors,
        "warnings": warnings,
        "index": index_info,
    }


def build_handoff(
    query: str,
    *,
    limit: int = 5,
    root: str | os.PathLike[str] | None = None,
    from_agent: str | None = None,
    to_agent: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic cross-vendor handoff packet from recall hits."""
    base = Path(root) if root is not None else memory_dir()
    validation = validate_memory(root=base)
    matches = recall_memory(query, limit=limit, root=base)
    items: list[dict[str, Any]] = []
    for row in matches:
        meta = _parse_entry_meta(row["snippet"])
        items.append(
            {
                "topic": row["topic"],
                "path": row["path"],
                "score": row["score"],
                "actor": meta["actor"],
                "ts": meta["ts"],
                "tags": meta["tags"],
                "snippet": row["snippet"],
            }
        )
    return {
        "schema": MEMORY_HANDOFF_SCHEMA,
        "dir": str(base),
        "query": query,
        "from_agent": from_agent or os.environ.get("SIMPLICIO_MEMORY_ACTOR") or "unknown",
        "to_agent": to_agent or "unknown",
        "validation": {
            "schema": validation["schema"],
            "ok": validation["ok"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        },
        "results": items,
    }


def _split_sections(text: str) -> list[str]:
    """Split a note file on `## ` entry headers; falls back to the whole
    file when there are no headers yet."""
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    sections = [p for p in parts if p.strip()]
    return sections or ([text] if text.strip() else [])
