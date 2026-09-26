"""Tests for the read-only MapperStore inventory contract (issue #473)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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
    _write(tmp_path, "schema.sql", "CREATE TABLE users (id INTEGER PRIMARY KEY);\nCREATE TEMP INDEX users_tmp ON users(id);\nPRAGMA journal_mode=WAL;\n")

    payload = INVENTORY.build_inventory([("mapper", tmp_path)], [], deterministic=True)

    assert payload["schema"] == INVENTORY.SCHEMA
    assert payload["generated_at"] is None
    assert {"mapper"} == {row["repo"] for row in payload["matches"]}
    assert any("ddl" in row["kinds"] for row in payload["matches"])
    assert any(row["target_path"].endswith("operations.sqlite") for row in payload["ownership_matrix"])
    evidence = json.dumps(payload)
    assert "secret-value" not in evidence


def test_policy_counts_only_critical_behavioral_legacy_writers() -> None:
    policy = INVENTORY._policy([
        {"repo": "loop", "file": "README.md", "kinds": ["ddl"],
         "criticality": "informational", "writers": []},
        {"repo": "loop", "file": "src/store.py", "kinds": ["ddl"],
         "criticality": "critical", "writers": ["loop"]},
        {"repo": "loop", "file": "tests/test_store.py", "kinds": ["ddl"],
         "criticality": "test-only", "writers": ["loop"]},
    ])
    assert policy["legacy_ddl_matches"] == 1
    assert policy["legacy_ddl_files"] == [{"repo": "loop", "file": "src/store.py"}]


def test_write_evidence_excludes_read_only_adapter_references() -> None:
    assert INVENTORY._has_write_evidence([
        "let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY);",
        "conn.execute(\"SELECT COUNT(*) FROM ops_tasks\", [])?;",
    ]) is False
    assert INVENTORY._has_write_evidence([
        "conn.execute(\"CREATE TABLE IF NOT EXISTS ops_tasks (...)\", [])?;",
    ]) is True


def test_write_evidence_ignores_policy_text_read_only_probes_and_temp_tables() -> None:
    assert INVENTORY._has_write_evidence([
        '# the policy blocks "DROP TABLE" actions',
        'cursor.execute("PRAGMA table_info(\\"tasks\\")")',
        'conn.execute("CREATE TEMP TABLE probe (id INTEGER)")',
    ]) is False


def test_ddl_evidence_excludes_test_and_temporary_tables() -> None:
    assert INVENTORY._has_persistent_ddl_evidence(
        [
            "#[cfg(test)]",
            "mod tests {",
            '    conn.execute_batch("CREATE TABLE fixture_rows (id INTEGER);")?;',
            "}",
        ],
        suffix=".rs",
    ) is False
    assert INVENTORY._has_persistent_ddl_evidence(
        ['conn.execute_batch("CREATE VIRTUAL TABLE temp.probe USING fts5(x);")?;'],
        suffix=".rs",
    ) is False
    assert INVENTORY._has_persistent_ddl_evidence(
        ['conn.execute_batch("CREATE TABLE production_rows (id INTEGER);")?;'],
        suffix=".rs",
    ) is True
    assert INVENTORY._has_persistent_ddl_evidence(
        [
            "def check_sql(query):",
            '    con = sqlite3.connect(":memory:")',
            '    con.executescript("CREATE TABLE customers(id INTEGER);")',
            "    return con.execute(query).fetchall()",
        ],
        suffix=".py",
    ) is False
    assert INVENTORY._has_persistent_ddl_evidence(
        [
            "def create_store(path):",
            '    con = sqlite3.connect(path)',
            '    con.executescript("CREATE TABLE production_rows(id INTEGER);")',
        ],
        suffix=".py",
    ) is True


def test_write_evidence_tracks_multiline_execution_calls() -> None:
    assert INVENTORY._has_write_evidence([
        'connection.execute_batch(',
        '    "CREATE TABLE tasks (id INTEGER);",',
        ')',
    ]) is True


def test_write_evidence_ignores_rust_cfg_test_module_schemas() -> None:
    assert INVENTORY._has_write_evidence(
        [
            "#[cfg(test)]",
            "mod tests {",
            '    conn.execute_batch("CREATE TABLE fixture_rows (id INTEGER);")?;',
            "}",
        ],
        suffix=".rs",
    ) is False
    assert INVENTORY._has_write_evidence(
        [
            'conn.execute_batch("CREATE TABLE production_rows (id INTEGER);")?;',
            "#[cfg(test)]",
            "mod tests {",
            '    conn.execute_batch("CREATE TABLE fixture_rows (id INTEGER);")?;',
            "}",
        ],
        suffix=".rs",
    ) is True


def test_write_evidence_does_not_treat_unexecuted_sql_strings_as_writers() -> None:
    assert INVENTORY._has_write_evidence([
        'let sql = "CREATE TABLE vectors (id INTEGER)";',
        'let risk = "DROP TABLE users";',
    ]) is False


def test_redaction_covers_bearer_headers_and_sql_default_values(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/auth.py",
        "Authorization: Bearer bearer-secret; sqlite3\nAWS_SECRET_ACCESS_KEY='aws secret/punct!'\nDATABASE_PASSWORD=\"db secret;punct\"\nGITHUB_TOKEN=github-secret\nCREATE TEMP TRIGGER audit AFTER INSERT ON users BEGIN SELECT 1; END;\nCREATE TABLE users (client_secret TEXT DEFAULT 'DB SECRET; punct');\n",
    )

    payload = INVENTORY.build_inventory([("mapper", tmp_path)], [], deterministic=True)

    evidence = json.dumps(payload)
    assert "bearer-secret" not in evidence
    assert "DB_SECRET" not in evidence
    assert "DB SECRET; punct" not in evidence
    assert "aws secret/punct!" not in evidence
    assert "db secret;punct" not in evidence
    assert "github-secret" not in evidence
    assert "Bearer <redacted>" in evidence


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


def test_explicit_database_accepts_extensionless_files_and_records_sidecars(tmp_path: Path) -> None:
    database = tmp_path / "store"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY)")
    (tmp_path / "store-wal").write_bytes(b"wal-evidence")

    payload = INVENTORY.build_inventory([], [("loop", database)], deterministic=True)

    assert payload["databases"][0]["path"] == "store"
    assert "wal" in payload["databases"][0]["sidecar_sha256"]


def test_explicit_database_rejects_symlinks_before_resolution(tmp_path: Path) -> None:
    target = tmp_path / "outside.sqlite"
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY)")
    link = tmp_path / "linked.sqlite"
    os.symlink(target, link)

    with pytest.raises(SystemExit, match="must not be a symlink"):
        INVENTORY.main(["--database", f"external={link}"])


def test_database_discovery_excludes_caches_wal_sidecars_and_external_symlinks(tmp_path: Path) -> None:
    visible = tmp_path / "store.sqlite"
    with sqlite3.connect(visible) as connection:
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY)")
    cache = tmp_path / ".mypy_cache" / "cache.db"
    cache.parent.mkdir()
    cache.write_bytes(visible.read_bytes())
    (tmp_path / "store.sqlite-wal").write_bytes(b"sidecar")
    (tmp_path / "store.sqlite-shm").write_bytes(b"sidecar")
    outside = tmp_path.parent / "mapper-store-outside.sqlite"
    outside.write_bytes(visible.read_bytes())
    os.symlink(outside, tmp_path / "linked.sqlite")

    payload = INVENTORY.build_inventory([("mapper", tmp_path)], [], deterministic=True)

    assert [record["path"] for record in payload["databases"]] == ["store.sqlite"]


def test_versions_support_a_root_rust_manifest(tmp_path: Path) -> None:
    _write(tmp_path, "Cargo.toml", '[package]\nname = "runtime"\nversion = "3.5.5"\n')

    assert INVENTORY._versions(tmp_path)["rust"] == "3.5.5"


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
    schema = json.loads((ROOT / "simplicio_mapper/contracts/mapper-store/v1/schemas/inventory.schema.json").read_text())
    fixture = json.loads((ROOT / "simplicio_mapper/contracts/mapper-store/v1/fixtures/minimal/inventory.json").read_text())

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
