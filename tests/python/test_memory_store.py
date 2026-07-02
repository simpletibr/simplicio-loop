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
        "auth flow", "Decided to use OAuth device flow for CLI login.",
        tags=["auth", "decision"], root=base, actor="claude-code",
    )
    results = memory_store.recall_memory("oauth device flow", root=base)
    assert results
    assert results[0]["topic"] == "auth-flow"
    assert "OAuth device flow" in results[0]["snippet"]


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


def test_cli_memory_init_store_recall(tmp_path, capsys):
    from simplicio import cli

    mem_dir = tmp_path / "mem"
    code = cli.main(["memory", "init", "--dir", str(mem_dir), "--json"])
    assert code == 0
    init_payload = json.loads(capsys.readouterr().out)
    assert init_payload["created"] is True

    code = cli.main([
        "memory", "store", "release process", "Ship via draft PR first.",
        "--dir", str(mem_dir), "--json",
    ])
    assert code == 0
    store_payload = json.loads(capsys.readouterr().out)
    assert store_payload["slug"] == "release-process"

    code = cli.main(["memory", "recall", "draft PR", "--dir", str(mem_dir), "--json"])
    assert code == 0
    recall_payload = json.loads(capsys.readouterr().out)
    assert len(recall_payload["results"]) == 1
