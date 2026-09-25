"""Pure prompt-compatibility tests for the retired provider boundary."""

from __future__ import annotations

import pytest

from simplicio import providers


def test_directive_block_covers_the_four_constraints() -> None:
    assert "No thinking" in providers.LLM_DIRECTIVES
    assert "No internet" in providers.LLM_DIRECTIVES
    assert "Tools" in providers.LLM_DIRECTIVES
    assert "Skills" in providers.LLM_DIRECTIVES


def test_apply_directives_is_idempotent() -> None:
    prompt = providers._apply_directives("write hello")
    assert providers._apply_directives(prompt) == prompt


def test_generation_is_blocked_before_directives_are_applied(monkeypatch) -> None:
    monkeypatch.setattr(providers, "_apply_directives", lambda _prompt: pytest.fail("prompt transformed"))
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.generate("write hello")
    assert error.value.receipt["reason_code"] == "llm_execution_disabled"
