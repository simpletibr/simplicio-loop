"""Single-SQLite memory unification (MapperStore SoT)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from simplicio_mapper.store.unify import unify_memory, unify_status


def _make_neural(path: Path, n: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_items (
              id INTEGER PRIMARY KEY,
              stable_id TEXT NOT NULL UNIQUE,
              kind TEXT NOT NULL,
              source TEXT NOT NULL,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              artifact_path TEXT,
              source_hash TEXT,
              metadata TEXT,
              provenance TEXT,
              tags TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        for i in range(n):
            conn.execute(
                """
                INSERT INTO memory_items(
                  stable_id, kind, source, title, content, tags, created_at, updated_at)
                VALUES (?,?,?,?,?,?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (f"u-{i}", "fact", "test", f"t{i}", f"content body {i} for unify", "test"),
            )
        conn.commit()


def test_unify_memory_loads_canonical_from_neural(tmp_path: Path) -> None:
    data = tmp_path / "data"
    neural = data / "simplicio-memory.sqlite"
    _make_neural(neural, n=5)

    report = unify_memory(data_dir=data, absorb_legacy_home=False, rebuild_fts=True)
    assert report["status"] == "ready"
    assert report["semantic_items"] >= 5
    assert report["memory_entries"] >= 5
    assert Path(report["canonical_database"]).is_file()
    assert Path(report["canonical_database"]).name == "memory.sqlite"

    status = unify_status(data_dir=data)
    assert status["status"] in {"ready", "drift"}
    assert status["semantic_items"] >= 5
    assert status["env_hints"]["SIMPLICIO_MEMORY_DB"].endswith("memory.sqlite")

    # Idempotent second pass
    again = unify_memory(data_dir=data, absorb_legacy_home=False, rebuild_fts=True)
    assert again["status"] == "ready"
    assert again["semantic_items"] >= 5
