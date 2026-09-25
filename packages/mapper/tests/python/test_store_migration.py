"""Governed legacy migration state machine and CLI contracts (#479)."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from simplicio_mapper.cli import main
from simplicio_mapper.store import MigrationCoordinator, MigrationCoordinatorError


def _legacy(path: Path, rows: list[tuple[int, str]] | None = None) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN")
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany("INSERT INTO records VALUES (?, ?)", rows or [(1, "one"), (2, "two")])
        connection.commit()


def test_dry_run_discovery_and_plan_are_side_effect_free(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(destination, {"dev-cli": source})
    plan = coordinator.plan()
    discovery = coordinator.discover(dry_run=True)
    assert plan["dry_run"] is True
    assert discovery["ok"] is True
    assert not destination.exists()
    assert not coordinator.state_path.exists()
    assert not coordinator.backup_dir.exists()


def test_discover_reports_corruption_and_active_writer(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    _legacy(source)
    lock = source.with_name(source.name + ".writer.lock")
    lock.write_text(json.dumps({"pid": 999999999, "owner": "dead"}), encoding="utf-8")
    report = MigrationCoordinator(tmp_path / "mapper.sqlite", {"legacy": source}).discover()
    assert report["ok"] is True
    assert report["sources"][0]["writers"]["stale"] is True
    lock.write_text(json.dumps({"pid": __import__("os").getpid()}), encoding="utf-8")
    blocked = MigrationCoordinator(tmp_path / "other.sqlite", {"legacy": source}).discover()
    assert any(item["code"] == "WRITER_ACTIVE" for item in blocked["blockers"])


def test_backup_is_verified_and_receipted(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(tmp_path / "mapper.sqlite", {"legacy": source})
    payload = coordinator.backup()
    assert payload["status"] == "backed_up"
    assert len(payload["receipts"]) == 2
    assert coordinator.status()["state"] == "BACKED_UP"
    for receipt in payload["receipts"]:
        if receipt["path"]:
            assert Path(receipt["path"]).is_file()


def test_import_is_idempotent_and_validate_proves_parity(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(destination, {"loop": source})
    coordinator.backup()
    first = coordinator.import_data()
    second = coordinator.import_data()
    assert first["status"] == "imported"
    assert second["status"] == "imported"
    assert coordinator.validate()["ok"] is True
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2


def test_import_requires_backup_and_writer_quiescence(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(tmp_path / "mapper.sqlite", {"legacy": source})
    with pytest.raises(MigrationCoordinatorError, match="BACKUP_REQUIRED"):
        coordinator.import_data()
    coordinator.backup()
    lock = source.with_name(source.name + ".writer.lock")
    lock.write_text(json.dumps({"pid": __import__("os").getpid()}), encoding="utf-8")
    with pytest.raises(MigrationCoordinatorError, match="PREFLIGHT_BLOCKED"):
        coordinator.import_data()


def test_shadow_cutover_and_pointer_have_single_writer_authority(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(destination, {"runtime": source})
    coordinator.backup()
    coordinator.import_data()
    shadow = coordinator.shadow()
    assert shadow["ok"] is True
    cutover = coordinator.cutover()
    pointer = destination.with_name(destination.name + ".active.json")
    assert cutover["writer_authority"] == "mapper-store"
    assert json.loads(pointer.read_text(encoding="utf-8"))["legacy_policy"] == "read-only"
    assert coordinator.status()["state"] == "CUTOVER"


def test_cutover_blocks_shadow_divergence(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(destination, {"runtime": source})
    coordinator.backup()
    coordinator.import_data()
    with closing(sqlite3.connect(destination)) as connection:
        connection.execute("BEGIN")
        connection.execute("UPDATE records SET value='diverged' WHERE id=1")
        connection.commit()
    report = coordinator.validate()
    assert report["ok"] is False
    with pytest.raises(MigrationCoordinatorError, match="SHADOW_DIVERGENCE"):
        coordinator.cutover()


def test_rollback_restores_preexisting_destination_and_removes_pointer(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    with closing(sqlite3.connect(destination)) as connection:
        connection.execute("BEGIN")
        connection.execute("CREATE TABLE old_records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_records VALUES (1, 'old')")
        connection.commit()
    coordinator = MigrationCoordinator(destination, {"legacy": source})
    coordinator.backup()
    coordinator.import_data()
    coordinator.cutover()
    with closing(sqlite3.connect(destination)) as connection:
        connection.execute("BEGIN")
        connection.execute("UPDATE records SET value='changed' WHERE id=1")
        connection.commit()
    result = coordinator.rollback()
    assert result["status"] == "rolled_back"
    assert not destination.with_name(destination.name + ".active.json").exists()
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT value FROM old_records WHERE id=1").fetchone()[0] == "old"
    assert coordinator.status()["state"] == "ROLLBACK"


def test_unknown_post_effect_requires_reconciliation(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(destination, {"legacy": source})
    coordinator.backup()
    coordinator.import_data()
    coordinator._append("cutover_intent", {"pointer": "unknown"}, state="READY")
    with pytest.raises(MigrationCoordinatorError, match="RECONCILIATION_REQUIRED"):
        coordinator.rollback()


def test_receipt_tamper_is_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    _legacy(source)
    coordinator = MigrationCoordinator(tmp_path / "mapper.sqlite", {"legacy": source})
    coordinator.discover()
    lines = coordinator.state_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["state"] = "CUTOVER"
    coordinator.state_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(MigrationCoordinatorError, match="RECEIPT_TAMPERED"):
        coordinator.status()


def test_cli_governed_surface_is_machine_readable_and_legacy_surface_remains(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "legacy.sqlite"
    destination = tmp_path / "mapper.sqlite"
    _legacy(source)
    code = main(
        ["mapper-store", "plan", "--database", str(destination), "--source", f"legacy={source}", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.mapper-store.migration-plan/v1"
    assert not destination.exists()
    legacy_code = main(["store-migrations", "plan", "--database", str(tmp_path / "catalog.sqlite"), "--json"])
    assert legacy_code == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "simplicio.mapper-store.migration-plan/v1"


def test_cli_missing_source_and_unknown_option_are_typed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["mapper-store", "backup", "--database", str(tmp_path / "x.sqlite"), "--json"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "INVALID_ARGUMENT"
    code = main(["mapper-store", "status", "--nope", "--json"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "INVALID_ARGUMENT"
