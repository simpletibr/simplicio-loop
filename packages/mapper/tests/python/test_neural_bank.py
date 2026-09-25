"""Neural bank centralization under Mapper data root."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from simplicio_mapper.store.neural import (
    absorb_runtime_neural,
    bootstrap_neural,
    neural_status,
)


def test_bootstrap_neural_applies_packaged_migrations(tmp_path: Path) -> None:
    result = bootstrap_neural(data_dir=tmp_path, apply_seeds=False)
    assert result["status"] == "ready"
    assert Path(result["database"]).is_file()
    assert result["migrations_present"]
    assert "0001_initial" in result["migrations_present"]
    assert "0018_seed_provenance" in result["migrations_present"]
    status = neural_status(data_dir=tmp_path)
    assert status["status"] == "ready"
    assert status["exists"] is True
    assert len(status["packaged_migrations"]) == 18


def test_bootstrap_with_seeds(tmp_path: Path) -> None:
    result = bootstrap_neural(data_dir=tmp_path, apply_seeds=True)
    assert result["status"] == "ready"
    assert result["seeds"] is not None
    assert result["memory_items"] >= 0


def test_absorb_runtime_neural_from_source(tmp_path: Path) -> None:
    # Realistic Runtime-shaped source: full migrations + one memory row.
    source_root = tmp_path / "runtime-data"
    bootstrap_neural(data_dir=source_root, apply_seeds=False)
    src = source_root / "simplicio-memory.sqlite"
    with sqlite3.connect(src) as conn:
        conn.execute(
            """
            INSERT INTO memory_items (stable_id, kind, source, title, content)
            VALUES ('runtime-absorb-1', 'fact', 'test', 't', 'Runtime neural content')
            """
        )
        conn.commit()
    dest_root = tmp_path / "mapper-data"
    out = absorb_runtime_neural(source=src, data_dir=dest_root, backup=False)
    assert out["status"] == "absorbed"
    assert out["memory_items"] >= 1
    assert Path(out["destination"]).is_file()
    with sqlite3.connect(out["destination"]) as conn:
        row = conn.execute(
            "SELECT content FROM memory_items WHERE stable_id = ?",
            ("runtime-absorb-1",),
        ).fetchone()
    assert row is not None
    assert row[0] == "Runtime neural content"
