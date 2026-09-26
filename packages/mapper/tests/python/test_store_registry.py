"""State-machine and contract tests for MapperStore registry migrations (#475)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from simplicio_mapper.cli import main
from simplicio_mapper.store import (
    DEFAULT_MANIFEST,
    AmbiguousMigrationError,
    IncompatibleWriterError,
    MigrationEngine,
    MigrationPreflightError,
    MigrationSpec,
    RegistryChecksumError,
    RegistryError,
    StoreFileLock,
    canonical_json,
    default_migrations,
    negotiate,
    registry_fixture,
    sha256_json,
)
from simplicio_mapper.store.connection import StoreConnection
from simplicio_mapper.store.profiles import StoreProfile


def test_manifest_is_canonical_and_json_contract_is_valid() -> None:
    from simplicio_mapper.contract import validate_instance

    schema = json.loads(
        (
            Path(__file__).parents[2] / "simplicio_mapper/contracts/mapper-store/v1/schemas/schema-registry.schema.json"
        ).read_text()
    )
    assert validate_instance(DEFAULT_MANIFEST, schema) == []
    assert sha256_json(DEFAULT_MANIFEST) == registry_fixture()["manifest_sha256"]
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_golden_migration_and_negotiation_fixtures_validate() -> None:
    from simplicio_mapper.contract import validate_instance

    root = Path(__file__).parents[2] / "simplicio_mapper/contracts/mapper-store/v1"
    migration_schema = json.loads((root / "schemas/migration.schema.json").read_text())
    migrations = json.loads((root / "fixtures/migrations/catalog.json").read_text())
    assert [item.as_dict() for item in MigrationEngine(":memory:").migrations] == migrations
    assert all(not validate_instance(item, migration_schema) for item in migrations)
    negotiation_schema = json.loads((root / "schemas/negotiation.schema.json").read_text())
    compatible = json.loads((root / "fixtures/negotiation/compatible.json").read_text())
    incompatible = json.loads((root / "fixtures/negotiation/incompatible-writer.json").read_text())
    assert negotiate(reader_min=1, reader_max=1, writer_min=1, writer_max=1, strict=False) == compatible
    assert negotiate(reader_min=1, reader_max=1, writer_min=2, writer_max=2, strict=False) == incompatible
    assert not validate_instance(compatible, negotiation_schema)
    assert not validate_instance(incompatible, negotiation_schema)


def test_json_api_response_schemas_validate(tmp_path: Path) -> None:
    from simplicio_mapper.contract import validate_instance

    root = Path(__file__).parents[2] / "simplicio_mapper/contracts/mapper-store/v1"
    engine = MigrationEngine(tmp_path / "catalog.sqlite")
    payloads = {
        "migration-plan.schema.json": engine.plan(),
        "migration-status.schema.json": engine.status(),
        "migration-verify.schema.json": engine.verify(),
    }
    for schema_name, payload in payloads.items():
        assert validate_instance(payload, json.loads((root / "schemas" / schema_name).read_text())) == []


def test_migration_descriptor_rejects_missing_invalid_and_tampered_values() -> None:
    with pytest.raises(ValueError, match="missing fields"):
        MigrationSpec.from_dict({"id": "x"})
    base = {
        "id": "x",
        "from_version": 1,
        "to_version": 1,
        "forward": ["SELECT 1"],
        "verification_query": "SELECT 1",
        "checksum": "",
    }
    with pytest.raises(ValueError, match="missing fields"):
        MigrationSpec.from_dict({key: value for key, value in base.items() if key != "checksum"})
    with pytest.raises(ValueError, match="versions must increase"):
        MigrationSpec.from_dict(base)
    base["to_version"] = 2
    base["checksum"] = "0" * 64
    with pytest.raises(RegistryChecksumError, match="checksum"):
        MigrationSpec.from_dict(base)


def test_engine_rejects_bad_manifest_and_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        MigrationEngine("catalog.sqlite", manifest={"schema": "wrong"})
    bad_manifest = dict(DEFAULT_MANIFEST)
    bad_manifest["namespaces"] = {"catalog": {"current": 1}}
    with pytest.raises(ValueError, match="namespaces"):
        MigrationEngine("catalog.sqlite", manifest=bad_manifest)
    migration = MigrationSpec("same", 0, 1, ("SELECT 1",), "SELECT 1")
    with pytest.raises(ValueError, match="unique"):
        MigrationEngine("catalog.sqlite", migrations=(migration, migration))


def test_default_migrations_have_a_local_fallback() -> None:
    with patch("simplicio_mapper.store.registry._fixture_path", return_value=None):
        assert len(default_migrations()) == 2
        assert registry_fixture()["manifest_sha256"] == sha256_json(DEFAULT_MANIFEST)


def test_fresh_apply_is_idempotent_and_ledger_is_reconstructable(tmp_path: Path) -> None:
    engine = MigrationEngine(tmp_path / "catalog.sqlite")
    assert engine.plan()["current_version"] == 0
    result = engine.apply()
    assert result["current_version"] == 2
    assert result["applied"] == ["catalog-0001-base-ledger", "catalog-0002-memory-records"]
    assert engine.apply()["applied"] == []
    status = engine.status()
    assert status["ledger_events"] == 6
    assert [event["event"] for event in status["latest"].values()] == ["receipt", "receipt"]
    assert engine.verify()["valid"] is True


def test_destructive_step_writes_verified_backup_before_ddl(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database, backup_dir=tmp_path / "backups")
    engine.apply(target_version=1)
    engine.apply()
    backups = list((tmp_path / "backups").glob("*.sqlite"))
    assert len(backups) == 1
    assert backups[0].stat().st_size > 0
    intent = [
        event
        for event in engine.status()["latest"].values()
        if event["migration_id"] == "catalog-0002-memory-records"
    ][0]
    assert intent["event"] == "receipt"
    assert intent["payload"]["backup"]["sha256"]
    assert (tmp_path / "backups").stat().st_mode & 0o777 == 0o700
    assert backups[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("stage", ["after_intent", "after_ddl", "after_receipt"])
def test_fault_boundaries_resume_without_reapplying_confirmed_step(tmp_path: Path, stage: str) -> None:
    fired = False

    def fault(name, _spec):
        nonlocal fired
        if name == stage and not fired:
            fired = True
            raise RuntimeError(name)

    engine = MigrationEngine(tmp_path / "catalog.sqlite", fault_hook=fault)
    with pytest.raises(RuntimeError):
        engine.apply()
    resumed = MigrationEngine(engine.database).apply()
    assert resumed["current_version"] == 2
    assert MigrationEngine(engine.database).verify()["valid"] is True


def test_final_ddl_receipt_is_recovered_after_crash(tmp_path: Path) -> None:
    def fault(name, spec):
        if name == "after_ddl" and spec.migration_id == "catalog-0002-memory-records":
            raise RuntimeError(name)

    database = tmp_path / "catalog.sqlite"
    with pytest.raises(RuntimeError):
        MigrationEngine(database, fault_hook=fault).apply()
    resumed = MigrationEngine(database).apply()
    assert resumed["current_version"] == 2
    assert resumed["latest"]["catalog-0002-memory-records"]["event"] == "receipt"


def test_deleted_final_receipt_is_not_recreated(tmp_path: Path) -> None:
    database = tmp_path / "deleted-receipt.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER migration_ledger_no_update")
        connection.execute("DROP TRIGGER migration_ledger_no_delete")
        connection.execute(
            "DELETE FROM migration_ledger WHERE migration_id = 'catalog-0002-memory-records' AND event = 'receipt'"
        )
        connection.execute(
            "CREATE TRIGGER migration_ledger_no_update BEFORE UPDATE ON migration_ledger BEGIN SELECT RAISE(ABORT, 'migration ledger is append-only'); END"
        )
        connection.execute(
            "CREATE TRIGGER migration_ledger_no_delete BEFORE DELETE ON migration_ledger BEGIN SELECT RAISE(ABORT, 'migration ledger is append-only'); END"
        )
    assert MigrationEngine(database).verify()["valid"] is False
    with pytest.raises(AmbiguousMigrationError):
        MigrationEngine(database).apply()


def test_checksum_tamper_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database)
    engine.apply(target_version=1)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER migration_ledger_no_update")
        connection.execute("DROP TRIGGER migration_ledger_no_delete")
        connection.execute(
            "UPDATE migration_ledger SET checksum = '0' WHERE migration_id = 'catalog-0001-base-ledger'"
        )
    assert engine.verify()["valid"] is False
    with pytest.raises(RegistryChecksumError):
        engine.apply()


def test_registry_version_and_required_triggers_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "registry-shape.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE mapper_schema_registry SET registry_version = 999")
    assert MigrationEngine(database).verify()["valid"] is False

    database = tmp_path / "missing-triggers.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER migration_ledger_no_update")
        connection.execute("DROP TRIGGER migration_ledger_no_delete")
    assert MigrationEngine(database).verify()["valid"] is False

    database = tmp_path / "tampered-trigger.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER migration_ledger_no_update")
        connection.execute(
            "CREATE TRIGGER migration_ledger_no_update BEFORE UPDATE ON migration_ledger BEGIN SELECT 1; END"
        )
    assert MigrationEngine(database).verify()["valid"] is False


def test_manifest_tamper_and_future_version_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database)
    engine.apply(target_version=1)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE mapper_schema_registry SET manifest_hash = '0'")
    with pytest.raises(RegistryChecksumError):
        engine.apply()
    future = tmp_path / "future.sqlite"
    with sqlite3.connect(future) as connection:
        connection.execute("PRAGMA user_version = 9")
    with pytest.raises(Exception, match="newer than target"):
        MigrationEngine(future).apply()


def test_ambiguous_ddl_state_is_not_guessed(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database)
    engine.apply(target_version=1)
    spec = engine.migrations[1]
    engine._append_event(spec, "ddl", {})
    with pytest.raises(AmbiguousMigrationError):
        engine.apply()


def test_preflight_reports_missing_capability_and_disk_contract(tmp_path: Path) -> None:
    engine = MigrationEngine(tmp_path / "catalog.sqlite", min_free_bytes=10**30)
    with pytest.raises(MigrationPreflightError):
        engine.preflight()
    with pytest.raises(MigrationPreflightError):
        MigrationEngine(tmp_path / "other.sqlite").preflight(required_capabilities={"sqlite-vec"})


def test_lock_is_exclusive(tmp_path: Path) -> None:
    engine = MigrationEngine(tmp_path / "catalog.sqlite")
    with StoreFileLock(engine.lock_path, owner="test"):
        with pytest.raises(MigrationPreflightError):
            engine.apply()


def test_ledger_rejects_mutation_and_apply_rejects_missing_receipts(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE migration_ledger SET actor = 'tamper'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM migration_ledger")
        connection.execute("DROP TRIGGER migration_ledger_no_update")
        connection.execute("DROP TRIGGER migration_ledger_no_delete")
        connection.execute("UPDATE migration_ledger SET actor = 'tamper'")
    assert engine.verify()["valid"] is False
    with pytest.raises(RegistryChecksumError):
        engine.apply()
    empty = tmp_path / "empty-version.sqlite"
    with sqlite3.connect(empty) as connection:
        connection.execute("PRAGMA user_version = 2")
    with pytest.raises(Exception, match="receipt missing|CHECKSUM_DIVERGENCE"):
        MigrationEngine(empty).apply()
    removed = tmp_path / "removed.sqlite"
    MigrationEngine(removed).apply()
    with sqlite3.connect(removed) as connection:
        connection.execute("DROP TABLE memory_records")
    with pytest.raises(Exception, match="verification failed"):
        MigrationEngine(removed).apply()
    ahead = tmp_path / "ahead-receipt.sqlite"
    ahead_engine = MigrationEngine(ahead)
    ahead_engine.apply(target_version=1)
    with sqlite3.connect(ahead) as connection:
        connection.execute("PRAGMA user_version = 0")
    with pytest.raises(Exception, match="objects exist"):
        ahead_engine.apply()
    manual = tmp_path / "manual-version-zero.sqlite"
    with sqlite3.connect(manual) as connection:
        connection.execute("CREATE TABLE memory_records (id TEXT PRIMARY KEY)")
    with pytest.raises(Exception, match="objects exist"):
        MigrationEngine(manual).apply()


def test_missing_status_and_raw_ledger_without_table_are_safe(tmp_path: Path) -> None:
    engine = MigrationEngine(tmp_path / "missing.sqlite")
    assert engine.status()["current_version"] == 0
    engine._validate_ledger()
    database = tmp_path / "empty.sqlite"
    sqlite3.connect(database).close()
    with StoreConnection.open(database, StoreProfile.read_only(), immutable=False) as store:
        assert engine._events(store) == []


def test_corrupt_version_and_malformed_lock_are_reported(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(Exception, match="cannot read schema version"):
        MigrationEngine(corrupt).current_version()
    malformed = MigrationEngine(tmp_path / "malformed.sqlite")
    malformed.lock_path.write_text("not-json\n", encoding="utf-8")
    assert malformed.status()["lock"]["stale"] is True


def test_no_migration_from_current_and_failed_verification_are_explicit(tmp_path: Path) -> None:
    database = tmp_path / "version-three.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 3")
    with pytest.raises(Exception, match="receipt missing|CHECKSUM_DIVERGENCE|INCOMPATIBLE_WRITER"):
        MigrationEngine(database).apply(target_version=4)
    bad = MigrationSpec(
        "fails-verification", 0, 1, ("CREATE TABLE failed_verification (id INTEGER)",), "SELECT 0"
    )
    with pytest.raises(AmbiguousMigrationError):
        MigrationEngine(tmp_path / "bad-verification.sqlite", migrations=(bad,)).apply()


def test_stale_lock_is_reported_and_prerequisites_are_enforced(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database)
    engine.lock_path.write_text('{"owner":"dead","pid":99999999}\n', encoding="utf-8")
    assert engine.status()["lock"]["stale"] is True
    prerequisite = MigrationSpec(
        "needs-prerequisite",
        1,
        2,
        ("CREATE TABLE prerequisite_target (id INTEGER)",),
        "SELECT COUNT(*) FROM sqlite_master WHERE name='prerequisite_target'",
        prerequisites=("missing-migration",),
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(Exception, match="prerequisites|receipt missing|CHECKSUM_DIVERGENCE"):
        MigrationEngine(database, migrations=(prerequisite,)).apply()


def test_rollback_intent_recovers_before_reapply(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    spec = engine.migrations[1]
    engine._append_event(spec, "rollback_intent", {"result": "prepared", "backup": None})
    assert MigrationEngine(database).apply()["current_version"] == 2
    mismatch = tmp_path / "mismatch.sqlite"
    mismatch_engine = MigrationEngine(mismatch)
    mismatch_engine.apply(target_version=1)
    mismatch_engine._append_event(mismatch_engine.migrations[1], "rollback_intent", {})
    with pytest.raises(AmbiguousMigrationError):
        mismatch_engine.apply()


def test_rollback_crash_after_ddl_is_recovered_and_backed_up(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    engine = MigrationEngine(database, backup_dir=tmp_path / "backups")
    engine.apply()
    spec = engine.migrations[1]
    engine._append_event(spec, "rollback_intent", {"result": "prepared", "backup": None})
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE memory_records")
        connection.execute("PRAGMA user_version = 1")
    resumed = MigrationEngine(database).apply()
    assert resumed["current_version"] == 2
    assert resumed["latest"][spec.migration_id]["event"] == "receipt"


def test_negotiated_reader_cannot_write_newer_target(tmp_path: Path) -> None:
    with pytest.raises(IncompatibleWriterError, match="INCOMPATIBLE_WRITER"):
        MigrationEngine(tmp_path / "old-reader.sqlite").apply(
            reader_min=1, reader_max=1, writer_min=1, writer_max=1
        )
    multi_step = MigrationSpec("multi", 0, 2, ("CREATE TABLE multi (id INTEGER)",), "SELECT 1")
    with pytest.raises(IncompatibleWriterError, match="INCOMPATIBLE_WRITER"):
        MigrationEngine(tmp_path / "multi.sqlite", migrations=(multi_step,)).apply(
            reader_min=1, reader_max=1, writer_min=1, writer_max=1
        )


def test_verify_reports_invalid_query_and_rollback_boundaries(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    bad = MigrationSpec("bad", 0, 1, ("CREATE TABLE marker (id INTEGER)",), "SELECT missing FROM nowhere")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")
    report = MigrationEngine(database, migrations=(bad,)).verify()
    assert report["valid"] is False
    with pytest.raises(Exception, match="no migration"):
        MigrationEngine(tmp_path / "fresh.sqlite").rollback()
    no_rollback = MigrationSpec("no-rollback", 0, 1, ("CREATE TABLE no_rollback (id INTEGER)",), "SELECT 1")
    no_rollback_engine = MigrationEngine(tmp_path / "no-rollback.sqlite", migrations=(no_rollback,))
    no_rollback_engine.apply()
    no_rollback_engine.migrations = (
        MigrationSpec("no-rollback", 0, 1, ("CREATE TABLE no_rollback (id INTEGER)",), "SELECT 1"),
    )
    with pytest.raises(Exception, match="not supported"):
        no_rollback_engine.rollback()


def test_negotiation_accepts_overlap_and_rejects_new_writer() -> None:
    result = negotiate(
        reader_min=1,
        reader_max=2,
        writer_min=2,
        writer_max=3,
        reader_capabilities={"sqlite", "wal"},
        writer_capabilities={"sqlite"},
    )
    assert result["compatible"] is True
    with pytest.raises(IncompatibleWriterError):
        MigrationEngine("incompatible.sqlite").apply(reader_max=1, writer_min=2, writer_max=2)
    with pytest.raises(IncompatibleWriterError, match="INCOMPATIBLE_WRITER"):
        negotiate(reader_min=1, reader_max=1, writer_min=2, writer_max=2)
    with pytest.raises(IncompatibleWriterError, match="INCOMPATIBLE_WRITER"):
        negotiate(
            reader_min=1,
            reader_max=2,
            writer_min=1,
            writer_max=2,
            reader_capabilities={"sqlite"},
            writer_capabilities={"sqlite", "wal"},
        )


def test_migration_rejects_symlink_database_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.sqlite"
    link = tmp_path / "link.sqlite"
    link.symlink_to(outside)
    with pytest.raises(Exception, match="symlink"):
        MigrationEngine(link).apply()
    with pytest.raises(MigrationPreflightError, match="symlink"):
        MigrationEngine(link).preflight()


def test_malformed_registry_and_ledger_fail_closed(tmp_path: Path) -> None:
    missing_registry = tmp_path / "missing-registry.sqlite"
    engine = MigrationEngine(missing_registry)
    engine.apply(target_version=1)
    with sqlite3.connect(missing_registry) as connection:
        connection.execute("DROP TABLE mapper_schema_registry")
    with pytest.raises(RegistryChecksumError):
        MigrationEngine(missing_registry).apply()

    malformed_ledger = tmp_path / "malformed-ledger.sqlite"
    MigrationEngine(malformed_ledger).apply(target_version=1)
    with sqlite3.connect(malformed_ledger) as connection:
        connection.execute("DROP TRIGGER migration_ledger_no_update")
        connection.execute("DROP TRIGGER migration_ledger_no_delete")
        connection.execute("UPDATE migration_ledger SET payload = '{'")
    report = MigrationEngine(malformed_ledger).verify()
    assert report["valid"] is False
    assert report["ledger_error"] == "CHECKSUM_DIVERGENCE"


def test_registry_shape_and_backup_destination_are_fail_closed(tmp_path: Path) -> None:
    partial = tmp_path / "partial.sqlite"
    with sqlite3.connect(partial) as connection:
        connection.execute("CREATE TABLE mapper_schema_registry (id INTEGER)")
    assert MigrationEngine(partial).verify()["valid"] is False

    missing_manifest = tmp_path / "missing-manifest.sqlite"
    with sqlite3.connect(missing_manifest) as connection:
        connection.execute(
            "CREATE TABLE mapper_schema_registry (id INTEGER PRIMARY KEY, manifest_hash TEXT NOT NULL, registry_version INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE migration_ledger (seq INTEGER PRIMARY KEY, event_schema TEXT NOT NULL, migration_id TEXT NOT NULL, checksum TEXT NOT NULL, event TEXT NOT NULL, from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)"
        )
    assert MigrationEngine(missing_manifest).verify()["valid"] is False

    malformed = tmp_path / "malformed-columns.sqlite"
    with sqlite3.connect(malformed) as connection:
        connection.execute("CREATE TABLE migration_ledger (seq INTEGER PRIMARY KEY)")
    engine = MigrationEngine(malformed)
    assert engine.verify()["valid"] is False
    with StoreConnection.open(malformed, StoreProfile.read_only(), immutable=False) as store:
        with pytest.raises(RegistryChecksumError):
            engine._events(store)

    database = tmp_path / "backup-destination.sqlite"
    backup_dir = tmp_path / "backups"
    engine = MigrationEngine(database, backup_dir=backup_dir)
    engine.apply(target_version=1)
    fixed = type("UUID", (), {"hex": "fixed"})()
    destination = backup_dir / "backup-destination.sqlite.1-2.fixed.sqlite"
    destination.parent.mkdir(mode=0o700)
    destination.symlink_to(tmp_path / "outside.sqlite")
    with patch("simplicio_mapper.store.registry.uuid4", return_value=fixed):
        with pytest.raises(RegistryError, match="already exists"):
            engine._backup(engine.migrations[1])

    mismatch = tmp_path / "manifest-mismatch.sqlite"
    base = MigrationEngine(mismatch)
    base.apply(target_version=1)
    altered = dict(DEFAULT_MANIFEST)
    altered["manifest_id"] = "other"
    with pytest.raises(RegistryChecksumError):
        with MigrationEngine(mismatch, manifest=altered)._open() as store:
            MigrationEngine(mismatch, manifest=altered)._ensure_metadata(store)


def test_ambiguous_rollback_and_receipt_ahead_states_are_not_guessed(tmp_path: Path) -> None:
    database = tmp_path / "ambiguous-rollback.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    spec = engine.migrations[1]
    engine._append_event(spec, "rollback_intent", {"result": "prepared", "backup": None})
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(AmbiguousMigrationError):
        MigrationEngine(database).apply()

    neither = tmp_path / "ambiguous-neither.sqlite"
    engine = MigrationEngine(neither)
    engine.apply(target_version=1)
    engine._append_event(engine.migrations[1], "rollback_intent", {})
    with sqlite3.connect(neither) as connection:
        connection.execute("PRAGMA user_version = 0")
    with pytest.raises(AmbiguousMigrationError):
        MigrationEngine(neither).apply()

    ahead = tmp_path / "receipt-ahead.sqlite"
    engine = MigrationEngine(ahead)
    engine.apply(target_version=1)
    engine._append_event(engine.migrations[1], "receipt", {"result": "verified", "verified": True})
    with pytest.raises(RegistryError, match="receipt is ahead"):
        MigrationEngine(ahead).apply(target_version=2)


def test_missing_prerequisite_is_explicit(tmp_path: Path) -> None:
    migration = MigrationSpec(
        "needs-prerequisite",
        0,
        1,
        ("CREATE TABLE prerequisite_target (id INTEGER)",),
        "SELECT COUNT(*) FROM sqlite_master WHERE name='prerequisite_target'",
        prerequisites=("missing-migration",),
    )
    with pytest.raises(RegistryError, match="prerequisites"):
        MigrationEngine(tmp_path / "prerequisite.sqlite", migrations=(migration,)).apply()


def test_engine_with_no_migrations_reports_missing_transition(tmp_path: Path) -> None:
    database = tmp_path / "no-transition.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(RegistryError, match="no migration from schema version 1"):
        MigrationEngine(database, migrations=()).apply(target_version=2)


def test_unknown_ledger_migration_is_invalid(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite"
    MigrationEngine(database).apply()
    custom = MigrationSpec("other", 0, 1, ("SELECT 1",), "SELECT 1", checksum="")
    assert MigrationEngine(database, migrations=(custom,)).verify()["valid"] is False


def test_rollback_is_explicit_and_cli_json_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "catalog.sqlite"
    assert main(["store-migrations", "apply", "--database", str(database), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["current_version"] == 2
    assert main(["store-migrations", "rollback", "--database", str(database), "--json"]) == 0
    rollback = json.loads(capsys.readouterr().out)
    assert rollback["current_version"] == 1
    assert rollback["latest"]["catalog-0002-memory-records"]["payload"]["backup"]["sha256"]
    assert main(["store-migrations", "apply", "--database", str(database), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["current_version"] == 2
    assert main(["store-migrations", "negotiate", "--reader-max", "1", "--writer-min", "2", "--json"]) == 0
    incompatible = json.loads(capsys.readouterr().out)
    assert incompatible["compatible"] is False
    assert incompatible["reason_code"] == "INCOMPATIBLE_WRITER"
    assert (
        main(
            [
                "store-migrations",
                "rollback",
                "--database",
                str(database),
                "--reader-max",
                "1",
                "--writer-min",
                "2",
                "--json",
            ]
        )
        == 1
    )
    incompatible_error = json.loads(capsys.readouterr().out)
    assert incompatible_error["error_type"] == "IncompatibleWriterError"
    assert incompatible_error["reason_code"] == "INCOMPATIBLE_WRITER"
    assert main(["store-migrations", "negotiate", "--writer-min", "bad", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "INVALID_ARGUMENT"
    assert main(["store-migrations", "plan", "--target", "-1", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "INVALID_ARGUMENT"
    assert main(["store-migrations", "status", "--unknown", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "INVALID_ARGUMENT"
    assert main(["store-migrations", "plan", "--target", "bad", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "INVALID_ARGUMENT"


def test_rollback_destination_and_sqlite_errors_have_reason_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "rollback-range.sqlite"
    engine = MigrationEngine(database)
    engine.apply()
    with pytest.raises(IncompatibleWriterError, match="INCOMPATIBLE_WRITER"):
        engine.rollback(reader_min=2, reader_max=2, writer_min=2, writer_max=2)

    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not sqlite")
    assert main(["store-migrations", "status", "--database", str(corrupt), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "REGISTRY_ERROR"


def test_restore_backup_rollback_uses_verified_forward_backup(tmp_path: Path) -> None:
    migration = MigrationSpec(
        "restore-backup",
        0,
        1,
        ("CREATE TABLE restore_target (id INTEGER)",),
        "SELECT COUNT(*) FROM sqlite_master WHERE name='restore_target'",
        rollback_class="restore-backup",
        destructive=True,
    )
    engine = MigrationEngine(tmp_path / "restore.sqlite", migrations=(migration,))
    engine.apply()
    result = engine.rollback(reader_min=0, reader_max=2, writer_min=0, writer_max=2)
    assert result["current_version"] == 0
