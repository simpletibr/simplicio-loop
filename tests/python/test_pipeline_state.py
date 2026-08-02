from __future__ import annotations

import pytest

from simplicio.pipeline_state import (
    InvalidPipelineTransition,
    PipelineState,
    PipelineTrace,
    result_trace,
    transition,
)


def test_valid_trace_reaches_sealed_and_is_serializable():
    trace = PipelineTrace((PipelineState.INPUT,))
    for state in (
        PipelineState.CONTEXT_BOUND,
        PipelineState.ROUTE_SELECTED,
        PipelineState.PROPOSED,
        PipelineState.AUTHORIZED_OR_LOCAL_POLICY,
        PipelineState.STAGED,
        PipelineState.COMMITTED,
        PipelineState.VERIFIED,
        PipelineState.SEALED,
    ):
        trace = transition(trace, state)
    assert trace.terminal is PipelineState.SEALED
    assert trace.to_dict()["states"][-1] == "SEALED"


def test_terminal_states_cannot_return_to_mutation():
    with pytest.raises(InvalidPipelineTransition):
        transition(PipelineTrace((PipelineState.INPUT, PipelineState.BLOCKED)), PipelineState.STAGED)
    assert (
        result_trace({"status": "effect_unknown", "applied": False}).terminal is PipelineState.EFFECT_UNKNOWN
    )
    assert result_trace({"status": "ok", "applied": True}).terminal is PipelineState.SEALED


def test_pipeline_trace_rejects_empty_non_initial_and_terminal_mismatch():
    with pytest.raises(InvalidPipelineTransition):
        PipelineTrace(())
    with pytest.raises(InvalidPipelineTransition):
        PipelineTrace((PipelineState.BLOCKED,))

    valid = result_trace({"status": "blocked", "applied": False}).to_dict()
    valid["terminal"] = PipelineState.SEALED.value
    with pytest.raises(InvalidPipelineTransition):
        PipelineTrace.from_dict(valid)


def test_result_trace_validates_supplied_receipt_states():
    receipt = result_trace({"status": "blocked", "applied": False}).to_dict()
    assert result_trace({"pipeline_state": receipt}).terminal is PipelineState.BLOCKED
    receipt["states"] = [PipelineState.INPUT.value, PipelineState.SEALED.value]
    with pytest.raises(InvalidPipelineTransition):
        result_trace({"pipeline_state": receipt})
