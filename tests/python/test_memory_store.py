"""Cross-vendor memory handoff — markdown + git under a configurable memory
dir (issue #89 P0)."""

import json

import pytest

from simplicio import memory_store


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
    assert (base / "index.sqlite3").exists()


def test_recall_supports_fts5_and_vector_modes(tmp_path):
    base = tmp_path / "mem"
    memory_store.store_memory("release process", "Ship via a draft pull request.", root=base)
    for mode in ("fts5", "vector", "hybrid"):
        results = memory_store.recall_memory("draft pull request", root=base, mode=mode)
        assert results
        assert results[0]["mode"] == mode


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
