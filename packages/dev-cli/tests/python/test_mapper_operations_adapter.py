from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from simplicio.store_adapter import MapperOperationsAdapter, StoreAdapterError


class FakeOperationsStore:
    records: dict[str, dict[str, object]] = {}

    def __init__(self, _database: Path, *, auto_create: bool) -> None:
        if not auto_create:
            return

    def initialize(self) -> dict[str, str]:
        return {"status": "ready"}

    def enqueue(
        self,
        task_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str,
        priority: int = 0,
    ) -> dict[str, object]:
        record = {
            "schema": "simplicio.mapper-store.operations-api/v1",
            "task_id": task_id,
            "payload": payload,
            "state": "queued",
        }
        self.records[idempotency_key] = record
        return record

    def find_task(self, idempotency_key: str) -> dict[str, object] | None:
        return self.records.get(idempotency_key)

    def update_payload(self, task_id: str, payload: dict[str, object]) -> dict[str, str]:
        for record in self.records.values():
            if record["task_id"] == task_id:
                record["payload"] = payload
        return {"status": "payload_updated"}


def _install_operations_store(monkeypatch, store: type) -> None:
    module = types.ModuleType("simplicio_mapper.store")
    module.OperationsStore = store  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "simplicio_mapper.store", module)


def test_operations_adapter_uses_canonical_mapper_database(tmp_path: Path, monkeypatch) -> None:
    FakeOperationsStore.records = {}
    _install_operations_store(monkeypatch, FakeOperationsStore)
    adapter = MapperOperationsAdapter(tmp_path)

    assert adapter.database == tmp_path / ".simplicio-loop" / "data" / "operations.sqlite"
    assert not (tmp_path / ".simplicio-loop").exists()

    ready = adapter.initialize()
    assert ready["status"] == "ready"
    adapter.enqueue("task-1", {"value": 1}, idempotency_key="idem-1")

    assert adapter.find_task("idem-1") == {
        "schema": "simplicio.mapper-store.operations-api/v1",
        "task_id": "task-1",
        "payload": {"value": 1},
        "state": "queued",
    }
    assert adapter.update_payload("task-1", {"value": 2})["status"] == "payload_updated"
    assert adapter.find_task("idem-1")["payload"] == {"value": 2}
    assert not (tmp_path / ".simplicio-loop" / "mapper-store").exists()


def test_operations_adapter_rejects_incomplete_mapper_store_api(tmp_path: Path, monkeypatch) -> None:
    class IncompleteOperationsStore:
        pass

    _install_operations_store(monkeypatch, IncompleteOperationsStore)
    adapter = MapperOperationsAdapter(tmp_path)

    with pytest.raises(StoreAdapterError, match="operations-api-missing"):
        adapter.find_task("missing-api")


def test_operations_adapter_wraps_store_initialization_failure(tmp_path: Path, monkeypatch) -> None:
    class BrokenOperationsStore:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("broken store")

        def initialize(self):
            raise AssertionError("constructor should fail first")

        def enqueue(self, *_args, **_kwargs):
            raise AssertionError("constructor should fail first")

        def find_task(self, *_args, **_kwargs):
            raise AssertionError("constructor should fail first")

        def update_payload(self, *_args, **_kwargs):
            raise AssertionError("constructor should fail first")

    _install_operations_store(monkeypatch, BrokenOperationsStore)
    adapter = MapperOperationsAdapter(tmp_path)

    with pytest.raises(StoreAdapterError, match="operations-store-init"):
        adapter.find_task("broken-store")
