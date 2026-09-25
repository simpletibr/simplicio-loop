"""Planner boundary tests for deterministic-only operation."""

from __future__ import annotations

import pytest

from simplicio import providers


def test_planner_config_is_provider_free(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "openai/gpt-5")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    config = providers.planner_cfg()
    assert config["disabled"] is True
    assert config["model"] is None
    assert config["key"] is None


def test_planner_info_is_deterministic() -> None:
    assert providers.planner_info() == "planner=disabled provider=deterministic-only"


def test_planner_complete_blocks_before_provider_access(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "deepseek/deepseek-v4")
    monkeypatch.setenv("SIMPLICIO_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr(providers, "_import_openai", lambda: pytest.fail("provider imported"))
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.planner_complete("plan this")
    assert error.value.receipt["reason_code"] == "llm_execution_disabled"
    assert error.value.receipt["effective_route"] == "deterministic"
    assert error.value.receipt["model_invoked"] is False
