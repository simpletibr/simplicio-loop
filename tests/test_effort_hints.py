"""Unit tests for per-phase reasoning-effort hints (issue #1310 follow-up).

The loop never calls an LLM itself -- the host does. `simplicio_loop.effort`
is the single source of truth for the phase->effort mapping, consumed by
both `orient --brief` (plan-phase hint for the NEXT turn) and
`simplicio-loop apply`'s result JSON (`next_effort` for the turn after
apply: review on PASS, a mechanical fix on BLOCKED/FAIL).
"""
from __future__ import annotations

from simplicio_loop.effort import PHASE_EFFORT, next_effort_for_status


def test_phase_effort_table_is_frozen_and_matches_the_user_request():
    assert PHASE_EFFORT == {"plan": "high", "execute": "low", "review": "medium"}


def test_next_effort_for_status_pass_is_review_effort():
    assert next_effort_for_status("PASS") == PHASE_EFFORT["review"]


def test_next_effort_for_status_blocked_is_execute_effort():
    assert next_effort_for_status("BLOCKED") == PHASE_EFFORT["execute"]


def test_next_effort_for_status_fail_is_execute_effort():
    assert next_effort_for_status("FAIL") == PHASE_EFFORT["execute"]


def test_next_effort_for_status_unknown_defaults_to_execute_effort():
    assert next_effort_for_status("WHATEVER") == PHASE_EFFORT["execute"]
