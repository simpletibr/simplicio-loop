from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import pytest

from scripts.mapper_store_inventory import ALLOWLIST, SCHEMA, inventory, main
from simplicio.store_adapter import MapperStoreAdapter, StoreAdapterError, storage_capabilities


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


def test_mapper_store_adapter_reads_missing_and_rejects_corrupt_records(tmp_path: Path) -> None:
    adapter = MapperStoreAdapter(tmp_path, "test-domain")

    assert adapter.read("missing") is None
    adapter.record_path("invalid").write_text("not-json", encoding="utf-8")
    with pytest.raises(StoreAdapterError, match="STORE_CORRUPT"):
        adapter.read("invalid")
    adapter.record_path("list").write_text("[]", encoding="utf-8")
    with pytest.raises(StoreAdapterError, match="STORE_CORRUPT"):
        adapter.read("list")


def test_mapper_store_adapter_retries_transient_replace(tmp_path: Path, monkeypatch) -> None:
    import simplicio.store_adapter as store_adapter

    adapter = MapperStoreAdapter(tmp_path, "test-domain")
    real_replace = store_adapter.os.replace
    attempts = 0

    def replace_once(source, target):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(5, "access denied")
        real_replace(source, target)

    monkeypatch.setattr(store_adapter.os, "replace", replace_once)
    adapter.write("retry", {"value": 1})

    assert attempts == 2
    assert adapter.read("retry") == {"value": 1}


def test_mapper_store_adapter_acquire_release_and_write_failure(tmp_path: Path, monkeypatch) -> None:
    import simplicio.store_adapter as store_adapter

    adapter = MapperStoreAdapter(tmp_path, "test-domain")
    handle = adapter.acquire("key", operation="test")
    adapter.release(handle)

    monkeypatch.setattr(
        store_adapter.os,
        "replace",
        lambda source, target: (_ for _ in ()).throw(PermissionError(5, "access denied")),
    )
    with pytest.raises(StoreAdapterError, match="STORE_WRITE_FAILED"):
        adapter.write("failure", {"value": 1})


def test_mapper_store_adapter_reports_lock_and_api_failures(tmp_path: Path, monkeypatch) -> None:
    import simplicio.store_adapter as store_adapter

    adapter = MapperStoreAdapter(tmp_path, "test-domain")
    monkeypatch.setattr(store_adapter, "acquire_lock_at", lambda *args, **kwargs: None)
    with pytest.raises(StoreAdapterError, match="STORE_LOCKED"):
        adapter.acquire("locked", operation="test")
    with pytest.raises(StoreAdapterError, match="STORE_LOCKED"):
        with adapter.lock("locked", operation="test"):
            pass

    monkeypatch.setattr(store_adapter, "acquire_lock_at", None)
    with pytest.raises(StoreAdapterError, match="mapper-api-unavailable"):
        adapter.acquire("unavailable", operation="test")
    with pytest.raises(StoreAdapterError, match="mapper-api-unavailable"):
        with adapter.lock("unavailable", operation="test"):
            pass
    monkeypatch.setattr(store_adapter, "release_lock_at", None)
    with pytest.raises(StoreAdapterError, match="mapper-api-unavailable"):
        adapter.release(object())


def test_mapper_status_reports_uninstalled_and_unparseable_versions(monkeypatch) -> None:
    import simplicio.store_adapter as store_adapter

    monkeypatch.delenv("SIMPLICIO_MAPPER_VERSION", raising=False)
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError(name)),
    )
    assert store_adapter._mapper_status() == (None, False, "mapper-package-not-installed")

    monkeypatch.setenv("SIMPLICIO_MAPPER_VERSION", "development")
    assert store_adapter._mapper_status() == ("development", False, "mapper-version-incompatible")


