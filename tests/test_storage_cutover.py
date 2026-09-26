from __future__ import annotations

import json

from simplicio_loop.storage_cutover import inspect_storage_cutover

SQLITE_HEADER = b"SQLite format 3\x00"


def _sqlite_stub(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(SQLITE_HEADER + b"fixture")


def test_empty_root_is_unverified_without_side_effects(tmp_path):
    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "UNVERIFIED"
    assert report["effects_attempted"] is False
    assert report["legacy_stores"] == []
    assert not (tmp_path / ".simplicio-loop").exists()


def test_legacy_store_is_detected_and_marked_read_only(tmp_path):
    path = tmp_path / ".simplicio-loop" / "orchestrator" / "hookwall.sqlite3"
    _sqlite_stub(path)

    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "LEGACY_PRESENT"
    assert report["legacy_read_only"] is True
    assert report["writer_authority"] == "loop-legacy-read-only"
    assert report["cutover_ready"] is False


def test_canonical_store_without_legacy_is_clean(tmp_path):
    _sqlite_stub(tmp_path / ".simplicio-loop" / "data" / "operations.sqlite")

    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "CLEAN"
    assert report["writer_authority"] == "mapper-store"
    assert report["cutover_ready"] is True


def test_canonical_and_legacy_stores_are_split_brain(tmp_path):
    _sqlite_stub(tmp_path / ".simplicio-loop" / "data" / "operations.sqlite")
    _sqlite_stub(tmp_path / ".simplicio-loop" / "orchestrator" / "run-journal.sqlite")

    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "SPLIT_BRAIN"
    assert report["writer_authority"] == "none"
    assert "stop_writers" in report["next_action"]


def test_invalid_legacy_bytes_are_corrupt(tmp_path):
    path = tmp_path / ".simplicio-loop" / "orchestrator" / "queue.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-a-database")

    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "CORRUPT"
    assert report["corrupt_paths"] == [".simplicio-loop/orchestrator/queue.sqlite3"]


def test_migration_marker_blocks_cutover(tmp_path):
    marker = tmp_path / ".simplicio-loop" / "storage-migration.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"status": "migrating", "migration_id": "m-1"}), encoding="utf-8")

    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "MIGRATING"
    assert report["migration_markers"][0]["migration_state"] == "migrating"


def test_route_receipt_conflict_is_split_brain(tmp_path):
    run_a = tmp_path / ".simplicio-loop" / "loop-runs" / "run-a"
    run_b = tmp_path / ".simplicio-loop" / "loop-runs" / "run-b"
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)
    for path, selected in ((run_a / "storage-route-receipt.json", "legacy"),
                           (run_b / "storage-route-receipt.json", "mapper")):
        path.write_text(json.dumps({
            "schema": "simplicio.loop-store-route-receipt/v1",
            "selected": selected,
            "generation": path.parent.name,
            "receipt_hash": "sha256:fixture",
        }), encoding="utf-8")

    report = inspect_storage_cutover(tmp_path)

    assert report["status"] == "SPLIT_BRAIN"
