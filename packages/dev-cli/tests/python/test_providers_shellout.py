"""Provider CLI compatibility boundary tests."""

from __future__ import annotations

import pytest

from simplicio import providers


@pytest.mark.parametrize("model", ["claude-cli/sonnet", "codex-cli/gpt-5"])
def test_provider_cli_is_not_required(monkeypatch, model) -> None:
    monkeypatch.setenv("SIMPLICIO_MODEL", model)
    monkeypatch.setattr(providers, "_shell_out", lambda *_args, **_kwargs: pytest.fail("CLI spawned"))
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.generate("refactor x")
    assert error.value.receipt["reason_code"] == "llm_execution_disabled"
    assert error.value.receipt["side_effects"]["subprocess"] is False


def test_remote_credentials_are_not_resolved(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    assert providers.planner_cfg()["key"] is None
