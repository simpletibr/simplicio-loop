"""Cross-vendor memory handoff — markdown + git under a configurable memory
dir (issue #89 P0)."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from simplicio import memory_store
from simplicio.store_adapter import StoreAdapterError


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MEMORY_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield


def test_memory_dir_defaults_under_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    assert memory_store.memory_dir() == home / ".simplicio" / "memory"


def test_memory_dir_honors_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-memory"
    monkeypatch.setenv("SIMPLICIO_MEMORY_DIR", str(override))
    assert memory_store.memory_dir() == override


def test_init_memory_creates_store(tmp_path):
    base = tmp_path / "mem"
    payload = memory_store.init_memory(root=base)
    assert payload["schema"] == memory_store.MEMORY_SCHEMA
    assert payload["created"] is True
    assert (base / "README.md").exists()
    assert (base / "notes").is_dir()


def test_init_memory_idempotent(tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    second = memory_store.init_memory(root=base)
    assert second["created"] is False


def test_store_then_recall_roundtrip(tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    memory_store.store_memory(
        "auth flow",
        "Decided to use OAuth device flow for CLI login.",
        tags=["auth", "decision"],
        root=base,
        actor="claude-code",
    )
    results = memory_store.recall_memory("oauth device flow", root=base)
    assert results
    assert results[0]["topic"] == "auth-flow"
    assert "OAuth device flow" in results[0]["snippet"]
    assert results[0]["mode"] == "hybrid"
    assert memory_store._index_path(base).exists()
    assert not (base / "index.sqlite3").exists()


def test_recall_supports_fts5_and_vector_modes(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory("release process", "Ship via a draft pull request.", root=base)
    for mode in ("fts5", "vector", "hybrid"):
        results = memory_store.recall_memory("draft pull request", root=base, mode=mode)
        assert results
        assert results[0]["requested_mode"] == mode
        assert results[0]["components"]
        assert results[0]["mode"] != "ann"


def test_recall_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        memory_store.recall_memory("anything", root=tmp_path / "mem", mode="llm")


def test_recall_no_match_returns_empty(tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    memory_store.store_memory("auth flow", "OAuth device flow.", root=base)
    assert memory_store.recall_memory("completely unrelated topic zzz", root=base) == []


def test_recall_on_uninitialized_store_returns_empty(tmp_path):
    assert memory_store.recall_memory("anything", root=tmp_path / "nope") == []


def test_recall_is_read_only_for_markdown_without_derived_index(tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    (base / "notes" / "topic.md").write_text(
        "# topic\n\n## 2026-01-01T00:00:00Z — test\n\nmapper handoff\n",
        encoding="utf-8",
    )
    assert memory_store.recall_memory("mapper handoff", root=base)
    assert not memory_store._index_path(base).exists()


def test_concurrent_memory_store_preserves_all_topics(tmp_path):
    base = tmp_path / "mem"

    def store(index: int):
        return memory_store.store_memory(f"topic-{index}", f"entry {index}", root=base)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store, range(12)))
    assert len(list((base / "notes").glob("*.md"))) == 12
    assert memory_store.validate_memory(root=base)["ok"] is True


def test_store_appends_without_overwriting_history(tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    memory_store.store_memory("topic", "first entry", root=base)
    memory_store.store_memory("topic", "second entry", root=base)
    path = base / "notes" / "topic.md"
    text = path.read_text(encoding="utf-8")
    assert "first entry" in text
    assert "second entry" in text


def test_store_topic_slugified():
    assert memory_store._slugify("Auth Flow!!") == "auth-flow"
    assert memory_store._slugify("   ") == "untitled"


def test_git_audit_failures_are_best_effort(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_store.shutil, "which", lambda _name: None)
    assert memory_store._git(tmp_path, "status") is False

    monkeypatch.setattr(memory_store.shutil, "which", lambda _name: "/usr/bin/git")

    def raise_os_error(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(memory_store.subprocess, "run", raise_os_error)
    assert memory_store._git(tmp_path, "status") is False


def test_rebuild_index_without_notes_is_a_noop(tmp_path):
    memory_store._rebuild_index(tmp_path / "missing")


def test_indexed_recall_skips_malformed_rows(tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    index_path = memory_store._index_path(base)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "schema": memory_store.MEMORY_INDEX_SCHEMA,
                "entries": [
                    None,
                    {"path": "bad-vector.md", "snippet": "query", "tokens": ["query"], "vector": ["bad"]},
                    {"path": 42, "snippet": "query", "tokens": ["query"], "vector": [0.0]},
                    {"path": "ok.md", "snippet": "query", "tokens": ["query"], "vector": [1.0]},
                ],
            }
        ),
        encoding="utf-8",
    )

    results = memory_store.recall_memory("query", root=base)

    assert [row["path"] for row in results] == ["ok.md"]


def test_indexed_recall_returns_empty_on_adapter_error(monkeypatch, tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    memory_store._index_path(base).write_text("{}", encoding="utf-8")

    def fail_read(*_args, **_kwargs):
        raise StoreAdapterError("adapter unavailable")

    monkeypatch.setattr(memory_store.MapperStoreAdapter, "read", fail_read)
    assert memory_store.recall_memory("query", root=base) == []


def test_recall_ignores_empty_query_and_unreadable_notes(monkeypatch, tmp_path):
    base = tmp_path / "mem"
    memory_store.init_memory(root=base)
    note = base / "notes" / "broken.md"
    note.write_text("# broken\n\n## entry — actor\n\nquery\n", encoding="utf-8")
    original_read_text = memory_store.Path.read_text

    def fail_note_read(path, *args, **kwargs):
        if path == note:
            raise OSError("note unavailable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(memory_store.Path, "read_text", fail_note_read)
    assert memory_store.recall_memory("!!!", root=base) == []
    assert memory_store.recall_memory("query", root=base) == []


def test_validate_memory_reports_missing_store_and_layout(tmp_path):
    missing = memory_store.validate_memory(root=tmp_path / "missing")
    assert missing["ok"] is False
    assert {row["code"] for row in missing["errors"]} == {"missing_store"}

    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    payload = memory_store.validate_memory(root=incomplete)
    assert payload["ok"] is False
    assert {row["code"] for row in payload["errors"]} == {"missing_readme", "missing_notes_dir"}


def test_validate_memory_reports_unreadable_and_malformed_entries(monkeypatch, tmp_path):
    base = tmp_path / "mem"
    notes = base / "notes"
    notes.mkdir(parents=True)
    (notes / "unreadable.md").write_text("# topic\n", encoding="utf-8")
    (notes / "malformed.md").write_text("# topic\n\n## malformed\n", encoding="utf-8")
    original_read_text = memory_store.Path.read_text

    def fail_one_note(path, *args, **kwargs):
        if path.name == "unreadable.md":
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(memory_store.Path, "read_text", fail_one_note)
    payload = memory_store.validate_memory(root=base)

    assert payload["ok"] is False
    assert {row["code"] for row in payload["errors"]} >= {"read_failed", "invalid_entry_header"}


def test_validate_memory_reports_legacy_and_invalid_index(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory("topic", "content", root=base)
    (base / "index.sqlite3").write_bytes(b"legacy")
    memory_store._index_path(base).write_text(
        json.dumps({"schema": "wrong", "entries": []}), encoding="utf-8"
    )

    payload = memory_store.validate_memory(root=base)

    assert payload["ok"] is False
    assert payload["index"]["legacy_path"].endswith("index.sqlite3")
    assert any(row["code"] == "legacy_index_read_only" for row in payload["warnings"])
    assert any(row["code"] == "invalid_index" for row in payload["errors"])


def test_validate_memory_reports_ok_for_initialized_store(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory("auth flow", "OAuth device flow.", root=base, actor="codex")
    payload = memory_store.validate_memory(root=base)
    assert payload["ok"] is True
    assert payload["notes"] == 1
    assert payload["entries"] == 1


def test_validate_memory_reports_missing_headers(tmp_path):
    base = tmp_path / "mem"
    notes = base / "notes"
    notes.mkdir(parents=True)
    (base / "README.md").write_text("ok\n", encoding="utf-8")
    (notes / "broken.md").write_text("bad\n", encoding="utf-8")
    payload = memory_store.validate_memory(root=base)
    assert payload["ok"] is False
    assert any(row["code"] == "missing_topic_header" for row in payload["errors"])


def test_validate_memory_reports_corrupt_index(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory("auth flow", "OAuth device flow.", root=base, actor="codex")
    memory_store._index_path(base).write_bytes(b"not-a-json-index")
    payload = memory_store.validate_memory(root=base)
    assert payload["ok"] is False
    assert any(row["code"] == "invalid_index" for row in payload["errors"])


def test_validate_memory_reports_stale_index_entry_count(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory("auth flow", "OAuth device flow.", root=base, actor="codex")
    index_path = memory_store._index_path(base)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["entries"] = []
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    payload = memory_store.validate_memory(root=base)
    assert payload["ok"] is False
    assert any(row["code"] == "stale_index" for row in payload["errors"])


def test_build_handoff_includes_validation_and_actor_metadata(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory(
        "release process",
        "Ship via draft PR first.",
        tags=["release", "workflow"],
        root=base,
        actor="claude-code",
    )
    payload = memory_store.build_handoff(
        "draft PR",
        root=base,
        from_agent="codex",
        to_agent="claude",
    )
    assert payload["schema"] == memory_store.MEMORY_HANDOFF_SCHEMA
    assert payload["validation"]["ok"] is True
    assert payload["from_agent"] == "codex"
    assert payload["to_agent"] == "claude"
    assert payload["results"][0]["actor"] == "claude-code"
    assert payload["results"][0]["tags"] == "release, workflow"


def test_cli_memory_init_store_recall(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    code = cli.main(["memory", "init", "--dir", str(mem_dir), "--json"])
    assert code == 0
    init_payload = json.loads(capsys.readouterr().out)
    assert init_payload["created"] is True

    code = cli.main(
        [
            "memory",
            "store",
            "release process",
            "Ship via draft PR first.",
            "--dir",
            str(mem_dir),
            "--json",
        ]
    )
    assert code == 0
    store_payload = json.loads(capsys.readouterr().out)
    assert store_payload["slug"] == "release-process"

    code = cli.main(["memory", "recall", "draft PR", "--dir", str(mem_dir), "--json"])
    assert code == 0
    recall_payload = json.loads(capsys.readouterr().out)
    assert len(recall_payload["results"]) == 1


def test_cli_memory_validate_and_handoff(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    cli.main(["memory", "store", "release process", "Ship via draft PR first.", "--dir", str(mem_dir)])
    capsys.readouterr()

    code = cli.main(["memory", "validate", "--dir", str(mem_dir), "--json"])
    assert code == 0
    validate_payload = json.loads(capsys.readouterr().out)
    assert validate_payload["ok"] is True

    code = cli.main(
        [
            "memory",
            "handoff",
            "draft PR",
            "--dir",
            str(mem_dir),
            "--from-agent",
            "codex",
            "--to-agent",
            "claude",
            "--json",
        ]
    )
    assert code == 0
    handoff_payload = json.loads(capsys.readouterr().out)
    assert handoff_payload["from_agent"] == "codex"
    assert handoff_payload["to_agent"] == "claude"
    assert len(handoff_payload["results"]) == 1


def test_cli_memory_validate_strict_exits_2_on_failure(tmp_path, capsys):
    """`simplicio/commands/memory.py`'s ``validate`` handler only maps a
    failing audit to a non-zero exit when ``--strict`` is passed (see
    ``return 0 if payload["ok"] or not getattr(a, "strict", False) else 2``);
    without it, a broken store still reports 0 so a script has to opt in to
    treating validation problems as fatal. Neither branch had CLI-level
    coverage before this test — `memory_store.validate_memory` itself was
    tested directly, but never through `cli.main(["memory", "validate", ...])`.
    """
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    notes_dir = mem_dir / "notes"
    notes_dir.mkdir(parents=True)
    (mem_dir / "README.md").write_text("# memory\n", encoding="utf-8")
    # Missing the required leading "# <topic>" header -> validate_memory()
    # appends a "missing_topic_header" error, so ok=False.
    (notes_dir / "broken.md").write_text("not a topic header\n", encoding="utf-8")

    lenient_code = cli.main(["memory", "validate", "--dir", str(mem_dir), "--json"])
    lenient_payload = json.loads(capsys.readouterr().out)
    assert lenient_code == 0
    assert lenient_payload["ok"] is False

    strict_code = cli.main(["memory", "validate", "--dir", str(mem_dir), "--json", "--strict"])
    capsys.readouterr()
    assert strict_code == 2


def test_cli_memory_validate_text_mode_prints_error_and_warning_rows(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    notes_dir = mem_dir / "notes"
    notes_dir.mkdir(parents=True)
    (mem_dir / "README.md").write_text("# memory\n", encoding="utf-8")
    (notes_dir / "broken.md").write_text("not a topic header\n", encoding="utf-8")

    code = cli.main(["memory", "validate", "--dir", str(mem_dir)])

    captured = capsys.readouterr()
    assert code == 0
    assert "simplicio-py memory validate: ok=False" in captured.out
    assert "ERROR missing_topic_header:" in captured.out


def test_cli_memory_init_text_mode_reports_dir_and_flags(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"

    code = cli.main(["memory", "init", "--dir", str(mem_dir)])

    captured = capsys.readouterr()
    assert code == 0
    assert f"simplicio-py memory init: {mem_dir}" in captured.out
    assert "created=True" in captured.out


def test_cli_memory_store_text_mode_reports_path(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"

    code = cli.main(["memory", "store", "release process", "Ship via draft PR first.", "--dir", str(mem_dir)])

    captured = capsys.readouterr()
    assert code == 0
    assert "simplicio-py memory store:" in captured.out
    assert "release-process" in captured.out


def test_cli_memory_recall_text_mode_reports_no_matches(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    cli.main(["memory", "init", "--dir", str(mem_dir)])
    capsys.readouterr()

    code = cli.main(["memory", "recall", "nothing stored yet", "--dir", str(mem_dir)])

    captured = capsys.readouterr()
    assert code == 0
    assert "no matches" in captured.out


def test_cli_memory_handoff_text_mode_reports_summary_line(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    cli.main(["memory", "store", "release process", "Ship via draft PR first.", "--dir", str(mem_dir)])
    capsys.readouterr()

    code = cli.main(
        [
            "memory",
            "handoff",
            "draft PR",
            "--dir",
            str(mem_dir),
            "--from-agent",
            "codex",
            "--to-agent",
            "claude",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "simplicio-py memory handoff:" in captured.out
    assert "from=codex to=claude" in captured.out
