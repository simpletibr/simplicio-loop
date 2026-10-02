import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simplicio_loop.control_policy import (
    DEFAULT_WEIGHTS, PolicyWeights, classify_drift, compute_v, decide, group_candidates,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "control_policy")


def _load(name):
    with open(os.path.join(FIXTURES, f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


def _replay(name, **decide_kwargs):
    """Replay a frozen trace tick-by-tick, feeding prior ticks in as history."""
    fixture = _load(name)
    shared_candidates = fixture.get("candidates")
    ticks = fixture["ticks"]
    history = []
    decisions = []
    for tick in ticks:
        projection = dict(tick)
        if shared_candidates is not None and "candidates" not in projection:
            projection["candidates"] = shared_candidates
        projection["history"] = list(history)
        decisions.append(decide(projection, **decide_kwargs))
        history.append(dict(tick))
    return decisions


# -- compute_v / determinism -------------------------------------------------

def test_compute_v_is_a_weighted_sum():
    projection = {"acs_open": 2, "verifiers_failed": 1, "effects_unverified": 1, "backlog": 4, "retry_amplification": 2.0}
    weights = PolicyWeights(a=1.0, b=1.0, c=1.0, d=0.25, e=1.0)
    assert compute_v(projection, weights) == 2 + 1 + 1 + 1.0 + 2.0


def test_decide_is_deterministic_for_identical_input():
    projection = {"acs_open": 1, "verifiers_failed": 0, "effects_unverified": 0, "backlog": 0,
                  "retry_amplification": 0.0, "history": [], "candidates": []}
    first = json.dumps(decide(projection), sort_keys=True)
    second = json.dumps(decide(projection), sort_keys=True)
    assert first == second


def test_decide_never_mutates_or_touches_a_file(tmp_path, monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("control_policy.decide must never open a file")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.open", _forbidden)
    projection = {"acs_open": 1, "verifiers_failed": 0, "effects_unverified": 0, "backlog": 0,
                  "retry_amplification": 0.0, "history": []}
    result = decide(projection)
    assert result["decision"] in {"CONTINUE_SERIAL", "CONTINUE_PARALLEL"}


# -- hard constraints always win -------------------------------------------

def test_unsafe_constraint_stops_regardless_of_drift():
    projection = {"acs_open": 5, "hard_constraints": {"safe": False}}
    result = decide(projection)
    assert result["decision"] == "STOP_UNSAFE"
    assert result["reason_code"] == "hard_constraint_violation"


def test_budget_exhaustion_stops_regardless_of_drift():
    projection = {"acs_open": 5, "hard_constraints": {"within_budget": False}}
    result = decide(projection)
    assert result["decision"] == "STOP_BUDGET"
    assert result["reason_code"] == "budget_exhausted"


def test_maintenance_deferred_backlog_only_stops_as_blocked():
    projection = {
        "acs_open": 5,
        "maintenance": {"mode": "maintenance_deferred", "disposition": "backlog_only"},
    }
    result = decide(projection)
    assert result["decision"] == "STOP_BLOCKED"
    assert result["reason_code"] == "maintenance_deferred"


def test_all_clear_stops_success():
    projection = {"acs_open": 0, "verifiers_failed": 0, "effects_unverified": 0}
    result = decide(projection)
    assert result["decision"] == "STOP_SUCCESS"
    assert result["reason_code"] == "verified"


def test_recoverable_blocker_continues_before_blocked_handoff():
    result = decide({
        "acs_open": 1, "blocked": True, "blocker_type": "operator_failure",
        "recovery_attempts": 0,
    })
    assert result["decision"] == "CONTINUE_SERIAL"
    assert result["reason_code"] == "recovery_pending"
    assert result["recovery"]["action"] == "capability_check"


def test_exhausted_recoverable_blocker_remains_explicitly_blocked():
    result = decide({
        "acs_open": 1, "blocked": True, "blocker_type": "operator_failure",
        "recovery_attempts": 2,
    })
    assert result["decision"] == "STOP_BLOCKED"
    assert result["reason_code"] == "operator_failure_recovery_exhausted"


# -- hysteresis: one bad tick must not flip strategy -------------------------

def test_single_stall_tick_under_cooldown_observes_instead_of_replanning():
    history = [{"acs_open": 2, "state_signature": "x"}]
    projection = {"acs_open": 2, "state_signature": "x", "history": history}
    result = decide(projection, stall_threshold=2, cooldown=3)
    assert result["decision"] == "OBSERVE_WAIT"
    assert result["reason_code"] == "hysteresis_hold"


def test_stall_past_cooldown_replans():
    history = [{"acs_open": 2, "state_signature": "x"}, {"acs_open": 2, "state_signature": "x"}]
    projection = {"acs_open": 2, "state_signature": "x", "history": history}
    result = decide(projection, stall_threshold=2, cooldown=2)
    assert result["decision"] == "REPLAN"
    assert result["reason_code"] == "stall_escalation"


# -- backpressure grouping ----------------------------------------------------

def test_group_candidates_serializes_conflicting_writers():
    candidates = [
        {"id": "a", "reads": [], "writes": ["shared"]},
        {"id": "b", "reads": [], "writes": ["shared"]},
    ]
    grouping = group_candidates(candidates, prior_group_size=4)
    assert grouping["serial"] is True
    assert sorted(g[0] for g in grouping["groups"]) == ["a", "b"]


def test_group_candidates_parallelizes_disjoint_writers():
    candidates = [
        {"id": "a", "reads": [], "writes": ["fileA"]},
        {"id": "b", "reads": [], "writes": ["fileB"]},
    ]
    grouping = group_candidates(candidates, prior_group_size=1)
    assert grouping["serial"] is False
    assert grouping["recommended_concurrency"] >= 2


def test_rising_capacity_signal_forces_group_size_to_one():
    candidates = [
        {"id": "a", "reads": [], "writes": ["fileA"]},
        {"id": "b", "reads": [], "writes": ["fileB"]},
    ]
    grouping = group_candidates(candidates, {"errors_rising": True}, prior_group_size=4)
    assert grouping["recommended_concurrency"] == 1
    assert grouping["serial"] is True


# -- frozen traces (issue #261 Step 0 baseline) ------------------------------

def test_success_trace_drifts_negative_and_stops_success():
    decisions = _replay("success")
    assert decisions[-1]["decision"] == "STOP_SUCCESS"
    assert all(d["delta_v"] <= 0 for d in decisions)


def test_flaky_test_trace_recovers_without_escalating():
    decisions = _replay("flaky_test")
    assert decisions[-1]["decision"] == "STOP_SUCCESS"
    assert all(d["decision"] not in {"ESCALATE", "REPLAN"} for d in decisions)


def test_blocked_dependency_trace_reaches_explicit_blocked_state():
    decisions = _replay("blocked_dependency")
    assert decisions[-1]["decision"] == "STOP_BLOCKED"
    assert decisions[-1]["reason_code"] == "upstream_service_unavailable"


def test_duplicate_effect_trace_never_claims_success():
    decisions = _replay("duplicate_effect")
    assert all(d["decision"] != "STOP_SUCCESS" for d in decisions)


def test_overload_trace_shrinks_recommended_concurrency():
    decisions = _replay("overload")
    calm, overloaded = decisions
    assert calm["recommended_concurrency"] >= overloaded["recommended_concurrency"]
    assert overloaded["recommended_concurrency"] == 1


def test_oscillation_trace_escalates_within_cooldown():
    decisions = _replay("oscillation")
    assert any(d["decision"] == "ESCALATE" and d["reason_code"] == "oscillation_detected" for d in decisions)
    escalate_index = next(i for i, d in enumerate(decisions) if d["decision"] == "ESCALATE")
    assert escalate_index <= 3
