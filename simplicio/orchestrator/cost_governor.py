"""Lightweight cost budget guard for long-running orchestration."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterator

from ..observability import estimate_tokens as _canonical_estimate_tokens


class BudgetExceeded(RuntimeError):
    """Raised when an orchestration run exceeds its configured cost budget."""


@dataclass
class CostGovernor:
    budget_usd: Decimal | None = None
    spent_usd: Decimal = Decimal("0")

    @classmethod
    def from_value(cls, value: str | float | int | None) -> "CostGovernor":
        raw = value if value is not None else os.environ.get("SIMPLICIO_MAX_COST")
        if raw in (None, ""):
            return cls(None)
        try:
            budget = Decimal(str(raw))
            spent = Decimal(os.environ.get("SIMPLICIO_COST_SPENT_USD", "0"))
        except InvalidOperation as exc:
            raise ValueError("max cost must be a finite decimal") from exc
        if not budget.is_finite() or not spent.is_finite():
            raise ValueError("max cost must be a finite decimal")
        if budget < 0:
            raise ValueError("max cost must be non-negative")
        return cls(budget, spent)

    def charge_usd(self, amount: str | float | int | Decimal) -> None:
        try:
            cost = Decimal(str(amount))
        except InvalidOperation as exc:
            raise ValueError("cost charge must be a finite decimal") from exc
        if not cost.is_finite():
            raise ValueError("cost charge must be a finite decimal")
        if cost < 0:
            raise ValueError("cost charge must be non-negative")
        self.spent_usd += cost
        if self.budget_usd is not None and self.spent_usd > self.budget_usd:
            raise BudgetExceeded(
                f"cost budget exceeded: spent ${self.spent_usd} "
                f"over budget ${self.budget_usd}"
            )

    def refresh_from_env(self) -> None:
        raw = os.environ.get("SIMPLICIO_COST_SPENT_USD")
        if raw not in (None, ""):
            self.spent_usd = Decimal(raw)

    def report(self) -> dict[str, str | None]:
        remaining = None
        if self.budget_usd is not None:
            remaining = str(self.budget_usd - self.spent_usd)
        return {
            "budget_usd": str(self.budget_usd) if self.budget_usd is not None else None,
            "spent_usd": str(self.spent_usd),
            "remaining_usd": remaining,
        }


@contextmanager
def provider_budget(value: str | float | int | None) -> Iterator[CostGovernor]:
    """Expose a max-cost value to nested provider calls for one run."""

    explicit_budget = value not in (None, "")
    old_budget = os.environ.get("SIMPLICIO_MAX_COST")
    old_spent = os.environ.get("SIMPLICIO_COST_SPENT_USD")
    governor = CostGovernor.from_value(value)

    if governor.budget_usd is not None:
        os.environ["SIMPLICIO_MAX_COST"] = str(governor.budget_usd)
        os.environ["SIMPLICIO_COST_SPENT_USD"] = str(governor.spent_usd)

    try:
        yield governor
    finally:
        governor.refresh_from_env()
        if explicit_budget:
            if old_budget is None:
                os.environ.pop("SIMPLICIO_MAX_COST", None)
            else:
                os.environ["SIMPLICIO_MAX_COST"] = old_budget
            if old_spent is None:
                os.environ.pop("SIMPLICIO_COST_SPENT_USD", None)
            else:
                os.environ["SIMPLICIO_COST_SPENT_USD"] = old_spent


def charge_provider_call(model: str | None, prompt: str, completion: str) -> None:
    """Charge an estimated provider call when SIMPLICIO_MAX_COST is configured."""

    if not os.environ.get("SIMPLICIO_MAX_COST"):
        return
    governor = CostGovernor.from_value(None)
    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(completion)
    cost = _price(model, prompt_tokens, completion_tokens)
    try:
        governor.charge_usd(cost)
    finally:
        os.environ["SIMPLICIO_COST_SPENT_USD"] = str(governor.spent_usd)


def _estimate_tokens(text: str) -> int:
    """Delegates to the single canonical estimator (issue #88 AC4).

    This module used to run its own `chars/4` heuristic while
    `observability.estimate_tokens` ran a `words*4/3` heuristic on the same
    text — the two could diverge ~30% on the same prompt, so a before/after
    token claim depended on which one happened to be quoted. There is now
    exactly one estimator (`observability.ESTIMATOR_LABEL`); this wrapper
    stays only so existing call sites in this module do not need to change.
    """
    return _canonical_estimate_tokens(text)


def _price(model: str | None, prompt_tokens: int, completion_tokens: int) -> Decimal:
    prompt_price = Decimal(os.environ.get("SIMPLICIO_PRICE_PROMPT_PER_MTOK", "0"))
    completion_price = Decimal(
        os.environ.get("SIMPLICIO_PRICE_COMPLETION_PER_MTOK", "0")
    )
    if prompt_price == 0 and completion_price == 0:
        blended = Decimal(os.environ.get("SIMPLICIO_PRICE_PER_MTOK", "0"))
        prompt_price = blended
        completion_price = blended
    total = (
        Decimal(prompt_tokens) * prompt_price
        + Decimal(completion_tokens) * completion_price
    ) / Decimal("1000000")
    return total.quantize(Decimal("0.0000001"))
