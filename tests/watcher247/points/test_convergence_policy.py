"""convergence_policy (verify): RunProjection -> LoopDecision from the attempt history and the verify outcome."""
import pytest

from simplicio_loop import escalation
from simplicio_loop.watcher247 import convergence, points

PASSED = "MEASURED|verify_passed: `python3 -m pytest -q`"
FAILED = "MEASURED|verify_failed: `python3 -m pytest -q`"
ISSUE = {"number": 7}


def _attempts(clone, outcomes):
    ladder = escalation.load_escalation_state(clone, 7, "claude")
    for outcome in outcomes:
        ladder.record_attempt(outcome)


def test_registered_at_verify_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "convergence_policy"]
    assert (info.stage, info.blocking, info.conditional) == ("verify", False, True)


def test_without_a_clone_or_an_issue_it_is_skipped(make_ctx, tmp_path):
    from simplicio_loop.watcher247.points.convergence_policy import applies  # the point's own module
    assert not applies(make_ctx(issue=ISSUE))
    assert not applies(make_ctx(clone=tmp_path))
    assert applies(make_ctx(clone=tmp_path, issue=ISSUE))


def test_passed_verify_continues_to_the_pr(point_contract, make_ctx, tmp_path):
    _attempts(tmp_path, ["ok"])
    result = point_contract("convergence_policy", make_ctx(clone=tmp_path, issue=ISSUE, verify=PASSED), expect="ok")
    assert result.evidence["decision"] == "STOP_SUCCESS"
    assert result.evidence["action"] == "continue"
    assert result.evidence["attempts"] == 1


def test_unverified_without_history_continues(point_contract, make_ctx, tmp_path):
    result = point_contract("convergence_policy",
                            make_ctx(clone=tmp_path, issue=ISSUE, verify="UNVERIFIED|no_test_command"), expect="ok")
    assert result.evidence["action"] == "continue"


def test_failed_verify_with_budget_left_is_a_retry(point_contract, make_ctx, tmp_path):
    _attempts(tmp_path, ["failed"])
    result = point_contract("convergence_policy", make_ctx(clone=tmp_path, issue=ISSUE, verify=FAILED), expect="ok")
    assert result.evidence["action"] == "retry"
    assert result.evidence["failed_attempts"] == 1


def test_a_plateau_of_failures_is_a_replan_retry(point_contract, make_ctx, tmp_path):
    _attempts(tmp_path, ["failed"] * 3)
    result = point_contract("convergence_policy", make_ctx(clone=tmp_path, issue=ISSUE, verify=FAILED), expect="ok")
    assert result.evidence["decision"] == "REPLAN"
    assert result.evidence["action"] == "retry"


def test_exhausted_attempts_stop_and_block(point_contract, make_ctx, tmp_path):
    _attempts(tmp_path, ["failed"] * escalation.ATTEMPT_CEILING_PER_ISSUE)
    result = point_contract("convergence_policy", make_ctx(clone=tmp_path, issue=ISSUE, verify=FAILED),
                            expect="blocked")
    assert result.reason_code == "budget_exhausted"
    assert result.evidence["decision"] == "STOP_BUDGET"
    assert result.evidence["action"] == "stop"


def test_a_passed_verify_is_not_blocked_by_past_failures(point_contract, make_ctx, tmp_path):
    _attempts(tmp_path, ["failed"] * escalation.ATTEMPT_CEILING_PER_ISSUE + ["ok"])
    result = point_contract("convergence_policy", make_ctx(clone=tmp_path, issue=ISSUE, verify=PASSED), expect="ok")
    assert result.evidence["action"] == "continue"


@pytest.mark.parametrize("decision, action", [
    ("CONTINUE_SERIAL", "continue"), ("CONTINUE_PARALLEL", "continue"), ("OBSERVE_WAIT", "continue"),
    ("STOP_SUCCESS", "continue"), ("REPLAN", "retry"), ("ESCALATE", "escalate"), ("STOP_BLOCKED", "stop"),
    ("STOP_BUDGET", "stop"), ("STOP_UNSAFE", "stop")])
def test_every_loop_decision_maps_to_an_action(decision, action):
    assert convergence.action_for(decision, verifier_failed=False) == action


def test_a_failed_verifier_never_continues():
    assert convergence.action_for("CONTINUE_SERIAL", verifier_failed=True) == "retry"


def test_assess_is_what_the_failed_verify_path_consumes(tmp_path):
    """host_mode.run_exec calls assess on its own ladder after a failed attempt: same decision, no point run."""
    ladder = escalation.load_escalation_state(tmp_path, 7, "claude")
    ladder.record_attempt("failed")
    verdict = convergence.assess(ladder, failed=True)
    assert (verdict["action"], verdict["attempts"], verdict["failed_attempts"]) == ("retry", 1, 1)
    for _ in range(escalation.ATTEMPT_CEILING_PER_ISSUE):
        ladder.record_attempt("failed")
    verdict = convergence.assess(ladder, failed=True)
    assert (verdict["action"], verdict["reason"]) == ("stop", "budget_exhausted")
