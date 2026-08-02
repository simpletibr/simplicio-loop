"""MapperStore memory, Markdown compatibility, and handoff contracts (#478)."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from simplicio_mapper.store import (
    MEMORY_HANDOFF_SCHEMA,
    MemoryStore,
    MemoryStoreError,
    build_handoff,
    init_memory,
    recall_memory,
    store_memory,
    transaction,
    validate_memory,
)


def test_markdown_import_is_idempotent_and_preserves_provenance(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    notes = root / "notes"
    notes.mkdir(parents=True)
    (root / "README.md").write_text("# legacy\n", encoding="utf-8")
    path = notes / "auth-flow.md"
    path.write_text(
        "# Auth flow\n\n## 2026-08-02T00:00:00Z — claude-code\n"
        "tags: auth, decision\n\nUse OAuth device flow.\n",
        encoding="utf-8",
    )
    store = MemoryStore(markdown_root=root)
    store.initialize()
    first = store.import_markdown(strict=True)
    second = store.import_markdown(strict=True)
    assert first["imported"] == 1
    assert second["unchanged"] == 1
    result = store.recall("OAuth device flow", mode="fts5")
    assert result["results"][0]["actor"] == "claude-code"
    assert result["results"][0]["source_path"] == "notes/auth-flow.md"
    assert result["results"][0]["tags"] == ["auth", "decision"]


def test_store_reuses_semantic_index_without_copying_embedding(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    store.initialize()
    stored = store.store("release", "Ship via a draft pull request.", tags=["workflow"], actor="codex")
    assert stored["status"] == "inserted"
    with store._open(read_only=True) as connection:
        semantic = connection.execute("SELECT COUNT(*) FROM semantic_items WHERE kind='memory'").fetchone()[0]
        memory_vectors = connection.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE stable_id=? AND content LIKE '%vector_json%'",
            (stored["stable_id"],),
        ).fetchone()[0]
    assert semantic == 1
    assert memory_vectors == 0
    assert store.recall("draft pull request", mode="hybrid")["results"]


def test_recall_modes_are_deterministic_and_honest(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    store.store("release", "Draft pull request before merge.")
    for mode in ("fts5", "vector", "hybrid"):
        result = store.recall("draft pull request", mode=mode)
        assert result["mode"] == mode
        assert result["results"]
        assert result["ann_claimed"] is False


def test_redaction_and_consent_metadata_are_fail_closed(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    result = store.store(
        "credentials",
        "Use token=super-secret only with consent.",
        consent={"purpose": "test", "token": "never-store"},
        metadata={"authorization": "Bearer abc"},
    )
    with store._open(read_only=True) as connection:
        row = connection.execute(
            "SELECT content, consent_json, metadata_json FROM memory_entries WHERE stable_id=?",
            (result["stable_id"],),
        ).fetchone()
    assert "super-secret" not in row[0]
    assert "never-store" not in row[1]
    assert "Bearer abc" not in row[2]


def test_malformed_markdown_is_explicit_and_strict_import_does_not_write(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    (root / "notes").mkdir(parents=True)
    (root / "README.md").write_text("# memory\n", encoding="utf-8")
    (root / "notes" / "broken.md").write_text("# topic\n\n## no actor separator\n\ntext\n", encoding="utf-8")
    store = MemoryStore(markdown_root=root)
    store.initialize()
    with pytest.raises(MemoryStoreError, match="MARKDOWN_INVALID"):
        store.import_markdown(strict=True)
    assert store.validate()["entries"] == 0


def test_export_round_trip_preserves_hashes_and_readable_markdown(tmp_path: Path) -> None:
    source = MemoryStore(tmp_path / "source.sqlite", markdown_root=tmp_path / "source")
    source.store("handoff", "Keep the migration receipt.", tags=["ops"], actor="codex")
    destination = tmp_path / "exported"
    exported = source.export_markdown(destination)
    assert exported["files"]
    restored = MemoryStore(tmp_path / "restored.sqlite", markdown_root=destination)
    restored.initialize()
    imported = restored.import_markdown(strict=True)
    assert imported["imported"] == 1
    assert (
        restored.recall("migration receipt")["results"][0]["content_hash"]
        == source.recall("migration receipt")["results"][0]["content_hash"]
    )


def test_handoff_is_versioned_deterministic_and_validated(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    store.store("decision", "Use the canonical store.", actor="codex")
    first = store.handoff("canonical store", from_agent="codex", to_agent="claude", persist=False)
    second = store.handoff("canonical store", from_agent="codex", to_agent="claude", persist=False)
    assert first == second
    assert first["schema"] == MEMORY_HANDOFF_SCHEMA
    assert store.validate_handoff(first)["ok"] is True
    broken = dict(first)
    broken["query"] = "tampered"
    assert store.validate_handoff(broken)["ok"] is False


def test_outcomes_snapshot_restore_and_hash_tamper_are_safe(tmp_path: Path) -> None:
    source = MemoryStore(tmp_path / "source.sqlite")
    stored = source.store("task", "Completed the migration.")
    source.outcome(stored["stable_id"], "verified", actor="tester")
    snapshot = tmp_path / "snapshot.json"
    source.export_snapshot(snapshot)
    target = MemoryStore(tmp_path / "target.sqlite")
    target.restore_snapshot(snapshot)
    assert target.recall("completed migration")["results"]
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["entries"][0]["content"] = "tampered"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MemoryStoreError, match="SNAPSHOT_HASH_INVALID"):
        target.restore_snapshot(snapshot)


def test_retention_excludes_expired_content_and_tombstones_audit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    stored = store.store("temporary", "Discard after expiry.", retention_until="2000-01-01T00:00:00Z")
    assert store.recall("discard expiry")["results"] == []
    purged = store.purge_expired()
    assert purged["count"] == 1
    with store._open(read_only=True) as connection:
        assert (
            connection.execute(
                "SELECT tombstone FROM memory_entries WHERE stable_id=?", (stored["stable_id"],)
            ).fetchone()[0]
            == 1
        )


def test_validate_detects_broken_semantic_reference(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    stored = store.store("broken", "Reference should exist.")
    with store._open() as connection:
        with transaction(connection, "IMMEDIATE") as tx:
            tx.execute("DELETE FROM semantic_embeddings WHERE stable_id=?", (stored["stable_id"],))
            tx.execute("DELETE FROM semantic_provenance WHERE stable_id=?", (stored["stable_id"],))
            tx.execute("DELETE FROM semantic_revisions WHERE stable_id=?", (stored["stable_id"],))
            tx.execute("DELETE FROM semantic_chunks WHERE stable_id=?", (stored["stable_id"],))
            tx.execute("DELETE FROM semantic_items WHERE stable_id=?", (stored["stable_id"],))
    report = store.validate()
    assert report["ok"] is False
    assert any(error["code"] == "SEMANTIC_REFERENCE_MISSING" for error in report["errors"])


def test_legacy_function_adapter_surface(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    init_memory(root=root)
    stored = store_memory("auth flow", "OAuth device flow.", root=root, actor="claude")
    assert stored["stable_id"].startswith("memory:")
    assert recall_memory("OAuth", root=root)[0]["topic"] == "auth flow"
    assert validate_memory(root=root)["ok"] is True
    assert build_handoff("OAuth", root=root, from_agent="codex", to_agent="claude")["from_agent"] == "codex"


def test_legacy_handoff_schema_is_accepted_with_explicit_version_error_shape(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    result = store.validate_handoff(
        {
            "schema": "simplicio.memory-handoff/v1",
            "query": "x",
            "from_agent": "a",
            "to_agent": "b",
            "results": [],
        }
    )
    assert result["ok"] is True


def test_concurrent_writers_keep_one_canonical_entry(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite"

    def write() -> str:
        return MemoryStore(database).store("same", "same content")["stable_id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _index: write(), range(8)))
    assert len(set(ids)) == 1
    store = MemoryStore(database, auto_create=False)
    with store._open(read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0] == 1


def test_validation_and_input_failures_are_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_MEMORY_DIR", str(tmp_path / "custom"))
    from simplicio_mapper.store import memory_dir as current_memory_dir

    assert os.fspath(current_memory_dir()).endswith("custom")
    store = MemoryStore(tmp_path / "memory.sqlite", max_content_chars=4)
    with pytest.raises(MemoryStoreError, match="CONTENT_EMPTY"):
        store.store("topic", "   ")
    with pytest.raises(MemoryStoreError, match="CONTENT_LIMIT"):
        store.store("topic", "12345")
    with pytest.raises(MemoryStoreError, match="MODE_INVALID"):
        store.recall("x", mode="llm")
    with pytest.raises(MemoryStoreError, match="JSON_INVALID"):
        store.store("topic", "ok", metadata={"value": float("nan")})


def test_invalid_timestamp_is_reported_without_import(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    notes = root / "notes"
    notes.mkdir(parents=True)
    (root / "README.md").write_text("# memory\n", encoding="utf-8")
    (notes / "bad.md").write_text("# bad\n\n## yesterday — agent\n\nvalue\n", encoding="utf-8")
    store = MemoryStore(markdown_root=root)
    store.initialize()
    result = store.import_markdown()
    assert result["entries"] == 0
    assert result["errors"][0]["code"] == "invalid_timestamp"


def test_snapshot_schema_and_outcome_errors_are_fail_closed(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    with pytest.raises(MemoryStoreError, match="ENTRY_NOT_FOUND"):
        store.outcome("missing", "not recorded")
    with pytest.raises(MemoryStoreError, match="SNAPSHOT_INVALID"):
        store.restore_snapshot(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(MemoryStoreError, match="SNAPSHOT_SCHEMA_INVALID"):
        store.restore_snapshot(invalid)


def test_source_drift_is_warning_and_unknown_tombstone_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    store = MemoryStore(tmp_path / "memory.sqlite", markdown_root=root)
    store.store("topic", "original", source="markdown", source_path="notes/topic.md", source_hash="old")
    notes = root / "notes"
    notes.mkdir(exist_ok=True)
    (root / "README.md").write_text("# memory\n", encoding="utf-8")
    (notes / "topic.md").write_text("# topic\n\n## 2026-08-02T00:00:00Z — agent\n\nnew\n", encoding="utf-8")
    report = store.validate()
    assert any(warning["code"] == "SOURCE_CHANGED" for warning in report["warnings"])
    assert store.tombstone("missing")["status"] == "unchanged"
