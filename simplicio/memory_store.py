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

Recall is deterministic keyword search over the markdown files — no LLM
call, no embeddings, no network. This is the "Zero-LLM Mode" P0 slice of
#89: real FTS5 + vector hybrid recall is explicitly P1/P2 follow-up (see
CHANGELOG / PR body), not implemented here to avoid overclaiming a search
quality this module does not deliver.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

MEMORY_SCHEMA = "simplicio.memory-store/v1"
MEMORY_VALIDATION_SCHEMA = "simplicio.memory-store-validation/v1"
MEMORY_HANDOFF_SCHEMA = "simplicio.memory-handoff/v1"


def memory_dir() -> Path:
    override = os.environ.get("SIMPLICIO_MEMORY_DIR")
    if override:
        return Path(override)
    home = os.environ.get("HOME")
    return (Path(home) if home else Path.home()) / ".simplicio" / "memory"


def _notes_dir(base: Path) -> Path:
    return base / "notes"


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
    is_new = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(f"# {topic}\n\n")
        f.write("\n" + entry)
    committed = _git(base, "add", "-A") and _git(
        base, "commit", "-q", "-m", f"memory: store {slug} ({actor})"
    )
    return {
        "schema": MEMORY_SCHEMA,
        "topic": topic,
        "slug": slug,
        "path": str(path),
        "ts": ts,
        "committed": committed,
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


def recall_memory(
    query: str,
    *,
    limit: int = 5,
    root: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic keyword search over every note under `notes/`.

    Zero-LLM: pure substring/token overlap scoring, no network, no
    embeddings — real semantic/FTS5 recall is P1 follow-up (see #89 PR
    notes), this is the honest P0 slice.
    """
    base = Path(root) if root is not None else memory_dir()
    notes_dir = _notes_dir(base)
    if not notes_dir.is_dir():
        return []
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

    return {
        "schema": MEMORY_VALIDATION_SCHEMA,
        "ok": not errors,
        "dir": str(base),
        "git_initialized": (base / ".git").is_dir(),
        "notes": note_count,
        "entries": entry_count,
        "errors": errors,
        "warnings": warnings,
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