def test_storage_capabilities_are_read_only_and_report_mapper_route(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    payload = storage_capabilities(tmp_path)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    assert before == after == []
    assert payload["schema"] == "simplicio.dev-cli.storage-capabilities/v1"
    assert payload["read_only"] is True
    assert payload["side_effects"] == {"directories_created": 0, "files_created": 0, "writes": 0}
    assert payload["route"]["frozen_before_effect"] is True


def test_storage_capabilities_fail_closed_for_incompatible_mapper(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_MAPPER_VERSION", "0.25.9")
    payload = storage_capabilities(tmp_path)

    assert payload["mapper_store"]["ready"] is False
    assert payload["mapper_store"]["reason"] == "mapper-version-incompatible"
    assert payload["route"] == {
        "selected": "blocked",
        "frozen_before_effect": True,
        "reason": "mapper-version-incompatible",
    }
    assert not (tmp_path / ".simplicio").exists()


def test_mapper_store_adapter_refuses_incompatible_mapper_before_materializing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SIMPLICIO_MAPPER_VERSION", "0.25.9")
    try:
        MapperStoreAdapter(tmp_path, "blocked")
    except RuntimeError as exc:
        assert str(exc) == "MAPPER_STORE_UNAVAILABLE:mapper-version-incompatible"
    else:
        raise AssertionError("incompatible Mapper must block before adapter initialization")
    assert not (tmp_path / ".simplicio").exists()


def test_storage_capabilities_fail_closed_when_mapper_api_is_absent(tmp_path: Path, monkeypatch) -> None:
    import simplicio.store_adapter as store_adapter

    monkeypatch.setattr(store_adapter, "_MAPPER_IMPORT_ERROR", ModuleNotFoundError("simplicio_mapper"))
    payload = storage_capabilities(tmp_path)

    assert payload["mapper_store"]["ready"] is False
    assert payload["mapper_store"]["reason"] == "mapper-package-not-installed"
    assert payload["route"]["selected"] == "blocked"
    assert not (tmp_path / ".simplicio").exists()


def test_mapper_store_adapter_freezes_route_before_first_record(tmp_path: Path, monkeypatch) -> None:

    adapter = MapperStoreAdapter(tmp_path, "route-test")
    route = tmp_path / ".simplicio" / "mapper-store" / "route.json"
    first = json.loads(route.read_text(encoding="utf-8"))
    assert first["selected"] == "mapper-store"
    adapter.write("key", {"value": 1})

    monkeypatch.setenv("SIMPLICIO_MAPPER_VERSION", "0.25.9")
    with pytest.raises(StoreAdapterError, match="mapper-version-incompatible"):
        MapperStoreAdapter(tmp_path, "route-test")
    blocked = storage_capabilities(tmp_path)
    assert blocked["route"]["selected"] == "mapper-store"
    assert blocked["route"]["reason"] == "mapper-version-incompatible"
    assert json.loads(route.read_text(encoding="utf-8")) == first
    assert not (tmp_path / ".simplicio" / "effect-transactions.sqlite3").exists()
    monkeypatch.delenv("SIMPLICIO_MAPPER_VERSION")
    payload = storage_capabilities(tmp_path)
    assert payload["route"]["frozen"] is True
    assert payload["route"]["receipt"] == first


def test_mapper_store_route_freeze_retries_concurrent_replace(tmp_path: Path, monkeypatch) -> None:
    import simplicio.store_adapter as store_adapter

    real_replace = store_adapter.os.replace
    calls = {"count": 0}

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("route is temporarily shared")
        return real_replace(source, destination)

    monkeypatch.setattr(store_adapter.os, "replace", flaky_replace)
    MapperStoreAdapter(tmp_path, "route-retry")

    route = tmp_path / ".simplicio" / "mapper-store" / "route.json"
    assert json.loads(route.read_text(encoding="utf-8"))["selected"] == "mapper-store"
    assert calls["count"] == 2
    assert not list(route.parent.glob("route.tmp-*"))


def test_mapper_store_adapter_blocks_partial_mapper_capability_before_materializing(
    tmp_path: Path, monkeypatch
) -> None:
    import simplicio.store_adapter as store_adapter

    monkeypatch.setattr(store_adapter, "release_lock_at", None)
    with pytest.raises(StoreAdapterError, match="mapper-api-unavailable"):
        MapperStoreAdapter(tmp_path, "partial")
    assert not (tmp_path / ".simplicio").exists()


def test_inventory_strict_gate_rejects_new_direct_connection(tmp_path: Path, capsys) -> None:
    source = tmp_path / "simplicio" / "new_store.py"
    source.parent.mkdir()
    source.write_text("import sqlite3\nsqlite3.connect('new.sqlite3')\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--strict"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict"] is False
    assert payload["direct_connections_outside_allowlist"][0]["path"] == "simplicio/new_store.py"


def test_inventory_reports_materialized_mapper_files_with_plans(tmp_path: Path) -> None:
    route = tmp_path / ".simplicio" / "mapper-store" / "route.json"
    record = tmp_path / ".simplicio" / "mapper-store" / "memory-index" / "record.json"
    route.parent.mkdir(parents=True)
    record.parent.mkdir(parents=True)
    route.write_text('{"schema":"simplicio.dev-cli.storage-route/v1"}', encoding="utf-8")
    record.write_text("{}", encoding="utf-8")

    payload = inventory(tmp_path)
    materialized = {row["path"]: row for row in payload["materialized_files"]}
    assert set(materialized) == {
        ".simplicio/mapper-store/route.json",
        ".simplicio/mapper-store/memory-index/record.json",
    }
    assert (
        materialized[".simplicio/mapper-store/memory-index/record.json"]["owner"] == "Dev CLI memory adapter"
    )
    assert materialized[".simplicio/mapper-store/route.json"]["target"]
    assert len(payload["store_plans"]) == 7
    assert payload["strict"] is True


def test_inventory_writes_digest_bound_receipt(tmp_path: Path) -> None:
    output = tmp_path / "inventory.json"
    assert main(["--root", str(tmp_path), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["inventory_digest"].startswith("sha256:")
