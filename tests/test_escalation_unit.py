"""Unit tests for escalation: retry and escalate execution failures up the ladder.

Escalation ladder: execution -> coordination -> planning -> stop
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from simplicio_loop import escalation, model_roles


@pytest.fixture
def temp_repo():
    """Create a temporary repository for escalation state."""
    with tempfile.TemporaryDirectory(prefix="test-escalation-") as tmpdir:
        yield Path(tmpdir)


def test_escalation_record_to_dict():
    record = escalation.EscalationRecord(
        step=0,
        role="execution",
        family="claude",
        model="claude-haiku-5-5",
        effort="high",
        attempt=1,
        outcome="failed",
        error="timeout",
        execution_ms=50000.0,
    )
    d = record.to_dict()
    assert d["step"] == 0
    assert d["role"] == "execution"
    assert d["family"] == "claude"
    assert d["model"] == "claude-haiku-5-5"
    assert d["attempt"] == 1
    assert d["outcome"] == "failed"
    assert "timestamp" in d


def test_escalation_state_creation(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    assert state.issue == 123
    assert state.family == "claude"
    assert state.current_step == 0
    assert state.current_role() == "execution"
    assert state.attempts_in_step == 0


def test_escalation_ladder_roles():
    assert escalation.ESCALATION_LADDER == ("execution", "coordination", "planning")


def test_escalation_state_record_attempt(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    record = state.record_attempt("failed", error="timeout", execution_ms=30000.0)
    assert record.step == 0
    assert record.role == "execution"
    assert record.family == "claude"
    assert record.attempt == 1
    assert record.outcome == "failed"
    assert record.error == "timeout"
    assert len(state.records) == 1
    assert state.attempts_in_step == 1


def test_escalation_state_next_step(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    assert state.current_role() == "execution"
    assert state.next_step()
    assert state.current_role() == "coordination"
    assert state.attempts_in_step == 0
    assert state.next_step()
    assert state.current_role() == "planning"
    assert not state.next_step()  # Can't escalate past planning


def test_escalation_state_cost_tracking(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    state.record_attempt("failed")
    assert state._get_cost_used_for_issue() > 0
    state.next_step()
    state.record_attempt("failed")
    cost = state._get_cost_used_for_issue()
    assert cost > 10  # At least execution + coordination costs


def test_escalation_state_ceiling_per_issue(temp_repo):
    state = escalation.EscalationState(
        temp_repo,
        issue=123,
        family="claude",
        cost_ceiling_per_issue=100,  # Low ceiling
    )
    # Exhaust the ceiling
    for _ in range(15):  # Execution costs ~10 per attempt
        state.record_attempt("failed")
    assert not state.can_escalate()
    assert not state.next_step()


def test_escalation_state_persistence(temp_repo):
    state1 = escalation.EscalationState(temp_repo, issue=123, family="claude")
    state1.record_attempt("failed", error="test error")
    state1.next_step()
    state1.record_attempt("failed", error="test error 2")

    # Load state in a new instance
    state2 = escalation.EscalationState(temp_repo, issue=123, family="claude")
    assert state2.current_step == 1
    assert state2.current_role() == "coordination"
    assert len(state2.records) == 2
    assert state2.records[0].error == "test error"
    assert state2.records[1].error == "test error 2"


def test_escalation_state_to_dict(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    state.record_attempt("failed")
    state.next_step()
    d = state.to_dict()
    assert d["issue"] == 123
    assert d["family"] == "claude"
    assert d["current_step"] == 1
    assert d["current_role"] == "coordination"
    assert d["cost_used_for_issue"] > 0
    assert len(d["records"]) == 1


def test_escalation_record_resolves_model_roles(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    record = state.record_attempt("ok")
    assert record.model == "claude-haiku-5-5"  # execution role
    assert record.effort == "high"
    state.next_step()
    record2 = state.record_attempt("ok")
    assert record2.model == "claude-sonnet-5-5"  # coordination role


def test_load_escalation_state(temp_repo):
    state = escalation.load_escalation_state(
        temp_repo,
        issue=456,
        family="codex",
        cost_ceiling_per_issue=500,
        cost_ceiling_per_day=2000,
    )
    assert state.issue == 456
    assert state.family == "codex"
    assert state.cost_ceiling_per_issue == 500
    assert state.cost_ceiling_per_day == 2000


def test_escalation_has_reached_end(temp_repo):
    state = escalation.EscalationState(temp_repo, issue=123, family="claude")
    assert not state.has_reached_end()
    state.current_step = 2
    assert state.has_reached_end()
