"""_task_result's cost_usd/cost_basis contract (issue #88 AC4).

cost_usd used to be hardcoded to 0.0 unconditionally. It is now computed
from the same pricing helper the cost governor charges against, and
`cost_basis` always says whether that number came from configured pricing
("estimated") or is genuinely unknown ("unknown_no_pricing_configured") —
never a silently fake real cost.
"""
from simplicio.pipeline import _task_result


def test_cost_usd_unknown_basis_without_pricing_env(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)
    monkeypatch.delenv("SIMPLICIO_PRICE_PROMPT_PER_MTOK", raising=False)
    monkeypatch.delenv("SIMPLICIO_PRICE_COMPLETION_PER_MTOK", raising=False)

    result = _task_result("t1", "a prompt", "some output", applied=True)

    assert result["cost_usd"] == 0.0
    assert result["cost_basis"] == "unknown_no_pricing_configured"


def test_cost_usd_estimated_when_pricing_configured(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_PRICE_PER_MTOK", "100")
    monkeypatch.setenv("SIMPLICIO_MODEL", "some-model")

    result = _task_result("t1", "a prompt " * 50, "some output " * 50, applied=True)

    assert result["cost_basis"] == "estimated"
    assert result["cost_usd"] > 0.0
