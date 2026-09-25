#!/usr/bin/env python3
"""Seed project skills into Mapper's canonical unified memory store.

The committed ``.simplicio/skills`` tree is the auditable source.  This command
indexes each ``SKILL.md`` through :class:`MemoryStore`, so Mapper's semantic
and lexical indexes share one deterministic, idempotent skill catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "simplicio.skill-seed/v1"
DEFAULT_DATABASE = Path(".simplicio/memory.sqlite")
SKILL_NAME = re.compile(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)
SKILL_DESCRIPTION = re.compile(r"^description:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _frontmatter(text: str) -> tuple[str, str]:
    head = text.split("---", 2)
    front = head[1] if len(head) >= 3 else ""
    name_match = SKILL_NAME.search(front)
    description_match = SKILL_DESCRIPTION.search(front)
    name = name_match.group(1).strip() if name_match else ""
    description = description_match.group(1).strip() if description_match else ""
    return name, description


def _skill_records(root: Path) -> list[dict[str, Any]]:
    skill_root = root / ".simplicio" / "skills"
    records: list[dict[str, Any]] = []
    for path in sorted(skill_root.glob("*/SKILL.md")):
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        name, description = _frontmatter(text)
        if not name:
            raise ValueError(f"missing frontmatter name: {path}")
        relative = path.relative_to(root).as_posix()
        content_hash = _sha256(raw)
        records.append(
            {
                "name": name,
                "description": description,
                "path": relative,
                "content": text,
                "content_hash": content_hash,
            }
        )
    return records


def seed(root: Path, database: Path) -> dict[str, Any]:
    from simplicio_mapper.store.memory import MemoryStore

    records = _skill_records(root)
    if not records:
        raise ValueError(f"no skill manifests found under {root / '.simplicio' / 'skills'}")
    store = MemoryStore(database=database)
    store.initialize()
    results: list[dict[str, Any]] = []
    for record in records:
        result = store.store(
            topic=f"simplicio-skill:{record['name']}",
            content=record["content"],
            tags=["simplicio", "skill", record["name"]],
            actor="simplicio.mapper",
            source="simplicio-skill-seed",
            source_path=record["path"],
            source_hash=record["content_hash"],
            metadata={
                "schema": SCHEMA,
                "skill": record["name"],
                "description": record["description"],
                "compatibility": "all Simplicio runtimes; invoke only when routing rules match",
                "content_hash": record["content_hash"],
            },
            stable_id=f"skill:{record['name']}",
        )
        results.append({"name": record["name"], **result})
    validation = store.validate()
    if not validation.get("ok"):
        raise RuntimeError(json.dumps(validation, sort_keys=True))
    return {
        "schema": SCHEMA,
        "database": str(database),
        "skills_root": str(root / ".simplicio" / "skills"),
        "count": len(results),
        "results": results,
        "validation": validation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="Mapper SQLite memory store")
    args = parser.parse_args(argv)
    root = args.root.expanduser().absolute()
    database = args.database if args.database.is_absolute() else (root / args.database)
    # Keep the seed command runnable from a source checkout without requiring
    # an editable install of the Mapper package.
    sys.path.insert(0, str(root))
    try:
        print(json.dumps(seed(root, database), ensure_ascii=False, sort_keys=True, indent=2))
    except Exception as error:  # pragma: no cover - CLI boundary
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
