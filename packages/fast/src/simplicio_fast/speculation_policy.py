"""Deterministic Fast-side selection for speculative decoding.

Fast decides which execution strategy is eligible. Simplicio Local consumes the
returned strategy and owns model, KV-cache, device, and kernel execution.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

SPECULATION_POLICY_SCHEMA = "simplicio.fast.speculation-policy/v1"
DECISION_OWNER = "simplicio-fast"
EXECUTION_OWNER = "simplicio-local"


class SpeculationConfiguration(str, Enum):
    """User-facing configuration values for the policy."""

    OFF = "off"
    AUTO = "auto"
    NGRAM = "ngram"
    DRAFT = "draft"
    DFLASH = "dflash"
    MTP = "mtp"

    @classmethod
    def parse(cls, value: str | SpeculationConfiguration) -> SpeculationConfiguration:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(f"unsupported speculation configuration: {value}") from exc


class SpeculationStrategy(str, Enum):
    """Strategies that Local may execute after Fast makes a decision."""

    BASELINE = "baseline"
    NGRAM = "ngram"
    DRAFT = "draft"
    DFLASH = "dflash"
    MTP = "mtp"


@dataclass(frozen=True, slots=True)
class StrategyCapability:
    """A backend capability and its optional expected speed relative to baseline."""

    supported: bool = False
    expected_speedup: float | None = None

    def is_usable(self) -> bool:
        """Return whether this capability is supported and expected to beat baseline."""
        if not self.supported:
            return False
        if self.expected_speedup is None:
            return True
        return math.isfinite(self.expected_speedup) and self.expected_speedup > 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "expected_speedup": self.expected_speedup,
        }


def _coerce_capability(value: StrategyCapability | bool) -> StrategyCapability:
    if isinstance(value, StrategyCapability):
        return value
    if isinstance(value, bool):
        return StrategyCapability(supported=value)
    raise TypeError("strategy capability must be StrategyCapability or bool")


@dataclass(frozen=True, slots=True)
class SpeculationCapabilities:
    """Capabilities reported by the Local backend for one policy decision.

    Boolean values are accepted as a compact capability-only form. An optional
    expected_speedup lets the policy reject a supported strategy that is
    measured or estimated to be no faster than baseline.
    """

    ngram: StrategyCapability | bool = False
    draft: StrategyCapability | bool = False
    dflash: StrategyCapability | bool = False
    mtp: StrategyCapability | bool = False

    def __post_init__(self) -> None:
        for name in ("ngram", "draft", "dflash", "mtp"):
            object.__setattr__(self, name, _coerce_capability(getattr(self, name)))

    def for_strategy(self, strategy: SpeculationStrategy) -> StrategyCapability:
        if strategy is SpeculationStrategy.BASELINE:
            return StrategyCapability(supported=True, expected_speedup=1.0)
        return getattr(self, strategy.value)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "baseline": self.for_strategy(SpeculationStrategy.BASELINE).to_dict(),
            "ngram": self.ngram.to_dict(),
            "draft": self.draft.to_dict(),
            "dflash": self.dflash.to_dict(),
            "mtp": self.mtp.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SpeculationReceipt:
    """Serializable evidence for one deterministic policy decision."""

    requested: SpeculationConfiguration
    selected: SpeculationStrategy
    reason: str
    fallback: bool
    capabilities: Mapping[str, Mapping[str, Any]]
    decision_owner: str = DECISION_OWNER
    execution_owner: str = EXECUTION_OWNER

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SPECULATION_POLICY_SCHEMA,
            "requested": self.requested.value,
            "selected": self.selected.value,
            "reason": self.reason,
            "fallback": self.fallback,
            "decision_owner": self.decision_owner,
            "execution_owner": self.execution_owner,
            "capabilities": {
                name: dict(value) for name, value in self.capabilities.items()
            },
        }


@dataclass(frozen=True, slots=True)
class SpeculationResult:
    """Typed plan/result returned to the Local execution boundary."""

    requested: SpeculationConfiguration
    selected: SpeculationStrategy
    reason: str
    receipt: SpeculationReceipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SPECULATION_POLICY_SCHEMA,
            "requested": self.requested.value,
            "selected": self.selected.value,
            "reason": self.reason,
            "execution_plan": {
                "strategy": self.selected.value,
                "owner": self.receipt.execution_owner,
            },
            "receipt": self.receipt.to_dict(),
        }


class SpeculationPolicy:
    """Choose one strategy without executing any inference work.

    Auto selection considers only usable capabilities. Candidates with a
    finite expected speedup are ranked by that speedup, with the fixed
    preference MTP, DFlash, Draft, then n-gram as the deterministic tie-break.
    A supported capability without a speed estimate uses that fixed preference.
    """

    _AUTO_PREFERENCE = (
        SpeculationStrategy.MTP,
        SpeculationStrategy.DFLASH,
        SpeculationStrategy.DRAFT,
        SpeculationStrategy.NGRAM,
    )

    def __init__(
        self,
        configuration: str | SpeculationConfiguration = SpeculationConfiguration.AUTO,
    ) -> None:
        self._configuration = SpeculationConfiguration.parse(configuration)

    @property
    def configuration(self) -> SpeculationConfiguration:
        return self._configuration

    def decide(
        self, capabilities: SpeculationCapabilities | None = None
    ) -> SpeculationResult:
        capabilities = capabilities or SpeculationCapabilities()
        if not isinstance(capabilities, SpeculationCapabilities):
            raise TypeError("capabilities must be SpeculationCapabilities")

        if self.configuration is SpeculationConfiguration.OFF:
            return self._result(
                capabilities,
                SpeculationStrategy.BASELINE,
                "disabled_by_configuration",
                fallback=False,
            )

        if self.configuration is not SpeculationConfiguration.AUTO:
            requested = SpeculationStrategy(self.configuration.value)
            capability = capabilities.for_strategy(requested)
            if not capability.supported:
                return self._result(
                    capabilities,
                    SpeculationStrategy.BASELINE,
                    "requested_strategy_unsupported",
                    fallback=True,
                )
            if not capability.is_usable():
                return self._result(
                    capabilities,
                    SpeculationStrategy.BASELINE,
                    "requested_strategy_not_faster_than_baseline",
                    fallback=True,
                )
            return self._result(
                capabilities,
                requested,
                "explicit_strategy_selected",
                fallback=False,
            )

        usable = [
            strategy
            for strategy in self._AUTO_PREFERENCE
            if capabilities.for_strategy(strategy).is_usable()
        ]
        if not usable:
            return self._result(
                capabilities,
                SpeculationStrategy.BASELINE,
                "no_faster_supported_strategy",
                fallback=True,
            )

        selected = max(
            usable,
            key=lambda strategy: self._auto_rank(strategy, capabilities),
        )
        return self._result(
            capabilities,
            selected,
            "auto_strategy_selected",
            fallback=False,
        )

    def _auto_rank(
        self,
        strategy: SpeculationStrategy,
        capabilities: SpeculationCapabilities,
    ) -> tuple[int, float, int]:
        capability = capabilities.for_strategy(strategy)
        if capability.expected_speedup is None:
            speed_known = 0
            speedup = 0.0
        else:
            speed_known = 1
            speedup = capability.expected_speedup
        preference = self._AUTO_PREFERENCE.index(strategy)
        return speed_known, speedup, -preference

    def _result(
        self,
        capabilities: SpeculationCapabilities,
        selected: SpeculationStrategy,
        reason: str,
        *,
        fallback: bool,
    ) -> SpeculationResult:
        receipt = SpeculationReceipt(
            requested=self.configuration,
            selected=selected,
            reason=reason,
            fallback=fallback,
            capabilities=capabilities.to_dict(),
        )
        return SpeculationResult(
            requested=self.configuration,
            selected=selected,
            reason=reason,
            receipt=receipt,
        )


__all__ = [
    "DECISION_OWNER",
    "EXECUTION_OWNER",
    "SPECULATION_POLICY_SCHEMA",
    "SpeculationCapabilities",
    "SpeculationConfiguration",
    "SpeculationPolicy",
    "SpeculationReceipt",
    "SpeculationResult",
    "SpeculationStrategy",
    "StrategyCapability",
]
