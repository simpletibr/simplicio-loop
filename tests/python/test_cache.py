import json
import os
import threading
from unittest.mock import patch

import pytest

from simplicio import providers
from simplicio._cache import (
    CacheEntry,
    CompletionCache,
    cache,
    make_key,
    reset_for_tests,
)
from simplicio.cli import main as cli_main


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SIMPLICIO_CACHE", raising=False)
    monkeypatch.delenv("SIMPLICIO_BUST_CACHE", raising=False)
    monkeypatch.delenv("SIMPLICIO_CACHE_TTL_DAYS", raising=False)
    monkeypatch.delenv("SIMPLICIO_CACHE_MAX_MB", raising=False)
    reset_for_tests()
    yield
    reset_for_tests()


def test_make_key_changes_with_prompt_and_template_version():
    key_a = make_key("provider", "model", "prompt", template_version="1")
    key_b = make_key("provider", "model", "prompt", template_version="2")
    key_c = make_key("provider", "model", "other", template_version="1")

    assert key_a != key_b
    assert key_a != key_c
    assert len(key_a) == 64


def test_hit_miss_ttl_and_malformed_cleanup(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_TTL_DAYS", "0.001")
    c = CompletionCache()
    key = make_key("p", "m", "prompt")

    assert c.get(key) is None
    c.put(key, CacheEntry("cached", provider_id="p", model="m"))
    assert c.get(key).completion == "cached"

    path = c.path_for(key)
    old = os.path.getmtime(path) - 1000
    os.utime(path, (old, old))
    assert c.get(key) is None
    assert not path.exists()

    c.put(key, CacheEntry("cached", provider_id="p", model="m"))
    path.write_text("{not-json", encoding="utf-8")
    assert c.get(key) is None
    assert not path.exists()


def test_bust_forces_miss_but_put_still_writes(monkeypatch):
    c = CompletionCache()
    key = make_key("p", "m", "prompt")
    c.put(key, CacheEntry("cached", provider_id="p", model="m"))

    monkeypatch.setenv("SIMPLICIO_BUST_CACHE", "1")
    assert c.get(key) is None
    c.put(key, CacheEntry("fresh", provider_id="p", model="m"))

    monkeypatch.setenv("SIMPLICIO_BUST_CACHE", "0")
    assert c.get(key).completion == "fresh"


def test_disabled_cache_is_noop(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE", "0")
    c = CompletionCache()
    key = make_key("p", "m", "prompt")

    c.put(key, CacheEntry("cached", provider_id="p", model="m"))

    assert c.get(key) is None
    assert c.stats()["entries"] == 0


def test_cache_stats_track_session_hit_rate():
    c = CompletionCache()
    key = make_key("p", "m", "prompt")

    assert c.get(key) is None
    c.put(key, CacheEntry("cached", provider_id="p", model="m"))
    assert c.get(key).completion == "cached"

    stats = c.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["puts"] == 1
    assert stats["hit_rate"] == 0.5


def test_concurrent_writes_keep_valid_json():
    c = CompletionCache()
    key = make_key("p", "m", "prompt")

    def write(i):
        c.put(key, CacheEntry(f"value-{i}", provider_id="p", model="m"))

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    path = c.path_for(key)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["completion"].startswith("value-")
    assert c.get(key).completion.startswith("value-")


def test_lru_eviction_removes_oldest(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_MAX_MB", "0.001")
    monkeypatch.setenv("SIMPLICIO_CACHE_EVICT_EVERY", "1")
    c = CompletionCache()
    old_key = make_key("p", "m", "old")
    new_key = make_key("p", "m", "new")

    c.put(old_key, CacheEntry("x" * 600, provider_id="p", model="m"))
    old_path = c.path_for(old_key)
    old = os.path.getmtime(old_path) - 100
    os.utime(old_path, (old, old))
    c.put(new_key, CacheEntry("y" * 600, provider_id="p", model="m"))

    assert c.get(old_key) is None
    assert c.get(new_key) is not None


def test_provider_cache_short_circuits_missing_api_key(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)
    key = make_key(
        "anthropic-native",
        "anthropic/claude-opus",
        providers._apply_directives("cached prompt"),
        feedback=None,
        max_tokens=4000,
    )
    cache().put(
        key,
        CacheEntry(
            "CACHED",
            provider_id="anthropic-native",
            model="anthropic/claude-opus",
        ),
    )

    assert providers.generate("cached prompt") == "CACHED"


def test_planner_cache_short_circuits_missing_api_key(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_PLANNER", "deepseek/deepseek-v4-pro")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = providers.planner_cfg(require_key=False)
    key = providers._planner_cache_key(
        cfg,
        providers._apply_directives("cached plan"),
        8192,
        0.1,
        "stack-v1",
    )
    cache().put(
        key,
        CacheEntry(
            "CACHED_PLAN",
            provider_id=providers._planner_provider_id(cfg),
            model=cfg["model"],
        ),
    )

    assert providers.planner_complete("cached plan", template_version="stack-v1") == ("CACHED_PLAN")
    with pytest.raises(SystemExit):
        providers.planner_complete("cached plan", template_version="stack-v2")


def test_provider_writes_shell_out_completion_to_cache(monkeypatch):
    from simplicio.task_operator import PHASE_COMPLETED, BoundedRunResult

    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    with patch("simplicio.task_operator.run_bounded_subprocess") as run:
        run.return_value = BoundedRunResult(
            phase=PHASE_COMPLETED,
            elapsed_s=0.01,
            returncode=0,
            stdout="from cli",
            stderr="",
            recovery="",
        )

        assert providers.generate("cache me") == "from cli"
        assert providers.generate("cache me") == "from cli"

    assert run.call_count == 1


def test_cache_cli_stats_and_clear(capsys):
    key = make_key("p", "m", "prompt")
    cache().put(key, CacheEntry("cached", provider_id="p", model="m"))

    assert cli_main(["cache", "stats", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["entries"] == 1

    assert cli_main(["cache", "clear"]) == 2
    assert cli_main(["cache", "clear", "--force"]) == 0
    assert "cleared 1" in capsys.readouterr().out


def test_eviction_runs_only_on_configured_put_interval(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_EVICT_EVERY", "16")
    c = CompletionCache()
    calls = []
    monkeypatch.setattr(c, "_evict_if_needed", lambda: calls.append(c.puts))

    for i in range(17):
        c.put(make_key("p", "m", f"prompt-{i}"), CacheEntry("cached", provider_id="p", model="m"))

    assert calls == [1, 16]
