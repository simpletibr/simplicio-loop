from __future__ import annotations

import pytest

from simplicio_loop.prototype_gate import (
    DEFAULT_MAX_REVISE,
    PrototypeGateError,
    build_candidate,
    build_plan,
    init_state,
    stall_verdict,
)
from simplicio_loop.prototype_judge import (
    RuleBasedJudge,
    SelfJudgingError,
    assert_no_self_judging,
    judge_and_decide,
    judge_transition,
    measure_diversity,
    score_candidate,
)


def _plan(validators=("pytest -q", "ruff check"), **overrides):
    kwargs = dict(
        work_item_id="wi-judge",
        goal="choose the retry strategy",
        prototype_type="code_spike",
        source_sha="sha-1",
        level="P1",
        validators=list(validators),
    )
    kwargs.update(overrides)
    return build_plan(**kwargs)


def _candidate(plan, *, candidate_id, agent_id, strategy="direct",
               passed_validators=(), failed_validators=(),
               evidence_refs=(), assumptions=(), limitations=(), out_of_scope=()):
    validation_results = [
        {"validator": v, "passed": True} for v in passed_validators
    ] + [
        {"validator": v, "passed": False} for v in failed_validators
    ]
    return build_candidate(
        plan=plan,
        candidate_id=candidate_id,
        strategy=strategy,
        agent_id=agent_id,
        artifact_hash=f"hash-{candidate_id}",
        validation_results=validation_results,
        evidence_refs=list(evidence_refs),
        assumptions=list(assumptions),
        limitations=list(limitations),
        out_of_scope=list(out_of_scope),
    )


# --- self-judging hard block -------------------------------------------------------------------


def test_self_judging_is_hard_blocked():
    plan = _plan()
    candidates = [
        _candidate(plan, candidate_id="c1", agent_id="agent-a",
                   passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"]),
        _candidate(plan, candidate_id="c2", agent_id="agent-b",
                   passed_validators=("pytest -q",), evidence_refs=["ev-2"]),
    ]
    with pytest.raises(SelfJudgingError, match="self-judging blocked"):
        assert_no_self_judging(candidates, "agent-a")

    with pytest.raises(SelfJudgingError):
        judge_and_decide(plan, candidates, "agent-a")


def test_self_judging_blocks_whole_round_no_decision_emitted():
    plan = _plan()
    candidates = [
        _candidate(plan, candidate_id="c1", agent_id="agent-a",
                   passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"]),
        _candidate(plan, candidate_id="c2", agent_id="agent-b",
                   passed_validators=(), evidence_refs=[]),
    ]
    # agent-b did not create the winning candidate, but IS a creator in the
    # round -- self-judging blocks the WHOLE round regardless of who would win.
    with pytest.raises(SelfJudgingError):
        judge_and_decide(plan, candidates, "agent-b")


def test_independent_judge_identity_is_allowed():
    plan = _plan()
    candidates = [
        _candidate(plan, candidate_id="c1", agent_id="agent-a",
                   passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"]),
        _candidate(plan, candidate_id="c2", agent_id="agent-b",
                   passed_validators=("pytest -q",), evidence_refs=["ev-2"]),
    ]
    decision, report = judge_and_decide(plan, candidates, "judge-independent")
    assert decision["judge_id"] == "judge-independent"
    assert decision["judge_independent"] is True
    assert report["judge_id"] == "judge-independent"


# --- ACCEPT requires AC coverage + evidence + zero findings ------------------------------------


def test_accept_requires_full_coverage_evidence_and_zero_findings():
    plan = _plan()
    winner = _candidate(
        plan, candidate_id="winner", agent_id="agent-a",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    decision, report = judge_and_decide(plan, [winner], "judge-1")
    assert decision["decision"] == "ACCEPT"
    assert decision["candidate_hash"] == winner["candidate_hash"]
    assert report["verdicts"][0]["eligible_for_accept"] is True


def test_missing_evidence_gets_revise_not_accept():
    plan = _plan()
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=(),
    )
    decision, report = judge_and_decide(plan, [candidate], "judge-1")
    assert decision["decision"] != "ACCEPT"
    assert report["verdicts"][0]["eligible_for_accept"] is False


def test_unresolved_finding_gets_revise_not_accept():
    plan = _plan()
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q",), failed_validators=("ruff check",),
        evidence_refs=["ev-1"],
    )
    decision, report = judge_and_decide(plan, [candidate], "judge-1")
    assert decision["decision"] == "REVISE"
    assert report["verdicts"][0]["finding_count"] == 1
    assert report["verdicts"][0]["eligible_for_accept"] is False


def test_incomplete_ac_coverage_gets_revise_not_accept():
    plan = _plan()
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q",), evidence_refs=["ev-1"],
    )
    decision, report = judge_and_decide(plan, [candidate], "judge-1")
    assert decision["decision"] == "REVISE"
    assert report["verdicts"][0]["ac_coverage_ratio"] == 0.5


def test_totally_unviable_round_gets_reject_not_revise():
    plan = _plan()
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=(), evidence_refs=(),
    )
    decision, report = judge_and_decide(plan, [candidate], "judge-1")
    assert decision["decision"] == "REJECT"
    assert report["verdicts"][0]["ac_coverage_ratio"] == 0.0


def test_plan_with_no_validators_is_vacuously_covered():
    plan = _plan(validators=())
    candidate = _candidate(plan, candidate_id="c1", agent_id="agent-a", evidence_refs=["ev-1"])
    decision, report = judge_and_decide(plan, [candidate], "judge-1")
    assert decision["decision"] == "ACCEPT"
    assert report["verdicts"][0]["ac_coverage_ratio"] == 1.0


