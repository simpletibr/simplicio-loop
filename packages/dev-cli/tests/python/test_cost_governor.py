import os
from decimal import Decimal

import pytest

from simplicio.orchestrator.cost_governor import (
    BudgetExceeded,
    CostGovernor,
    charge_provider_call,
    provider_budget,
)


def test_cost_governor_allows_missing_budget():
    gov = CostGovernor.from_value(None)
    gov.charge_usd("999")
    assert gov.report()["budget_usd"] is None


def test_cost_governor_raises_after_budget_exceeded():
    gov = CostGovernor.from_value("1.00")
    gov.charge_usd(Decimal("0.75"))

    with pytest.raises(BudgetExceeded):
        gov.charge_usd("0.26")


def test_cost_governor_rejects_negative_budget():
    with pytest.raises(ValueError):
        CostGovernor.from_value("-1")


def test_cost_governor_rejects_non_finite_budget():
    for value in ("abc", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            CostGovernor.from_value(value)


def test_provider_charge_updates_spent_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MAX_COST", "1")
    monkeypatch.setenv("SIMPLICIO_PRICE_PER_MTOK", "100")
    monkeypatch.delenv("SIMPLICIO_COST_SPENT_USD", raising=False)

    charge_provider_call("model", "x" * 4000, "y" * 4000)

    assert Decimal(os.environ["SIMPLICIO_COST_SPENT_USD"]) > 0


def test_provider_charge_updates_spent_env_before_budget_exception(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MAX_COST", "0.0001")
    monkeypatch.setenv("SIMPLICIO_COST_SPENT_USD", "0")
    monkeypatch.setenv("SIMPLICIO_PRICE_PER_MTOK", "100")

    try:
        charge_provider_call("model", "x" * 4000, "y" * 4000)
    except BudgetExceeded:
        pass
    else:
        raise AssertionError("expected BudgetExceeded")

    assert Decimal(os.environ["SIMPLICIO_COST_SPENT_USD"]) > Decimal("0.0001")


def test_provider_budget_exposes_and_restores_explicit_budget(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MAX_COST", raising=False)
    monkeypatch.delenv("SIMPLICIO_COST_SPENT_USD", raising=False)
    monkeypatch.setenv("SIMPLICIO_PRICE_PER_MTOK", "100")

    with provider_budget("1.25") as governor:
        assert os.environ["SIMPLICIO_MAX_COST"] == "1.25"
        assert os.environ["SIMPLICIO_COST_SPENT_USD"] == "0"
        charge_provider_call("model", "x" * 4000, "y" * 4000)
        governor.refresh_from_env()
        assert governor.spent_usd > 0

    assert "SIMPLICIO_MAX_COST" not in os.environ
    assert "SIMPLICIO_COST_SPENT_USD" not in os.environ
