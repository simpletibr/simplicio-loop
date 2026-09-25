"""System and regression coverage for the canonical MapperStore facade."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from simplicio_mapper.contract import validate_instance
from simplicio_mapper.store import MapperStore, MapperStoreError, MemoryStoreError


def _schema(name: str) -> dict:
    root = Path(__file__).parents[2] / "contracts/mapper-store/v1/schemas"
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_mapper_store_initializes_one_canonical_pair_and_reader_is_read_only(tmp_path: Path) -> None:
    store = MapperStore(tmp_path / "data")
    receipt = store.initialize()
    assert receipt["store_schema"] == "simplicio.mapper-store/v1"
    assert store.status()["status"] == "ready"
    assert {path.name for path in (tmp_path / "data").glob("*.sqlite")} == {"memory.sqlite", "operations.sqlite"}
    reader = store.read_only()
    assert reader.status()["valid"] is True
    assert not hasattr(reader, "record")
    assert validate_instance(receipt, _schema("store.schema.json")) == []
    assert validate_instance(store.capabilities(), _schema("capability.schema.json")) == []
    assert validate_instance(store.conformance(), _schema("conformance-api.schema.json")) == []


def test_schema_drift_fails_closed_before_writing(tmp_path: Path) -> None:
    store = MapperStore(tmp_path / "data")
    store.initialize()
    with sqlite3.connect(store.memory_database) as connection:
        connection.execute("UPDATE memory_store_meta SET value='future' WHERE key='schema'")
    with pytest.raises(MemoryStoreError):
        store.memory.store("drift", "must fail")
    with store.memory._open(read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_items").fetchone()[0] == 0
    assert store.status()["valid"] is False
    assert store.capabilities()["available"] is False


def test_canonical_initialize_preflights_operations_drift(tmp_path: Path) -> None:
    store = MapperStore(tmp_path / "data")
    store.initialize()
    with sqlite3.connect(store.operations_database) as connection:
        connection.execute("UPDATE operations_meta SET value='future' WHERE key='schema_version'")
    with pytest.raises(MapperStoreError, match="STORE_SCHEMA_DRIFT"):
        store.initialize()


def test_records_have_stable_provenance_and_precedents_remain_candidates(tmp_path: Path) -> None:
    store = MapperStore(tmp_path / "data", repository_id="repo", generation="gen-1")
    store.initialize()
    first = store.record_run({"files": ["a.py"]}, source="mapper", producer="mapper", version="7", consent={"scope": "repo"})
    second = store.record_run({"files": ["a.py"]}, source="mapper", producer="mapper", version="7", consent={"scope": "repo"})
    assert first["stable_id"] == second["stable_id"]
    assert second["status"] == "unchanged"
    record = store.read_record(first["stable_id"])
    assert record["provenance"]["generation"] == "gen-1"
    assert record["consent"] == {"scope": "repo"}
    reader = store.read_only()
    assert reader.read_record(first["stable_id"])["provenance"]["generation"] == "gen-1"
    assert set(reader.capabilities()["readers"]) == {"runtime", "fast", "loop", "mcp"}
    precedent = store.record_precedent(
        {"rule": "prefer small changes"}, applicability_evidence={"tests": ["test_one"]}
    )
    candidate = store.read_record(precedent["stable_id"])
    assert candidate["metadata"]["approval_status"] == "candidate"
    assert candidate["metadata"]["applicability_evidence"] == {"tests": ["test_one"]}
    with pytest.raises(MapperStoreError, match="APPLICABILITY_EVIDENCE_REQUIRED"):
        store.record("precedent", {"rule": "unproven"})


def test_semantic_results_report_actual_backend_model_and_dimension(tmp_path: Path) -> None:
    store = MapperStore(tmp_path / "data")
    store.initialize()
    store.record_change({"change": "index"})
    result = store.memory.semantic.recall("index", mode="hybrid")
    assert result["backend"] == "brute-force"
    assert result["model"] == "memory-lexical-v1"
    assert result["dimensions"] == 128
    assert result["ann_claimed"] is False
    assert result["results"][0]["embedding_provenance"]["model"] == "memory-lexical-v1"
    assert validate_instance(result, _schema("semantic-recall.schema.json")) == []


def test_canonical_facade_owns_operation_events_and_tombstones(tmp_path: Path) -> None:
    store = MapperStore(tmp_path / "data")
    store.initialize()
    record = store.record_change({"change": "remove-me"})
    event = store.append_event("run-1", "recorded", {"stable_id": record["stable_id"]})
    assert event["status"] == "appended"
    assert store.replay("run-1")["events"][0]["event_type"] == "recorded"
    assert store.operations_status()["counts"] == {
        "queued": 0,
        "running": 0,
        "completed": 0,
        "cancelled": 0,
        "failed": 0,
    }
    assert store.tombstone(record["stable_id"], reason="test")["status"] == "tombstoned"
    assert store.read_record(record["stable_id"])["tombstone"] is True


def test_legacy_absorb_is_lossless_lineaged_and_idempotent(tmp_path: Path) -> None:
    legacy = tmp_path / "simplicio-memory.sqlite"
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            """CREATE TABLE memory_items (
                id INTEGER PRIMARY KEY, stable_id TEXT UNIQUE, kind TEXT, source TEXT,
                title TEXT, content TEXT, artifact_path TEXT, source_hash TEXT,
                metadata TEXT, provenance TEXT, tags TEXT, weight REAL,
                created_at TEXT, updated_at TEXT)"""
        )
        connection.execute(
            "INSERT INTO memory_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, "mapper-run:legacy-1", "mapper-run", "runtime", "run", "old content", "run.json", "abc", json.dumps({"generation": "g1", "repository_id": "r1", "consent": {"ok": True}}), json.dumps({"source": "runtime", "producer": "runtime", "version": "2"}), "run", 1.0, "2025-01-01", "2025-01-01"),
        )
        connection.execute(
            "INSERT INTO memory_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (2, "mapper-change:legacy-2", "mapper-change", "runtime", "change", "old change", None, "def", "{}", "{}", "change", 1.0, "2025-01-02", "2025-01-02"),
        )
    store = MapperStore(tmp_path / "data")
    report = store.absorb_legacy(legacy)
    assert report["imported"] == 2
    assert report["source_lineage"]["source_sha256"]
    assert report["legacy_read_only"] is True
    assert Path(report["legacy_read_only_marker"]).is_file()
    assert store.read_record("mapper-run:legacy-1")["provenance"]["legacy"]["row_id"] == 1
    assert store.read_record("mapper-run:legacy-1")["payload"]["content"] == "old content"
    replay = store.absorb_legacy(legacy)
    assert replay["status"] == "unchanged"
    assert replay["imported"] == 0
    assert replay["unchanged"] == 2
    assert len(store.list_records()) == 2
    assert validate_instance(report, _schema("legacy-absorb.schema.json")) == []


def test_legacy_stable_id_conflict_fails_closed(tmp_path: Path) -> None:
    legacy = tmp_path / "simplicio-memory.sqlite"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE memory_items (id INTEGER PRIMARY KEY, stable_id TEXT, kind TEXT, source TEXT, title TEXT, content TEXT, metadata TEXT, provenance TEXT)")
        connection.execute("INSERT INTO memory_items VALUES (1,'mapper-run:conflict','mapper-run','legacy','run','old','{}','{}')")
    store = MapperStore(tmp_path / "data")
    store.initialize()
    store.record_run({"content": "different"}, stable_id="mapper-run:conflict")
    with pytest.raises(MapperStoreError, match="LEGACY_ID_CONFLICT"):
        store.absorb_legacy(legacy)
