"""Ecosystem data catalog under Mapper SIMPLICIO_DATA_DIR."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from simplicio_mapper.store.catalog import (
    ECOSYSTEM_BANKS,
    absorb_all,
    absorb_bank,
    data_status,
    ensure_mapper_memory,
    layout_tree,
)


def test_layout_lists_core_banks() -> None:
    layout = layout_tree()
    ids = {b["id"] for b in layout["banks"]}
    assert "mapper-memory" in ids
    assert "neural" in ids
    assert "operations" in ids
    assert len(ECOSYSTEM_BANKS) >= 10


def test_absorb_all_from_legacy_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = home / ".simplicio"
    (legacy / "memory").mkdir(parents=True)
    (legacy / "ops").mkdir(parents=True)
    (legacy / "ledger").mkdir(parents=True)

    # minimal neural-shaped sqlite
    neural = legacy / "memory" / "simplicio-memory.sqlite"
    with sqlite3.connect(neural) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE memory_items (id INTEGER PRIMARY KEY, stable_id TEXT UNIQUE, "
            "kind TEXT, source TEXT, title TEXT, content TEXT)"
        )
        conn.execute(
            "INSERT INTO memory_items(stable_id, kind, source, title, content) "
            "VALUES ('a','fact','t','t','legacy neural')"
        )
        for mid in [
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
        ]:
            conn.execute("INSERT INTO schema_migrations(id) VALUES (?)", (mid,))
        conn.commit()

    (legacy / "memory" / "interactions.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    (legacy / "ops" / "events.jsonl").write_text('{"e":1}\n', encoding="utf-8")
    (legacy / "ledger" / "savings-events.jsonl").write_text('{"s":1}\n', encoding="utf-8")
    (legacy / "operator-check.json").write_text("{}", encoding="utf-8")

    data_root = tmp_path / "data"
    ensure_mapper_memory(data_dir=data_root)
    out = absorb_all(data_dir=data_root, home=home, backup=False)
    assert out["status"] == "complete"
    assert (data_root / "simplicio-memory.sqlite").is_file()
    assert (data_root / "memory" / "interactions.jsonl").is_file()
    assert (data_root / "ops" / "events.jsonl").is_file()
    assert (data_root / "ecosystem-data-catalog.json").is_file()
    status = data_status(data_dir=data_root, home=home)
    by_id = {b["id"]: b for b in status["banks"]}
    assert by_id["neural"]["status"] == "ready"
    assert by_id["mapper-memory"]["status"] == "ready"
    assert by_id["interactions"]["status"] == "ready"


def test_absorb_single_bank(tmp_path: Path) -> None:
    home = tmp_path / "h"
    src = home / ".simplicio" / "runtime-resource-map.json"
    src.parent.mkdir(parents=True)
    src.write_text('{"ok":true}', encoding="utf-8")
    data_root = tmp_path / "d"
    report = absorb_bank("runtime-resource-map", data_dir=data_root, home=home, backup=False)
    assert report["status"] == "absorbed"
    assert (data_root / "runtime-resource-map.json").read_text(encoding="utf-8") == '{"ok":true}'
    manifest_round = absorb_bank("runtime-resource-map", data_dir=data_root, home=home, backup=False)
    assert manifest_round["status"] == "unchanged"
