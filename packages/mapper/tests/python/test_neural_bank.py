"""Neural bank centralization under Mapper data root."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simplicio_mapper.store.neural import (
    absorb_runtime_neural,
    bootstrap_neural,
    neural_status,
)
from simplicio_mapper.store.neural import bank

SEEDS_DIR = Path(bank.__file__).resolve().parent / "assets" / "seeds"
MAX_SEED_PART_LINES = 9000


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


def _seed_parts() -> list[Path]:
    return sorted(SEEDS_DIR.glob("part-*.sql"))


def test_seed_parts_are_numbered_contiguously_from_one() -> None:
    parts = _seed_parts()
    assert parts, f"no seed parts under {SEEDS_DIR}"
    assert [p.name for p in parts] == [f"part-{i:02d}.sql" for i in range(1, len(parts) + 1)]


def test_seed_parts_are_within_the_line_cap() -> None:
    assert _seed_parts(), f"no seed parts under {SEEDS_DIR}"
    for part in _seed_parts():
        lines = part.read_bytes().count(b"\n")
        assert lines <= MAX_SEED_PART_LINES, f"{part.name} has {lines} lines"


def test_seed_parts_end_on_statement_boundaries() -> None:
    # A cut inside a statement (or inside a quoted literal) would leave an incomplete statement.
    assert _seed_parts(), f"no seed parts under {SEEDS_DIR}"
    for part in _seed_parts():
        buffer = ""
        for line in part.read_text(encoding="utf-8").splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                buffer = ""
        leftover = [ln for ln in buffer.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        assert leftover == [], f"{part.name} ends inside a statement: {leftover[:1]}"


def test_seed_loader_applies_parts_in_numeric_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts_dir = tmp_path / "seeds"
    parts_dir.mkdir()
    (parts_dir / "part-01.sql").write_text(
        "CREATE TABLE IF NOT EXISTS memory_items (v TEXT);\nINSERT INTO memory_items VALUES('first');\n",
        encoding="utf-8",
    )
    (parts_dir / "part-02.sql").write_text("INSERT INTO memory_items VALUES('second');\n", encoding="utf-8")
    monkeypatch.setattr(bank, "_SEEDS_DIR", parts_dir)
    with sqlite3.connect(":memory:") as conn:
        report = bank.seed_neural(conn)
        values = [r[0] for r in conn.execute("SELECT v FROM memory_items ORDER BY rowid")]
    assert values == ["first", "second"]
    assert report["items_after"] == 2
    assert report["parts"] == ["part-01.sql", "part-02.sql"]


def test_seed_loader_fails_closed_on_a_missing_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts_dir = tmp_path / "seeds"
    parts_dir.mkdir()
    (parts_dir / "part-01.sql").write_text(
        "CREATE TABLE IF NOT EXISTS memory_items (v TEXT);\n", encoding="utf-8"
    )
    (parts_dir / "part-03.sql").write_text("INSERT INTO memory_items VALUES('orphan');\n", encoding="utf-8")
    monkeypatch.setattr(bank, "_SEEDS_DIR", parts_dir)
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE memory_items (v TEXT)")
        with pytest.raises(bank.NeuralBankError) as exc:
            bank.seed_neural(conn)
        assert exc.value.reason_code == "SEEDS_INCOMPLETE"
        assert conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 0


def test_bootstrap_with_packaged_seed_parts_reports_every_part(tmp_path: Path) -> None:
    result = bootstrap_neural(data_dir=tmp_path, apply_seeds=True)
    assert result["seeds"]["parts"] == [p.name for p in _seed_parts()]
    assert result["memory_items"] == result["seeds"]["items_after"]


def test_seed_loader_rejects_non_canonical_or_duplicate_part_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts_dir = tmp_path / "seeds"
    parts_dir.mkdir()
    (parts_dir / "part-1.sql").write_text("CREATE TABLE IF NOT EXISTS memory_items (v TEXT);\n", encoding="utf-8")
    monkeypatch.setattr(bank, "_SEEDS_DIR", parts_dir)
    with sqlite3.connect(":memory:") as conn:
        with pytest.raises(bank.NeuralBankError) as exc:
            bank.seed_neural(conn)
        assert exc.value.reason_code == "SEEDS_INVALID"
    (parts_dir / "part-1.sql").unlink()
    (parts_dir / "part-01.sql").write_text("CREATE TABLE IF NOT EXISTS memory_items (v TEXT);\n", encoding="utf-8")
    (parts_dir / "part-001.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with sqlite3.connect(":memory:") as conn:
        with pytest.raises(bank.NeuralBankError) as exc:
            bank.seed_neural(conn)
        assert exc.value.reason_code == "SEEDS_INVALID"
