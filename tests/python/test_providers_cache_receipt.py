"""Cache receipt helpers remain deterministic and side-effect free."""

from __future__ import annotations

from simplicio import providers


def test_new_cache_receipt_is_not_needed_for_blocked_execution() -> None:
    providers._remember_cache_receipt(None)
    assert providers.last_cache_receipt() is None


def test_provider_policy_receipt_is_separate_from_cache() -> None:
    from simplicio.llm_policy import execution_disabled_receipt

    receipt = execution_disabled_receipt(
        surface="test",
        model="openai/gpt-5",
        base_url="https://api.openai.com/v1",
    )
    assert receipt["schema"] == "simplicio.llm-policy-receipt/v1"
    assert receipt["requested_route"] == "remote"
    assert receipt["effective_route"] == "deterministic"
    assert receipt["side_effects"]["network"] is False
