"""Typed EffectSink boundary used by the integrated pipeline.

Production uses :class:`RuntimeEffectSink`; ``RecordingEffectSink`` is an
explicit test double and is rejected by the integrated production entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from simplicio.plan_compiler.authority import EffectAuthorization
from simplicio.plan_compiler.models import EffectPlan, PlanDAG, PlanNode, VerificationPlan

EFFECT_STATES = frozenset(
    {
        "not_started",
        "denied",
        "running",
        "completed",
        "validation_failed",
        "rolled_back",
        "blocked_conflict",
        "cancelled_safe",
        "effect_unknown",
    }
)


@dataclass(frozen=True)
class EffectDispatchContext:
    """Plan and causal data which must cross the Runtime boundary intact."""

    plan_id: str
    goal_id: str
    plan_node: PlanNode
    verifications: list[VerificationPlan]
    coordinator_kind: str = "simplicio-dev-cli"
    coordinator_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    attempt: int = 1
    subworkflow_id: str = ""
    deadline: str | None = None
    policy_revision: str = ""
    base_hash: str = ""
    source_hash: str = ""
    context_handle: str = ""
    lease_id: str = ""
    fencing_token: str = ""
    authorization: EffectAuthorization | None = None
    plan: PlanDAG | None = None


@dataclass(frozen=True)
class EffectOutcome:
    """Verified Runtime state. Custody is deliberately not represented."""

    effect_id: str
    state: str
    idempotency_key: str
    receipt: dict[str, Any] | None = None
    reason_codes: list[str] = field(default_factory=list)
    validation: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    latency_ms: float | None = None
    transport: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state not in {"not_started", "running", "effect_unknown"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "state": self.state,
            "terminal": self.terminal,
            "idempotency_key": self.idempotency_key,
            "receipt": self.receipt,
            "reason_codes": self.reason_codes,
            "validation": self.validation,
            "rollback": self.rollback,
            "latency_ms": self.latency_ms,
            "transport": self.transport,
        }


@runtime_checkable
class EffectSink(Protocol):
    def submit(self, effect: EffectPlan, context: EffectDispatchContext) -> EffectOutcome: ...


class IntegratedModeRequiresSinkError(RuntimeError):
    """Integrated execution cannot obtain a real Runtime sink."""


class RecordingEffectSink:
    """Test-only sink; production integrated mode explicitly rejects it."""

    test_only = True

    def __init__(self, *, state: str = "not_started") -> None:
        if state not in EFFECT_STATES:
            raise ValueError(f"invalid effect state: {state}")
        self.state = state
        self.received: list[EffectPlan] = []
        self.contexts: list[EffectDispatchContext] = []

    def submit(self, effect: EffectPlan, context: EffectDispatchContext) -> EffectOutcome:
        self.received.append(effect)
        self.contexts.append(context)
        return EffectOutcome(effect.effect_id, self.state, effect.idempotency_key, transport="recording-test")
