"""Tests for the read-only MapperStore inventory contract (issue #473)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mapper_store_inventory", ROOT / "scripts/mapper_store_inventory.py")
INVENTORY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = INVENTORY
SPEC.loader.exec_module(INVENTORY)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_source_scan_captures_cross_language_evidence_and_redacts_secrets(tmp_path: Path) -> None:
    _write(tmp_path, "src/store.py", "import sqlite3\nDB = 'sqlite:///memory.sqlite'\nTOKEN = 'secret-value'\n")
    _write(tmp_path, "src/store.rs", "use rusqlite::Connection;\nlet db = Connection::open(\"operations.sqlite\");\n")
    _write(tmp_path, "schema.sql", "CREATE TABLE users (id INTEGER PRIMARY KEY);\nPRAGMA journal_mode=WAL;\n")

    payload = INVENTORY.build_inventory([("mapper", tmp_path)], [], deterministic=True)

    assert payload["schema"] == INVENTORY.SCHEMA
    assert payload["generated_at"] is None
    assert {"mapper"} == {row["repo"] for row in payload["matches"]}
    assert any("ddl" in row["kinds"] for row in payload["matches"])
    evidence = json.dumps(payload)
    assert "secret-value" not in evidence


def test_database_inspection_is_read_only_and_extracts_schema(tmp_path: Path) -> None:
    database = tmp_path / "operations.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
        connection.execute("CREATE INDEX tasks_state ON tasks(state)")
        connection.commit()
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    payload = INVENTORY.build_inventory([], [("loop", database)], deterministic=True)

    record = payload["databases"][0]
    assert record["status"] == "readable"
    assert record["read_only_inspection"] is True
    assert record["objects"][0]["name"] == "tasks"
    assert record["objects"][0]["columns"][0]["name"] == "id"
    assert record["path"] == "operations.sqlite"
    assert any(row.get("table") == "tasks" for row in payload["ownership_matrix"])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_policy_distinguishes_mapper_violations_from_legacy_consumer_ddl(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", "connection.execute('CREATE TABLE legacy (id INTEGER)')\n")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    _write(legacy, "loop.py", "connection.execute('CREATE TABLE queue (id INTEGER)')\n")

    payload = INVENTORY.build_inventory([("mapper", tmp_path), ("loop", legacy)], [], deterministic=True)

    assert payload["policy"]["status"] == "fail"
    assert any(row["repo"] == "mapper" for row in payload["policy"]["violations"])
    assert payload["policy"]["legacy_ddl_matches"] >= 1


def test_golden_fixture_matches_the_versioned_schema() -> None:
    schema = json.loads((ROOT / "contracts/mapper-store/v1/schemas/inventory.schema.json").read_text())
    fixture = json.loads((ROOT / "contracts/mapper-store/v1/fixtures/minimal/inventory.json").read_text())

    from simplicio_mapper.contract import validate_instance

    assert validate_instance(fixture, schema) == []


@pytest.mark.parametrize("relative", ["tests/fixtures/source.py", "contracts/mapper-store/v1/fixtures/sample.sql"])
def test_fixture_paths_are_not_policy_violations(tmp_path: Path, relative: str) -> None:
    _write(tmp_path, relative, "CREATE TABLE fixture_rows (id INTEGER);\n")

    payload = INVENTORY.build_inventory([("mapper", tmp_path)], [], deterministic=True)

    assert payload["policy"]["status"] == "pass"
    assert payload["policy"]["violations"] == []


def test_cli_entrypoint_emits_contract_json(tmp_path: Path) -> None:
    _write(tmp_path, "src/store.py", "import sqlite3\nDB = 'semantic.sqlite'\n")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/mapper_store_inventory.py"),
            "--repo",
            f"mapper={tmp_path}",
            "--deterministic",
            "--check-ddl",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == INVENTORY.SCHEMA
    assert payload["policy"]["status"] == "pass"
    assert payload["matches"][0]["repo"] == "mapper"
