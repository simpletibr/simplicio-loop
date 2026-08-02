from __future__ import annotations

from pathlib import Path

from simplicio.store_adapter import MapperOperationsAdapter


def test_operations_adapter_uses_canonical_mapper_database(tmp_path: Path) -> None:
    adapter = MapperOperationsAdapter(tmp_path)

    assert adapter.database == tmp_path / ".simplicio" / "data" / "operations.sqlite"
    assert not (tmp_path / ".simplicio").exists()

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
    assert not (tmp_path / ".simplicio" / "mapper-store").exists()
