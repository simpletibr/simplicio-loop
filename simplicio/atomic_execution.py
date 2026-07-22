"""One-dispatch/one-attempt execution boundary for integrated coordinators.

This module deliberately has no scheduler, retry loop, provider selection,
worktree creation, queue, or terminal-state writer.  The coordinator supplies
one already-selected PlanNode and its causal attempt/lease context; Dev CLI
may submit at most the single effect belonging to that node and returns an
observation.  What happens next is exclusively a coordinator decision.
"""

from __future__ import annotations

import contextvars
import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from simplicio.plan_compiler.effect_sink import EffectDispatchContext, EffectOutcome, EffectSink
from simplicio.plan_compiler.models import EffectPlan, PlanNode, VerificationPlan

ATOMIC_OBSERVATION_SCHEMA = "simplicio.dev-cli.atomic-observation/v1"
Outcome = Literal[
    "completed",
    "effect_submitted",
    "failed",
    "cancelled",
    "lease_lost",
    "stale_fence",
    "effect_unknown",
]
Retryability = Literal["retryable", "non_retryable", "unknown"]
CancellationCheck = Callable[[], bool]
LeaseCheck = Callable[[str, str], bool]
FenceCheck = Callable[[str], bool]


class IntegratedOwnershipError(RuntimeError):
    """An integrated caller attempted to reintroduce local lifecycle ownership."""


