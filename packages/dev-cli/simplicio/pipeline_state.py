"""Typed state contract for the task execution facade (issue #420)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PipelineState(StrEnum):
    INPUT = "INPUT"
    CONTEXT_BOUND = "CONTEXT_BOUND"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    PROPOSED = "PROPOSED"
    AUTHORIZED_OR_LOCAL_POLICY = "AUTHORIZED_OR_LOCAL_POLICY"
    STAGED = "STAGED"
    COMMITTED = "COMMITTED"
    VERIFIED = "VERIFIED"
    SEALED = "SEALED"
    BLOCKED = "BLOCKED"
    REFUSED = "REFUSED"
    EFFECT_UNKNOWN = "EFFECT_UNKNOWN"
    ROLLED_BACK = "ROLLED_BACK"


TERMINAL_STATES = frozenset(
    {
        PipelineState.SEALED,
        PipelineState.BLOCKED,
        PipelineState.REFUSED,
        PipelineState.EFFECT_UNKNOWN,
        PipelineState.ROLLED_BACK,
    }
)

_NEXT: dict[PipelineState, frozenset[PipelineState]] = {
    PipelineState.INPUT: frozenset(
        {
            PipelineState.CONTEXT_BOUND,
            PipelineState.BLOCKED,
            PipelineState.REFUSED,
            PipelineState.EFFECT_UNKNOWN,
            PipelineState.ROLLED_BACK,
        }
    ),
    PipelineState.CONTEXT_BOUND: frozenset({PipelineState.ROUTE_SELECTED, PipelineState.BLOCKED}),
    PipelineState.ROUTE_SELECTED: frozenset({PipelineState.PROPOSED, PipelineState.BLOCKED}),
    PipelineState.PROPOSED: frozenset(
        {PipelineState.AUTHORIZED_OR_LOCAL_POLICY, PipelineState.BLOCKED, PipelineState.REFUSED}
    ),
    PipelineState.AUTHORIZED_OR_LOCAL_POLICY: frozenset(
        {PipelineState.STAGED, PipelineState.BLOCKED, PipelineState.EFFECT_UNKNOWN}
    ),
    PipelineState.STAGED: frozenset(
        {PipelineState.COMMITTED, PipelineState.ROLLED_BACK, PipelineState.EFFECT_UNKNOWN}
    ),
    PipelineState.COMMITTED: frozenset(
        {PipelineState.VERIFIED, PipelineState.ROLLED_BACK, PipelineState.EFFECT_UNKNOWN}
    ),
    PipelineState.VERIFIED: frozenset({PipelineState.SEALED, PipelineState.ROLLED_BACK}),
}


class InvalidPipelineTransition(ValueError):
    """Raised when a result attempts to cross an impossible state edge."""


@dataclass(frozen=True)
class PipelineTrace:
    states: tuple[PipelineState, ...]

    def __post_init__(self) -> None:
        if not self.states or self.states[0] is not PipelineState.INPUT:
            raise InvalidPipelineTransition("pipeline trace must start at INPUT")
        for current, next_state in zip(self.states, self.states[1:], strict=False):
            if current in TERMINAL_STATES or next_state not in _NEXT.get(current, frozenset()):
                raise InvalidPipelineTransition(f"{current.value} -> {next_state.value} is not allowed")

    @property
    def terminal(self) -> PipelineState:
        return self.states[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.dev-cli.pipeline-state/v1",
            "states": [state.value for state in self.states],
            "terminal": self.terminal.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PipelineTrace:
        if payload.get("schema") != "simplicio.dev-cli.pipeline-state/v1":
            raise InvalidPipelineTransition("pipeline trace schema is invalid")
        raw_states = payload.get("states")
        if not isinstance(raw_states, list):
            raise InvalidPipelineTransition("pipeline trace states must be a list")
        try:
            states = tuple(PipelineState(value) for value in raw_states)
        except (TypeError, ValueError) as exc:
            raise InvalidPipelineTransition("pipeline trace contains an unknown state") from exc
        trace = cls(states)
        if payload.get("terminal") != trace.terminal.value:
            raise InvalidPipelineTransition("pipeline trace terminal does not match states")
        return trace


def transition(trace: PipelineTrace, next_state: PipelineState) -> PipelineTrace:
    current = trace.terminal
    if current in TERMINAL_STATES or next_state not in _NEXT.get(current, frozenset()):
        raise InvalidPipelineTransition(f"{current.value} -> {next_state.value} is not allowed")
    return PipelineTrace(trace.states + (next_state,))


def result_trace(result: dict[str, Any]) -> PipelineTrace:
    """Classify a legacy facade result into a terminal, non-mutating trace."""
    supplied = result.get("pipeline_state")
    if isinstance(supplied, dict):
        return PipelineTrace.from_dict(supplied)
    status = str(result.get("status") or "").lower()
    applied = bool(result.get("applied"))
    if status == "effect_unknown" or result.get("effect_unknown") is True:
        terminal = PipelineState.EFFECT_UNKNOWN
    elif status in {"refused", "invalid"}:
        terminal = PipelineState.REFUSED
    elif status in {"blocked", "dry_run"} or not applied:
        terminal = PipelineState.BLOCKED
    else:
        terminal = PipelineState.SEALED
    if terminal in {PipelineState.BLOCKED, PipelineState.REFUSED, PipelineState.EFFECT_UNKNOWN}:
        return PipelineTrace((PipelineState.INPUT, terminal))
    return PipelineTrace(
        (
            PipelineState.INPUT,
            PipelineState.CONTEXT_BOUND,
            PipelineState.ROUTE_SELECTED,
            PipelineState.PROPOSED,
            PipelineState.AUTHORIZED_OR_LOCAL_POLICY,
            PipelineState.STAGED,
            PipelineState.COMMITTED,
            PipelineState.VERIFIED,
            PipelineState.SEALED,
        )
    )
