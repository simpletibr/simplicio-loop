"""Operational doctor, backup, repair and observability evidence for #480."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from simplicio_mapper.contract import validate_instance
from simplicio_mapper.store import (
    DoctorError,
    MemoryStore,
    Metrics,
    backup_store,
    capacity_report,
    doctor_store,
    metrics_for_store,
    repair_store,
    restore_store,
    run_benchmark,
    secure_export,
)

ROOT = Path(__file__).parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "simplicio_mapper/contracts/mapper-store/v1/schemas" / name).read_text(encoding="utf-8"))


def test_doctor_missing_is_side_effect_free_and_contract_valid(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "store.sqlite"
    before = set(tmp_path.rglob("*"))
    report = doctor_store(path)
    assert report["state"] == "missing"
    assert report["side_effects"] is False
    assert validate_instance(report, _schema("doctor.schema.json")) == []
    assert set(tmp_path.rglob("*")) == before


def test_doctor_distinguishes_legacy_ready_and_corrupt(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.sqlite"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY)")
    assert doctor_store(legacy)["state"] == "legacy"
    ready = tmp_path / "ready.sqlite"
    MemoryStore(ready).initialize()
    assert doctor_store(ready)["state"] == "ready"
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not sqlite")
    assert doctor_store(corrupt)["state"] == "corrupt"


def test_doctor_detects_split_brain_and_stale_migration(tmp_path: Path) -> None:
    database = tmp_path / "store.sqlite"
    MemoryStore(database).initialize()
    pointer = database.with_name(database.name + ".active.json")
    pointer.write_text(json.dumps({"writer_authority": "legacy-loop", "generation": 2}), encoding="utf-8")
    assert doctor_store(database)["state"] == "split_brain"
    pointer.unlink()
    lock = database.with_name(database.name + ".migration.lock")
    lock.write_text(json.dumps({"owner": "dead", "pid": 99999999}), encoding="utf-8")
    assert doctor_store(database)["state"] == "stale"


def test_doctor_detects_active_migration_and_incomplete_receipt(tmp_path: Path) -> None:
    database = tmp_path / "store.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE memory_store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO memory_store_meta VALUES ('schema', 'simplicio.memory/v1')")
        connection.execute(
            "CREATE TABLE migration_ledger(seq INTEGER PRIMARY KEY, event TEXT, event_hash TEXT, previous_hash TEXT)"
        )
        connection.execute("INSERT INTO migration_ledger VALUES (1, 'intent', 'hash-1', '')")
    lock = database.with_name(database.name + ".migration.lock")
    lock.write_text(json.dumps({"owner": "running", "pid": os.getpid()}), encoding="utf-8")
    report = doctor_store(database)
    assert report["state"] == "migrating"
    assert "MIGRATION_RECEIPT_INCOMPLETE" in report["reason_codes"]


def test_doctor_checks_foreign_keys_and_checksum_budget(tmp_path: Path) -> None:
    database = tmp_path / "constraints.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("CREATE TABLE memory_store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO memory_store_meta VALUES ('schema', 'simplicio.memory/v1')")
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        connection.execute("INSERT INTO child VALUES (99)")
        connection.execute("INSERT INTO memory_store_meta VALUES ('schema_checksum', 'bad')")
    report = doctor_store(database, max_bytes=1, max_rows=0)
    assert report["state"] == "corrupt"
    assert report["checks"]["foreign_keys"]["violations"] == 1
    assert "SCHEMA_CHECKSUM_MISMATCH" in report["reason_codes"]
    assert len(report["alerts"]) == 2


def test_doctor_detects_fts_drift_without_repair_side_effect(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite"
    store = MemoryStore(database)
    store.initialize()
    store.store("topic", "content for index")
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM semantic_fts")
    report = doctor_store(database)
    assert report["state"] == "ready"
    assert "FTS_OUT_OF_SYNC" in report["reason_codes"]
    plan = repair_store(database)
    assert plan["status"] == "planned"
    assert plan["side_effects"] is False


def test_backup_manifest_restore_and_no_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    MemoryStore(source).initialize()
    result = backup_store(source, tmp_path / "backup.sqlite")
    assert validate_instance(result, _schema("backup.schema.json")) == []
    manifest_path = tmp_path / "backup.sqlite.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == result["manifest"]["sha256"]
    restored = restore_store(tmp_path / "backup.sqlite", tmp_path / "restored.sqlite")
    assert restored["status"] == "restored"
    with pytest.raises(Exception, match="RESTORE_DESTINATION_EXISTS"):
        restore_store(tmp_path / "backup.sqlite", tmp_path / "restored.sqlite")
    with pytest.raises(Exception, match="RESTORE_DESTINATION_EXISTS"):
        restore_store(tmp_path / "backup.sqlite", tmp_path / "restored.sqlite", allow_overwrite=True)
    overwritten = restore_store(
        tmp_path / "backup.sqlite",
        tmp_path / "restored.sqlite",
        allow_overwrite=True,
        authorization="mapper-store-restore-overwrite/v1",
    )
    assert overwritten["status"] == "restored"


def test_backup_and_restore_fail_closed_on_existing_or_tampered_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    MemoryStore(source).initialize()
    backup_store(source, tmp_path / "backup.sqlite")
    with pytest.raises(DoctorError, match="BACKUP_DESTINATION_EXISTS"):
        backup_store(source, tmp_path / "backup.sqlite")
    tampered = tmp_path / "tampered.sqlite"
    tampered.write_bytes((tmp_path / "backup.sqlite").read_bytes())
    tampered_manifest = tmp_path / "tampered.sqlite.manifest.json"
    tampered_manifest.write_text(
        json.dumps(
            {"schema": "simplicio.mapper-store.backup/v1", "backup_path": str(tampered), "sha256": "0" * 64}
        ),
        encoding="utf-8",
    )
    with pytest.raises(DoctorError, match="BACKUP_HASH_MISMATCH"):
        restore_store(tampered, tmp_path / "new.sqlite", manifest=tampered_manifest)


def test_repair_requires_verified_backup_and_rebuilds_only_derived_fts(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite"
    store = MemoryStore(database)
    store.initialize()
    stored = store.store("topic", "authoritative content")
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM semantic_fts")
    backup = backup_store(database, tmp_path / "backup.sqlite")
    repaired = repair_store(database, apply=True, backup_manifest=backup["manifest"])
    assert validate_instance(repaired, _schema("repair.schema.json")) == []
    assert repaired["status"] == "repaired"
    assert MemoryStore(database, auto_create=False).recall("authoritative")["results"]
    assert stored["stable_id"]


def test_repair_quarantines_reference_gap_without_deleting_semantic_data(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite"
    store = MemoryStore(database)
    store.initialize()
    stored = store.store("topic", "keep the semantic authority")
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM memory_entries WHERE stable_id=?", (stored["stable_id"],))
    planned = repair_store(database)
    assert "quarantine_reference_gaps" in planned["actions"]
    backup = backup_store(database, tmp_path / "backup.sqlite")
    result = repair_store(database, apply=True, backup_manifest=backup["manifest"])
    assert result["post_check"]["quarantine"] is True
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mapper_repair_quarantine").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_items WHERE stable_id=?", (stored["stable_id"],)
            ).fetchone()[0]
            == 1
        )


def test_redaction_secure_export_metrics_capacity_and_benchmark(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite"
    MemoryStore(database).initialize()
    collector = Metrics()
    collector.observe("query", 1.0, rows=2, retries=1, lock_wait_ms=0.5, error_code="BUSY")
    collector.observe("query", 3.0, rows=1)
    metrics = metrics_for_store(database, collector)
    assert validate_instance(metrics, _schema("metrics.schema.json")) == []
    assert metrics["operations"]["query"]["p95_ms"] == 3.0
    assert metrics["cache"]["hit_rate"] is None
    capacity = capacity_report(database, max_bytes=1)
    assert "DATABASE_SIZE_BUDGET_EXCEEDED" in capacity["alerts"][0]["code"]
    benchmark = run_benchmark(database, workers=(1,), repetitions=1)
    assert validate_instance(benchmark, _schema("benchmark.schema.json")) == []
    assert benchmark["claim"] == "UNVERIFIED_END_TO_END_PERFORMANCE"
    export = secure_export({"token": "secret-value", "message": "Bearer abc"}, tmp_path / "report.json")
    assert export["permissions"] == "0o600"
    assert "secret-value" not in (tmp_path / "report.json").read_text(encoding="utf-8")
    with pytest.raises(DoctorError, match="EXPORT_DESTINATION_EXISTS"):
        secure_export({"safe": True}, tmp_path / "report.json")


def test_metrics_validation_and_repair_noop(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite"
    MemoryStore(database).initialize()
    assert repair_store(database)["status"] == "no_op"
    collector = Metrics()
    with pytest.raises(ValueError):
        collector.observe("query", -1)
    finish = collector.time("query")
    finish("FAILED")
    assert collector.snapshot()["errors"] == {"FAILED": 1}
    with pytest.raises(ValueError):
        run_benchmark(database, workers=(0,), repetitions=1)


def test_cli_operational_commands_are_wired(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from simplicio_mapper.cli import main

    database = tmp_path / "store.sqlite"
    MemoryStore(database).initialize()
    assert main(["mapper-store", "doctor", "--database", str(database), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == "simplicio.mapper-store.doctor/v1"
