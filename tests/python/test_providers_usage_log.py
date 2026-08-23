"""Blocked provider calls produce no usage event."""

from __future__ import annotations

import json

import pytest

from simplicio import providers


def test_blocked_generation_does_not_write_usage_or_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))
    monkeypatch.setenv("SIMPLICIO_MODEL", "openai/gpt-5")
    monkeypatch.setattr(providers, "cache", lambda: pytest.fail("cache accessed"))
    with pytest.raises(providers.ProviderExecutionError):
        providers.generate("write hello")
    assert not list(tmp_path.glob("**/runs.jsonl"))
    assert not list(tmp_path.glob("**/*provider*"))


def test_blocked_receipt_is_secret_free(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_API_KEY", "super-secret")
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.generate("x")
    assert "super-secret" not in json.dumps(error.value.receipt)
