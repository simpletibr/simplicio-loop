from __future__ import annotations

import json
from pathlib import Path

from scripts.mapper_store_inventory import ALLOWLIST, SCHEMA, inventory, main
from simplicio.store_adapter import MapperStoreAdapter, storage_capabilities


def test_inventory_covers_current_production_sqlite_stores() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = inventory(root)
    paths = {row["path"] for row in payload["stores"]}
    assert payload["schema"] == SCHEMA
    assert paths == {
        "simplicio/store_adapter.py",
        "simplicio/templates/stacks/py-django/tree/config/settings.py",
    }
    assert payload["direct_connections_outside_allowlist"] == []
    assert payload["strict_violations"] == []
    assert payload["strict"] is True
    assert all(row["path"] in ALLOWLIST for row in payload["occurrences"] if row["direct_connection"])


def test_mapper_store_adapter_round_trip_and_lock(tmp_path: Path) -> None:
    adapter = MapperStoreAdapter(tmp_path, "test-domain")
    with adapter.lock("key-1", operation="test"):
        adapter.write("key-1", {"schema": "test/v1", "value": 1})
        assert adapter.read("key-1") == {"schema": "test/v1", "value": 1}
    assert list((tmp_path / ".simplicio" / "mapper-store" / "test-domain").glob("*.json"))


def test_storage_capabilities_are_read_only_and_report_mapper_route(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    payload = storage_capabilities(tmp_path)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    assert before == after == []
    assert payload["schema"] == "simplicio.dev-cli.storage-capabilities/v1"
    assert payload["read_only"] is True
    assert payload["side_effects"] == {"directories_created": 0, "files_created": 0, "writes": 0}
    assert payload["route"]["frozen_before_effect"] is True


def test_inventory_strict_gate_rejects_new_direct_connection(tmp_path: Path, capsys) -> None:
    source = tmp_path / "simplicio" / "new_store.py"
    source.parent.mkdir()
    source.write_text("import sqlite3\nsqlite3.connect('new.sqlite3')\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--strict"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict"] is False
    assert payload["direct_connections_outside_allowlist"][0]["path"] == "simplicio/new_store.py"


def test_inventory_writes_digest_bound_receipt(tmp_path: Path) -> None:
    output = tmp_path / "inventory.json"
    assert main(["--root", str(tmp_path), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["inventory_digest"].startswith("sha256:")
