"""Executable zero-mismatch corpus for issue #497 memory migration."""

from __future__ import annotations

import json
from pathlib import Path

from simplicio.memory_store import (
    _split_sections,
    build_handoff,
    import_memory,
    recall_memory,
    validate_handoff,
    validate_memory,
)
from simplicio.store_adapter import MapperStoreAdapter, storage_capabilities


def _write_corpus(source: Path) -> None:
    notes = source / "notes"
    notes.mkdir(parents=True)
    (notes / "release.md").write_text(
        """# Release 🚀

## 2026-07-31T12:00:00Z — codex
tags: release, unicode

Ship the draft PR with rollback receipt and provenance.

## 2026-08-01T12:00:00Z — claude
tags: handoff, 🔒

Mapper handoff preserves actor, timestamp, and tags.
""",
        encoding="utf-8",
    )
    (notes / "security.md").write_text(
        """# Security

## 2026-08-02T12:00:00Z — cursor
tags: pii, fail-closed

Reject malformed handoff payloads without mutation.
""",
        encoding="utf-8",
    )


def _sections(notes: Path) -> list[str]:
    return [
        section.strip()
        for path in sorted(notes.glob("*.md"))
        for section in _split_sections(path.read_text(encoding="utf-8"))
        if section.strip().startswith("## ")
    ]


def test_issue_497_memory_zero_mismatch_corpus(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _write_corpus(source)

    first = import_memory(source, root=target)
    second = import_memory(source, root=target)
    assert first["status"] == "ok"
    assert first["imported_files"] == 2
    assert second["status"] == "ok"
    assert second["imported_files"] == 0
    assert second["merged_entries"] == 0

    source_notes = source / "notes"
    target_notes = target / "notes"
    assert [path.name for path in sorted(source_notes.glob("*.md"))] == [
        path.name for path in sorted(target_notes.glob("*.md"))
    ]
    for source_path in sorted(source_notes.glob("*.md")):
        assert (target_notes / source_path.name).read_bytes() == source_path.read_bytes()

    source_sections = _sections(source_notes)
    target_sections = _sections(target_notes)
    assert source_sections == target_sections

    validation = validate_memory(root=target)
    assert validation["ok"] is True
    assert validation["entries"] == len(source_sections)

    index = MapperStoreAdapter(target, "memory-index").read("index") or {}
    assert index["entry_count"] == len(source_sections)
    assert {row["snippet"] for row in index["entries"]} == {section[:800] for section in source_sections}

    for mode in ("fts5", "vector", "hybrid"):
        results = recall_memory("rollback receipt", root=target, mode=mode)
        assert results
        result = results[0]
        assert result["requested_mode"] == mode
        assert isinstance(result["components"]["lexical"], (int, float))
        assert isinstance(result["components"]["vector"], (int, float))
        assert "rollback receipt" in result["snippet"].lower()

    handoff = build_handoff("Mapper handoff", root=target, from_agent="codex", to_agent="claude")
    assert validate_handoff(handoff)["ok"] is True
    assert any(
        item["actor"] == "claude" and item["tags"] == "handoff, 🔒" and item["ts"] == "2026-08-01T12:00:00Z"
        for item in handoff["results"]
    )

    malformed = json.loads(json.dumps(handoff))
    malformed["results"][0]["score"] = "not-a-score"
    malformed_validation = validate_handoff(malformed)
    assert malformed_validation["ok"] is False
    assert any(error["code"] == "invalid_result_score" for error in malformed_validation["errors"])

    capabilities = storage_capabilities(target)
    assert capabilities["route"]["selected"] == "mapper-store"
    assert capabilities["route"]["frozen_before_effect"] is True
    assert capabilities["mapper_store"]["ready"] is True
    assert not (target / "index.sqlite3").exists()
    assert not (target / "memory" / "index.sqlite3").exists()
