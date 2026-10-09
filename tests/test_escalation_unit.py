"""Unit tests for escalation module."""

import tempfile
from unittest import mock


from simplicio_loop import escalation, model_roles
from simplicio_loop.execution_report import SCHEMA as EXECUTION_REPORT_SCHEMA


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
            assert d["tokens_used_for_issue"] == 0  # no report, so no measured tokens
            assert d["unverified_attempts_for_issue"] == 1


class TestLoadEscalationState:
    """Test load_escalation_state helper."""

    def test_load_creates_new_state(self):
        """Test that load_escalation_state creates a new state if none exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.load_escalation_state(
                tmpdir,
                issue=666,
                family="claude",
                token_ceiling_per_issue=1000,
            )
            assert state.issue == 666
            assert state.current_step == 0

    def test_load_with_custom_ceilings(self):
        """Test custom token ceiling parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = escalation.load_escalation_state(
                tmpdir,
                issue=777,
                family="claude",
                token_ceiling_per_issue=500,
                token_ceiling_per_day=2000,
            )
            assert state.token_ceiling_per_issue == 500
            assert state.token_ceiling_per_day == 2000


def _report(*task_tokens):
    """An execution report with one task per entry: an int is MEASURED tokens, None is absent (UNVERIFIED)."""
    tasks = []
    for total in task_tokens:
        if total is None:
            tokens = {"tokens_total": None, "source": "absent"}
        else:
            tokens = {"tokens_in": total, "tokens_out": 0, "tokens_total": total, "source": "cli_measured"}
        tasks.append({"tokens": tokens, "outcome": "FAIL"})
    return {"schema": EXECUTION_REPORT_SCHEMA, "tasks": tasks}


class TestMeasuredTokens:
    def test_sums_measured_tasks(self):
        assert escalation.measured_tokens(_report(300, 200)) == 500

    def test_any_absent_task_makes_the_attempt_unverified(self):
        assert escalation.measured_tokens(_report(300, None)) is None

    def test_absent_is_not_zero(self):
        assert escalation.measured_tokens(_report(None)) is None

    def test_wrong_schema_or_no_tasks_is_unverified(self):
        other = {"schema": "other", "tasks": [{"tokens": {"tokens_total": 5, "source": "cli_measured"}}]}
        assert escalation.measured_tokens(other) is None
        assert escalation.measured_tokens({"schema": EXECUTION_REPORT_SCHEMA, "tasks": []}) is None
        assert escalation.measured_tokens(None) is None


class TestMeasuredCostCeilings:
    def test_record_keeps_measured_tokens_from_the_report(self, tmp_path):
        state = escalation.EscalationState(tmp_path, issue=1, family="claude")
        assert state.record_attempt("fail", report=_report(1200)).tokens == 1200

    def test_record_without_report_is_unverified_not_zero(self, tmp_path):
        state = escalation.EscalationState(tmp_path, issue=2, family="claude")
        assert state.record_attempt("fail").tokens is None
        d = state.to_dict()
        assert d["tokens_used_for_issue"] == 0
        assert d["unverified_attempts_for_issue"] == 1

    def test_token_ceiling_per_issue_uses_measured_tokens(self, tmp_path):
        state = escalation.EscalationState(tmp_path, issue=3, family="claude", token_ceiling_per_issue=1000)
        state.record_attempt("fail", report=_report(600))
        assert state.can_escalate()
        state.record_attempt("fail", report=_report(600))
        assert not state.can_escalate()

    def test_token_ceiling_per_day_uses_measured_tokens(self, tmp_path):
        state = escalation.EscalationState(tmp_path, issue=4, family="claude", token_ceiling_per_day=500)
        state.record_attempt("fail", report=_report(500))
        assert not state.can_escalate()

    def test_unverified_attempts_are_not_zero_and_hit_the_attempt_ceiling(self, tmp_path):
        state = escalation.EscalationState(
            tmp_path, issue=5, family="claude", token_ceiling_per_issue=100, attempt_ceiling_per_issue=2
        )
        state.record_attempt("fail", report=_report(50))
        assert state.can_escalate()  # 50 < 100 measured, one attempt, no unverified attempt yet
        state.record_attempt("fail")  # unverified: attempt ceiling now applies
        assert not state.can_escalate()

    def test_attempt_ceiling_not_applied_when_all_attempts_are_measured(self, tmp_path):
        state = escalation.EscalationState(tmp_path, issue=6, family="claude", attempt_ceiling_per_issue=2)
        state.record_attempt("fail", report=_report(10))
        state.record_attempt("fail", report=_report(10))
        assert state.can_escalate()

    def test_fixed_cost_table_is_gone(self, tmp_path):
        state = escalation.EscalationState(tmp_path, issue=7, family="claude")
        assert not hasattr(state, "_cost_per_role")