@dataclass(frozen=True)
class AttemptContext:
    """Coordinator-owned identity and guards for exactly one dispatch."""

    attempt_id: str
    lease_id: str
    fencing_token: str
    context_handle: str
    deadline_monotonic: float | None = None
    cancellation_requested: CancellationCheck = field(default=lambda: False, repr=False, compare=False)
    lease_valid: LeaseCheck = field(default=lambda _lease, _fence: True, repr=False, compare=False)
    fence_current: FenceCheck = field(default=lambda _fence: True, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in ("attempt_id", "lease_id", "fencing_token", "context_handle"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required for integrated execution")


@dataclass(frozen=True)
class AtomicObservation:
    """Executor facts sufficient for an external coordinator's next decision."""

    outcome: Outcome
    reason: str
    failure_fingerprint: str | None
    retryability: Retryability
    attempt_id: str
    lease_id: str
    fencing_token: str
    context_handle: str
    plan_node_id: str
    effect_ids: tuple[str, ...]
    evidence_handles: tuple[str, ...]
    receipt_handles: tuple[str, ...]
    validation: tuple[Mapping[str, Any], ...]
    resources: Mapping[str, int | float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ATOMIC_OBSERVATION_SCHEMA,
            "outcome": self.outcome,
            "reason": self.reason,
            "failure_fingerprint": self.failure_fingerprint,
            "retryability": self.retryability,
            "attempt_id": self.attempt_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "context_handle": self.context_handle,
            "plan_node_id": self.plan_node_id,
            "effect_ids": list(self.effect_ids),
            "evidence_handles": list(self.evidence_handles),
            "receipt_handles": list(self.receipt_handles),
            "validation": [dict(item) for item in self.validation],
            "resources": dict(self.resources),
        }


_ACTIVE_ATTEMPT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "simplicio_integrated_attempt", default=None
)


def _fingerprint(reason: str) -> str:
    return hashlib.sha256(reason.encode("utf-8", errors="replace")).hexdigest()[:16]


def _guard_reason(attempt: AttemptContext) -> tuple[Outcome, str] | None:
    if attempt.cancellation_requested():
        return "cancelled", "coordinator cancellation requested"
    if attempt.deadline_monotonic is not None and time.monotonic() >= attempt.deadline_monotonic:
        return "cancelled", "coordinator deadline elapsed"
    if not attempt.fence_current(attempt.fencing_token):
        return "stale_fence", "coordinator fencing token is stale"
    if not attempt.lease_valid(attempt.lease_id, attempt.fencing_token):
        return "lease_lost", "coordinator lease is no longer valid"
    return None


def _observation(
    outcome: Outcome,
    reason: str,
    retryability: Retryability,
    *,
    node: PlanNode,
    attempt: AttemptContext,
    started: float,
    effect_ids: tuple[str, ...] = (),
    evidence_handles: tuple[str, ...] = (),
    receipt_handles: tuple[str, ...] = (),
    validation: tuple[Mapping[str, Any], ...] = (),
) -> AtomicObservation:
    return AtomicObservation(
        outcome=outcome,
        reason=reason,
        failure_fingerprint=None if outcome in {"completed", "effect_submitted"} else _fingerprint(reason),
        retryability=retryability,
        attempt_id=attempt.attempt_id,
        lease_id=attempt.lease_id,
        fencing_token=attempt.fencing_token,
        context_handle=attempt.context_handle,
        plan_node_id=node.node_id,
        effect_ids=effect_ids,
        evidence_handles=evidence_handles,
        receipt_handles=receipt_handles,
        validation=validation,
        resources={
            "atomic_attempts": 1,
            "effect_calls": len(effect_ids),
            "model_calls": 0,
            "subprocesses": 0,
            "threads_created": 0,
            "worktrees_created": 0,
            "tokens": 0,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        },
    )


def execute_work_item_once(
    plan_node: PlanNode,
    attempt: AttemptContext,
    *,
    effects: Sequence[EffectPlan],
    verifications: Sequence[VerificationPlan],
    effect_sink: EffectSink,
    dispatch_context: EffectDispatchContext | None = None,
) -> AtomicObservation:
    """Execute one selected node once, without making lifecycle decisions.

    An effectful node must have exactly one matching effect.  This structural
    restriction makes a single dispatch incapable of hiding a retry/batch.
    Guard checks run immediately before the only mutating boundary.  Sink
    exceptions become ``effect_unknown`` and are never retried here.
    """
    active = _ACTIVE_ATTEMPT.get()
    if active is not None:
        raise IntegratedOwnershipError(
            f"nested integrated attempt is forbidden: active={active}, requested={attempt.attempt_id}"
        )
    matching_effects = tuple(effect for effect in effects if effect.plan_node_id == plan_node.node_id)
    unrelated = [effect.effect_id for effect in effects if effect.plan_node_id != plan_node.node_id]
    if unrelated:
        raise IntegratedOwnershipError("one dispatch may contain effects only for its selected PlanNode")
    if len(matching_effects) > 1:
        raise IntegratedOwnershipError("one integrated PlanNode may submit at most one effect per dispatch")

    started = time.monotonic()
    token = _ACTIVE_ATTEMPT.set(attempt.attempt_id)
    try:
        guard = _guard_reason(attempt)
        if guard is not None:
            outcome, reason = guard
            return _observation(
                outcome, reason, "retryable", node=plan_node, attempt=attempt, started=started
            )

        matching_validations = tuple(
            {
                "verification_id": item.verification_id,
                "verifier": item.verifier,
                "acceptance_criteria_refs": list(item.acceptance_criteria_refs),
            }
            for item in verifications
            if item.plan_node_id == plan_node.node_id
        )
        if not matching_effects:
            return _observation(
                "completed",
                "effect-free node observed; coordinator retains verification scheduling",
                "non_retryable",
                node=plan_node,
                attempt=attempt,
                started=started,
                validation=matching_validations,
            )

        # Re-check at the last possible instant before the only effect boundary.
        guard = _guard_reason(attempt)
        if guard is not None:
            outcome, reason = guard
            return _observation(
                outcome, reason, "retryable", node=plan_node, attempt=attempt, started=started
            )
        effect = matching_effects[0]
        try:
            context = dispatch_context or EffectDispatchContext(
                plan_id="",
                goal_id="",
                plan_node=plan_node,
                verifications=list(verifications),
                coordinator_id=attempt.attempt_id,
            )
            result: EffectOutcome = effect_sink.submit(effect, context)
        except IntegratedOwnershipError:
            raise
        except Exception as exc:
            reason = f"effect outcome unknown after sink failure: {type(exc).__name__}"
            return _observation(
                "effect_unknown",
                reason,
                "unknown",
                node=plan_node,
                attempt=attempt,
                started=started,
                effect_ids=(effect.effect_id,),
            )

        receipt_payload = result.receipt or {}
        receipt = str(receipt_payload.get("receipt_handle", result.idempotency_key)).strip()
        evidence = tuple(
            str(item) for item in receipt_payload.get("evidence_handles", ()) if str(item).strip()
        )
        accepted_states = {"not_started", "running", "completed"}
        if result.state not in accepted_states:
            reason = ", ".join(result.reason_codes) or f"runtime effect state: {result.state}"
            retryability: Retryability = (
                "unknown"
                if result.state == "effect_unknown"
                else "retryable"
                if result.state == "blocked_conflict"
                else "non_retryable"
            )
            return _observation(
                "effect_unknown" if result.state == "effect_unknown" else "failed",
                reason,
                retryability,
                node=plan_node,
                attempt=attempt,
                started=started,
                effect_ids=(effect.effect_id,),
                receipt_handles=(receipt,) if receipt else (),
            )
        return _observation(
            "effect_submitted",
            f"runtime accepted atomic submission with state {result.state}",
            "non_retryable",
            node=plan_node,
            attempt=attempt,
            started=started,
            effect_ids=(effect.effect_id,),
            evidence_handles=evidence,
            receipt_handles=(receipt,) if receipt else (),
            validation=matching_validations,
        )
    finally:
        _ACTIVE_ATTEMPT.reset(token)


__all__ = [
    "ATOMIC_OBSERVATION_SCHEMA",
    "AtomicObservation",
    "AttemptContext",
    "IntegratedOwnershipError",
    "execute_work_item_once",
]
