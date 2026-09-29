"""Unit coverage for edge/validation branches of simplicio_loop.flow_semantics that the existing
happy-path tests (test_flow_semantics.py) don't reach: malformed inputs, invalid limits, the
attempt-cap escalation, and evaluate_drain's mapping-shaped `blocked` and dict-item quarantine
paths.
"""
from simplicio_loop.flow_semantics import evaluate_converge, evaluate_drain


def test_evaluate_converge_rejects_invalid_limits():
    result = evaluate_converge([], max_attempts=0)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "limits_invalid"

    result = evaluate_converge([], stall_threshold=0)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "limits_invalid"


def test_evaluate_converge_rejects_non_mapping_attempt_rows():
    result = evaluate_converge([{"verified": False}, "not-a-mapping"])
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "attempt_invalid"


def test_evaluate_converge_completes_when_latest_attempt_is_verified():
    attempts = [{"verified": False}, {"verified": True}]
    result = evaluate_converge(attempts, max_attempts=10)
    assert result["status"] == "COMPLETE"
    assert result["reason_code"] == "verified"
    assert result["strategy_changed"] is False


def test_evaluate_converge_escalates_at_attempt_cap():
    attempts = [{"verified": False}, {"verified": False}, {"verified": False}]
    result = evaluate_converge(attempts, max_attempts=3)
    assert result["status"] == "ESCALATE"
    assert result["reason_code"] == "attempt_cap"


def test_evaluate_converge_fingerprint_repeat_breaks_on_first_mismatch():
    # Latest fingerprint differs from the one before it: repeat_count stays 1 (break at line 58).
    attempts = [
        {"verified": False, "failure_fingerprint": "fp-old"},
        {"verified": False, "failure_fingerprint": "fp-new"},
    ]
    result = evaluate_converge(attempts, max_attempts=10, stall_threshold=10)
    assert result["failure_fingerprint"] == "fp-new"
    assert result["repeat_count"] == 1


def test_items_with_mapping_uses_keys():
    from simplicio_loop.flow_semantics import _items
    assert _items({"b": 1, "a": 2}) == ["a", "b"]


def test_items_with_none_returns_empty():
    from simplicio_loop.flow_semantics import _items
    assert _items(None) == []


def test_items_with_plain_string_returns_single_item():
    from simplicio_loop.flow_semantics import _items
    assert _items("solo") == ["solo"]


def test_evaluate_drain_rejects_non_sequence_rounds():
    result = evaluate_drain("nope")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "rounds_invalid"


def test_evaluate_drain_rejects_non_mapping_round_rows():
    result = evaluate_drain([{"ready": []}, "bad-row"])
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "round_invalid"


def test_evaluate_drain_blocked_as_single_mapping_is_wrapped_in_list():
    result = evaluate_drain([
        {"ready": [], "active": [], "blocked": {"id": "wi-1", "reason": "cycle"}},
    ], k=1)
    assert any(q["id"] == "wi-1" and q["reason"] == "cycle" for q in result["quarantined"])


def test_evaluate_drain_blocked_dict_items_capture_dead_ends():
    result = evaluate_drain([
        {"ready": [], "active": [],
         "blocked": [{"id": "wi-2", "reason": "dep_missing", "dead_ends": ["wi-9"]}]},
    ], k=1)
    quarantined = result["quarantined"]
    assert quarantined == [{"id": "wi-2", "reason": "dep_missing", "dead_ends": ["wi-9"]}]


def test_evaluate_drain_blocked_scalar_items_default_reason():
    result = evaluate_drain([
        {"ready": [], "active": [], "blocked": ["wi-3"]},
    ], k=1)
    assert result["quarantined"] == [{"id": "wi-3", "reason": "blocked", "dead_ends": []}]
