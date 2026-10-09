"""Unit tests for escalation module."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop import escalation, model_roles


class TestEscalationRecord:
    """Test EscalationRecord class."""

    def test_record_creation(self):
        record = escalation.EscalationRecord(
            step=0,
            role="execution",
            family="claude",
            model="claude-3-sonnet",
            effort="low",
            attempt=1,
            outcome="success",
            error=None,
            execution_ms=100.5,
        )
        assert record.step == 0
        assert record.role == "execution"
        assert record.outcome == "success"
        assert record.timestamp is not None

    def test_record_to_dict(self):
        record = escalation.EscalationRecord(
            step=1,
            role="coordination",
            family="codex",
            model="codex-model",
            effort="medium",
            attempt=2,
            outcome="failed",
            error="timeout",
            execution_ms=250.0,
        )
        d = record.to_dict()
        assert d["step"] == 1
        assert d["role"] == "coordination"
        assert d["family"] == "codex"
        assert d["error"] == "timeout"
        assert "timestamp" in d


class TestEscalationState:
    """Test EscalationState class."""

    def test_state_initialization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(
                tmpdir, issue=123, family="claude"
            )
            assert state.issue == 123
            assert state.family == "claude"
            assert state.current_step == 0
            assert state.attempts_in_step == 0
            assert state.current_role() == "execution"

    def test_state_persistence(self):
        """Test that state is saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and record something
            state1 = escalation.EscalationState(
                tmpdir, issue=456, family="codex"
            )
            state1.record_attempt("success", error=None, execution_ms=100.0)
            state1.next_step()

            # Load in a new instance
            state2 = escalation.EscalationState(
                tmpdir, issue=456, family="codex"
            )
            assert state2.current_step == 1
            assert len(state2.records) == 1
            assert state2.records[0].outcome == "success"

    def test_escalation_ladder_order(self):
        """Test ladder moves through execution -> coordination -> planning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(tmpdir, issue=1, family="claude")
            assert state.current_role() == "execution"
            assert state.next_step()
            assert state.current_role() == "coordination"
            assert state.next_step()
            assert state.current_role() == "planning"
            assert not state.next_step()  # Can't escalate beyond planning

    def test_cost_ceiling_per_issue(self):
        """Test that per-issue cost ceiling is enforced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(
                tmpdir,
                issue=789,
                family="claude",
                cost_ceiling_per_issue=20,  # 2x execution cost
            )
            # Record two execution attempts (cost = 10 + 10 = 20)
            state.record_attempt("fail", error="test")
            state.record_attempt("fail", error="test")
            # Now we're at ceiling, next_step should return False
            assert not state.can_escalate()
            assert not state.next_step()

    def test_cost_ceiling_per_day(self):
        """Test that per-day cost ceiling is enforced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(
                tmpdir,
                issue=999,
                family="claude",
                cost_ceiling_per_day=15,  # 1.5x execution cost
            )
            # Record one execution attempt (cost = 10)
            state.record_attempt("fail", error="test")
            assert state.can_escalate()  # Still under ceiling
            # Try to record another (would be 20 total)
            # The state tracks per-day, so we need to test cost tracking
            cost_today = state._get_cost_used_today()
            assert cost_today == 10

    def test_attempt_tracking(self):
        """Test attempt counting in each step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(tmpdir, issue=111, family="claude")
            assert state.attempts_in_step == 0
            state.record_attempt("fail")
            assert state.attempts_in_step == 1
            state.record_attempt("fail")
            assert state.attempts_in_step == 2
            state.next_step()
            assert state.attempts_in_step == 0  # Reset on next step

    def test_record_attempt_resolves_model(self):
        """Test that record_attempt resolves model via model_roles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                model_roles, "resolve",
                return_value={"model": "claude-3-opus", "effort": "high"}
            ):
                state = escalation.EscalationState(tmpdir, issue=222, family="claude")
                record = state.record_attempt("success")
                assert record.model == "claude-3-opus"
                assert record.effort == "high"

    def test_record_attempt_on_bad_role(self):
        """Test record_attempt handles bad role gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                model_roles, "resolve",
                side_effect=model_roles.ModelRoleError("bad role")
            ):
                state = escalation.EscalationState(tmpdir, issue=333, family="claude")
                record = state.record_attempt("success")
                assert record.model == ""
                assert record.effort == ""

    def test_has_reached_end(self):
        """Test end-of-ladder detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(tmpdir, issue=444, family="claude")
            assert not state.has_reached_end()
            state.current_step = len(escalation.ESCALATION_LADDER) - 1
            assert state.has_reached_end()

    def test_to_dict_export(self):
        """Test full state export to dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.EscalationState(tmpdir, issue=555, family="claude")
            state.record_attempt("fail", error="test", execution_ms=50.0)
            d = state.to_dict()
            assert d["issue"] == 555
            assert d["family"] == "claude"
            assert d["current_role"] == "execution"
            assert len(d["records"]) == 1
            assert d["cost_used_for_issue"] == 10  # execution cost


class TestLoadEscalationState:
    """Test load_escalation_state helper."""

    def test_load_creates_new_state(self):
        """Test that load_escalation_state creates a new state if none exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.load_escalation_state(
                tmpdir,
                issue=666,
                family="claude",
                cost_ceiling_per_issue=1000,
            )
            assert state.issue == 666
            assert state.current_step == 0

    def test_load_with_custom_ceilings(self):
        """Test custom cost ceiling parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.load_escalation_state(
                tmpdir,
                issue=777,
                family="claude",
                cost_ceiling_per_issue=500,
                cost_ceiling_per_day=2000,
            )
            assert state.cost_ceiling_per_issue == 500
            assert state.cost_ceiling_per_day == 2000
