from unittest.mock import MagicMock, patch

import pytest

from simplicio import providers
from simplicio._cache import CacheEntry, cache, make_key, reset_for_tests


@pytest.fixture(autouse=True)
def isolated_completion_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SIMPLICIO_CACHE", raising=False)
    monkeypatch.delenv("SIMPLICIO_BUST_CACHE", raising=False)
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(providers, "_LAST_CACHE_RECEIPT", None)
    reset_for_tests()
    yield
    monkeypatch.setattr(providers, "_LAST_CACHE_RECEIPT", None)
    reset_for_tests()


def test_generate_receipt_marks_local_exact_reuse(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    prompt = providers._apply_directives("cached prompt")
    key = make_key(
        "doer",
        "anthropic/claude-opus",
        prompt,
        max_tokens=4000,
        template_version=None,
    )
    cache().put(key, CacheEntry("CACHED", provider_id="doer", model="anthropic/claude-opus"))

    assert providers.generate("cached prompt") == "CACHED"
    receipt = providers.last_cache_receipt()

    assert receipt is not None
    assert receipt["outcome"] == "local_exact_reuse"
    assert receipt["local_exact_lookup"]["status"] == "hit"
    assert receipt["provider_lookup"]["status"] == "not_tried"
    assert receipt["provider_write"]["status"] == "not_tried"


def test_generate_receipt_marks_provider_cache_read(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    prompt = providers._apply_directives("cached prompt")
    key = make_key(
        "anthropic-native",
        "anthropic/claude-opus",
        prompt,
        feedback=None,
        max_tokens=4000,
    )
    cache().put(
        key,
        CacheEntry("CACHED", provider_id="anthropic-native", model="anthropic/claude-opus"),
    )

    assert providers.generate("cached prompt") == "CACHED"
    receipt = providers.last_cache_receipt()

    assert receipt is not None
    assert receipt["outcome"] == "provider_cache_read"
    assert receipt["local_exact_lookup"]["status"] == "miss"
    assert receipt["provider_lookup"]["status"] == "hit"
    assert receipt["provider_write"]["status"] == "not_tried"


def test_generate_receipt_marks_provider_cache_write(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")

    ok = MagicMock(returncode=0, stdout="from cli", stderr="")
    with patch("subprocess.run", return_value=ok):
        assert providers.generate("cache me") == "from cli"

    receipt = providers.last_cache_receipt()
    assert receipt is not None
    assert receipt["outcome"] == "provider_cache_write"
    assert receipt["local_exact_lookup"]["status"] == "miss"
    assert receipt["provider_lookup"]["status"] == "miss"
    assert receipt["provider_write"]["status"] == "written"


def test_generate_receipt_marks_known_bypass(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.setenv("SIMPLICIO_CACHE", "0")

    ok = MagicMock(returncode=0, stdout="from cli", stderr="")
    with patch("subprocess.run", return_value=ok):
        assert providers.generate("cache me") == "from cli"

    receipt = providers.last_cache_receipt()
    assert receipt is not None
    assert receipt["outcome"] == "bypass"
    assert receipt["local_exact_lookup"]["status"] == "bypass"
    assert receipt["local_exact_lookup"]["reason"] == "cache_disabled"
    assert receipt["provider_lookup"]["status"] == "bypass"
    assert receipt["provider_write"]["status"] == "bypass"
