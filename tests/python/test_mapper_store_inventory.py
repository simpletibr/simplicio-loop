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
    schema = json.loads((ROOT / "contracts/mapper-store/v1/schemas/inventory.schema.json").read_text())
    fixture = json.loads((ROOT / "contracts/mapper-store/v1/fixtures/minimal/inventory.json").read_text())

    from simplicio_mapper.contract import validate_instance

    assert validate_instance(fixture, schema) == []


def test_committed_inventory_matches_the_versioned_schema() -> None:
    schema = json.loads((ROOT / "contracts/mapper-store/v1/schemas/inventory.schema.json").read_text())
    evidence = json.loads((ROOT / "docs/evidence/mapper-store-inventory.json").read_text())

    from simplicio_mapper.contract import validate_instance

    assert validate_instance(evidence, schema) == []
    assert evidence["policy"]["status"] == "pass"
    assert {row["id"] for row in evidence["repos"]} == {"mapper", "loop", "dev-cli", "runtime"}
    assert next(row for row in evidence["repos"] if row["id"] == "runtime")["versions"]["rust"]
    assert any(row["status"] == "readable" for row in evidence["databases"])

    repo_roots = {
        "mapper": ROOT,
        "loop": ROOT.parent / "simplicio-loop",
        "dev-cli": ROOT.parent / "simplicio-dev-cli",
        "runtime": ROOT.parent / "simplicio-runtime",
    }
    for record in evidence["databases"]:
        if record["status"] != "readable":
            continue
        database = repo_roots[record["repo"]] / record["path"]
        assert database.is_file(), database
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name")]
        assert names == [obj["name"] for obj in record.get("objects", [])]


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
