"""Public generation boundary tests."""

from __future__ import annotations

import pytest

from simplicio import providers


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"SIMPLICIO_MODEL": "local-llama/default"},
        {"SIMPLICIO_MODEL": "qwen3", "SIMPLICIO_BASE_URL": "http://127.0.0.1:11434/v1"},
        {"SIMPLICIO_MODEL": "openai/gpt-5", "SIMPLICIO_BASE_URL": "https://api.openai.com/v1"},
    ],
)
def test_generate_never_requires_local_or_remote_llm(monkeypatch, environment) -> None:
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(providers, "cache", lambda: pytest.fail("cache accessed"))
    monkeypatch.setattr(providers, "_import_openai", lambda: pytest.fail("remote provider imported"))
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.generate("change this")
    receipt = error.value.receipt
    assert receipt["reason_code"] == "llm_execution_disabled"
    assert receipt["effective_route"] == "deterministic"
    assert receipt["model_invoked"] is False
    assert not any(receipt["side_effects"].values())


def test_local_worker_is_guarded() -> None:
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers._local_generate("prompt", None, "local-llama/default", 32)
    assert error.value.receipt["reason_code"] == "llm_execution_disabled"