# --- diversity / tie-break ----------------------------------------------------------------------


def test_diversity_differentiates_identical_from_distinct_candidates():
    plan = _plan()
    identical_a = _candidate(
        plan, candidate_id="ia", agent_id="agent-a", strategy="retry-backoff",
        assumptions=["network flaky"], limitations=["no idempotency"],
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    identical_b = _candidate(
        plan, candidate_id="ib", agent_id="agent-b", strategy="retry-backoff",
        assumptions=["network flaky"], limitations=["no idempotency"],
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-2"],
    )
    identical_round = measure_diversity([identical_a, identical_b])
    assert identical_round["ia"] == pytest.approx(0.0)
    assert identical_round["ib"] == pytest.approx(0.0)

    distinct_a = _candidate(
        plan, candidate_id="da", agent_id="agent-a", strategy="retry-backoff",
        assumptions=["network flaky"], limitations=["no idempotency"],
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    distinct_b = _candidate(
        plan, candidate_id="db", agent_id="agent-b", strategy="circuit-breaker",
        assumptions=["dependency unreliable"], limitations=["adds latency"],
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-2"],
    )
    distinct_round = measure_diversity([distinct_a, distinct_b])
    assert distinct_round["da"] > identical_round["ia"]
    assert distinct_round["db"] > identical_round["ib"]


def test_score_candidate_reflects_diversity_component():
    plan = _plan()
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    low = score_candidate(plan, candidate, diversity_score=0.0)
    high = score_candidate(plan, candidate, diversity_score=1.0)
    assert high["score"] > low["score"]
    assert high["eligible_for_accept"] is low["eligible_for_accept"] is True


def test_tie_break_is_deterministic_by_candidate_id():
    plan = _plan()
    a = _candidate(
        plan, candidate_id="alpha", agent_id="agent-a", strategy="same",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    b = _candidate(
        plan, candidate_id="beta", agent_id="agent-b", strategy="same",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-2"],
    )
    _decision, report = judge_and_decide(plan, [a, b], "judge-1")
    verdicts = report["verdicts"]
    assert verdicts[0]["score"] == pytest.approx(verdicts[1]["score"])
    assert verdicts[0]["candidate_id"] == "alpha"  # alphabetically first wins the tie


# --- wiring into the state machine ---------------------------------------------------------------


def test_judge_transition_drives_accept_through_apply_decision():
    plan = _plan(level="P0")
    winner = _candidate(
        plan, candidate_id="winner", agent_id="agent-a",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    state = init_state(work_item_id="wi-judge", plan=plan)
    new_state, decision, report = judge_transition(state, plan, [winner], "judge-1")
    assert decision["decision"] == "ACCEPT"
    assert new_state["current_level"] == "P1"
    assert new_state["status"] == "in_progress"
    assert new_state["history"][-1]["decision"] == "ACCEPT"
    assert report["verdicts"][0]["candidate_id"] == "winner"


def test_judge_transition_drives_revise_and_is_bounded_like_manual_revise():
    plan = _plan(level="P0")
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q",), evidence_refs=["ev-1"],
    )
    state = init_state(work_item_id="wi-judge-revise", plan=plan)
    for _ in range(DEFAULT_MAX_REVISE):
        state, decision, _report = judge_transition(state, plan, [candidate], "judge-1")
        assert decision["decision"] == "REVISE"
        assert state["status"] == "in_progress"
    state, decision, _report = judge_transition(state, plan, [candidate], "judge-1")
    assert decision["decision"] == "REVISE"
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "revise_iterations_exceeded"


def test_stall_verdict_still_works_after_judge_driven_transitions():
    plan = _plan(level="P0")
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q",), evidence_refs=["ev-1"],
    )
    state = init_state(work_item_id="wi-judge-stall", plan=plan)
    for _ in range(3):
        state, _decision, _report = judge_transition(state, plan, [candidate], "judge-1")
    verdict = stall_verdict(state, k=3)
    # the SAME candidate round judged the SAME way three times in a row is a
    # real stall -- reusing loop_journal's stall detector, not reinventing it.
    assert verdict["verdict"] == "STALLED"


def test_judge_transition_self_judging_blocks_before_touching_state():
    plan = _plan(level="P0")
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )
    state = init_state(work_item_id="wi-judge-self", plan=plan)
    with pytest.raises(SelfJudgingError):
        judge_transition(state, plan, [candidate], "agent-a")


def test_judge_requires_at_least_one_candidate():
    plan = _plan()
    with pytest.raises(PrototypeGateError, match="at least 1 candidate"):
        RuleBasedJudge().judge(plan, [], "judge-1")


def test_custom_judge_can_be_plugged_in_via_keyword():
    plan = _plan()
    candidate = _candidate(
        plan, candidate_id="c1", agent_id="agent-a",
        passed_validators=("pytest -q", "ruff check"), evidence_refs=["ev-1"],
    )

    calls = []

    class RecordingJudge:
        def judge(self, plan, candidates, judge_identity):
            calls.append(judge_identity)
            return RuleBasedJudge().judge(plan, candidates, judge_identity)

    decision, _report = judge_and_decide(plan, [candidate], "judge-2", judge=RecordingJudge())
    assert calls == ["judge-2"]
    assert decision["decision"] == "ACCEPT"
