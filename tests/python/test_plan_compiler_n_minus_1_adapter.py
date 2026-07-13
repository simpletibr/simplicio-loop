"""Tests for the N-1 compat adapter (issue #167 slice 11/23).

Fixtures under ``tests/fixtures/plan_compiler/n_minus_1/`` are genuine
N-1-shaped payloads: a ``GoalEnvelope`` without ``producer_id``/
``consumer_id`` (pre-#171 shape) and two ``PlanDAG`` dicts with
``producer_id``/``consumer_id`` (post-#171) but no ``budget`` (pre-budget
slice) — exactly the N-1 boundary ``compat_adapter`` documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio.plan_compiler import GoalEnvelope, PlanDAG, PlanNode
from simplicio.plan_compiler.compat_adapter import (
    GOAL_ENVELOPE_VERSION,
    PLAN_DAG_VERSION,
    CompatAdapterExpiredError,
    UnsupportedCompatVersionError,
    adapt_goal_envelope_inbound,
    adapt_goal_envelope_outbound,
    adapt_inbound,
    adapt_outbound,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "plan_compiler" / "n_minus_1"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _current_plan() -> PlanDAG:
    return PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[
            PlanNode(node_id="n1", capability="edit.apply", acceptance_criteria_refs=["AC1"]),
            PlanNode(node_id="n2", capability="test.run", depends_on=["n1"]),
        ],
        producer_id="simplicio-runtime",
        consumer_id="simplicio-loop",
        budget=100.0,
    )


def _current_goal() -> GoalEnvelope:
    return GoalEnvelope(
        goal_id="goal-1",
        revision="1",
        context_snapshot_id="snap-1",
        text="Do the thing.",
        acceptance_criteria=["AC1"],
        producer_id="simplicio-runtime",
        consumer_id="simplicio-loop",
    )


# --- GoalEnvelope fixtures / round-trip --------------------------------------


def test_goal_envelope_fixture_is_n_minus_1_shaped() -> None:
    payload = _load_fixture("goal_envelope_n_minus_1.json")
    assert "producer_id" not in payload
    assert "consumer_id" not in payload


def test_goal_envelope_adapt_inbound_fills_defaults_from_fixture() -> None:
    payload = _load_fixture("goal_envelope_n_minus_1.json")
    goal = adapt_goal_envelope_inbound(payload, GOAL_ENVELOPE_VERSION - 1)
    assert goal.goal_id == "goal-fixture-1"
    assert goal.producer_id == ""
    assert goal.consumer_id == ""


def test_goal_envelope_round_trip_outbound_then_inbound() -> None:
    goal = _current_goal()
    downgraded = adapt_goal_envelope_outbound(goal, GOAL_ENVELOPE_VERSION - 1)
    assert "producer_id" not in downgraded
    assert "consumer_id" not in downgraded

    upgraded = adapt_goal_envelope_inbound(downgraded, GOAL_ENVELOPE_VERSION - 1)
    # Fields known at N-1 survive the round trip unchanged.
    assert upgraded.goal_id == goal.goal_id
    assert upgraded.text == goal.text
    assert upgraded.acceptance_criteria == goal.acceptance_criteria
    # Fields unknown at N-1 fall back to the dataclass default, not the
    # original value — this is the expected, documented lossy edge.
    assert upgraded.producer_id == ""
    assert upgraded.consumer_id == ""


def test_goal_envelope_adapt_outbound_rejects_older_than_n_minus_1() -> None:
    goal = _current_goal()
    with pytest.raises(UnsupportedCompatVersionError):
        adapt_goal_envelope_outbound(goal, GOAL_ENVELOPE_VERSION - 2)


# --- PlanDAG fixtures / round-trip --------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    ["plan_dag_n_minus_1_simple.json", "plan_dag_n_minus_1_no_ids.json"],
)
def test_plan_dag_fixture_is_n_minus_1_shaped(fixture_name: str) -> None:
    payload = _load_fixture(fixture_name)
    assert "budget" not in payload


@pytest.mark.parametrize(
    "fixture_name",
    ["plan_dag_n_minus_1_simple.json", "plan_dag_n_minus_1_no_ids.json"],
)
def test_plan_dag_adapt_inbound_from_fixture(fixture_name: str) -> None:
    payload = _load_fixture(fixture_name)
    plan = adapt_inbound(payload, PLAN_DAG_VERSION - 1)
    assert plan.budget is None
    assert plan.plan_id == payload["plan_id"]
    # Validates cleanly: fixtures are genuine, well-formed N-1 payloads.
    plan.validate()


def test_plan_dag_round_trip_outbound_then_inbound_preserves_n_minus_1_fields() -> None:
    plan = _current_plan()
    downgraded = adapt_outbound(plan, PLAN_DAG_VERSION - 1)
    assert "budget" not in downgraded
    assert downgraded["producer_id"] == plan.producer_id
    assert downgraded["consumer_id"] == plan.consumer_id

    upgraded = adapt_inbound(downgraded, PLAN_DAG_VERSION - 1)
    assert upgraded.plan_id == plan.plan_id
    assert upgraded.goal_id == plan.goal_id
    assert upgraded.producer_id == plan.producer_id
    assert upgraded.consumer_id == plan.consumer_id
    assert [node.node_id for node in upgraded.nodes] == [node.node_id for node in plan.nodes]
    # budget is the one field N-1 never carried: it comes back as the
    # documented default, not the original value.
    assert upgraded.budget is None


def test_plan_dag_rollback_scenario_n_only_fields_do_not_survive_n_minus_1_hop() -> None:
    """Rollback scenario: produce at N, adapt down to N-1, confirm an N-1-only
    consumer path round-trips without data loss for the fields it knows
    about (producer_id/consumer_id/nodes/ids) while budget - unknown at
    N-1 - is dropped rather than corrupting the payload.
    """
    plan = _current_plan()
    n_minus_1_payload = adapt_outbound(plan, PLAN_DAG_VERSION - 1)

    # An N-1-only consumer sees a plain dict with no budget key at all.
    assert set(n_minus_1_payload) == {
        "schema",
        "plan_id",
        "goal_id",
        "context_snapshot_id",
        "revision",
        "nodes",
        "producer_id",
        "consumer_id",
    }

    # Rolling back into this compiler's own current PlanDAG still works and
    # preserves every field the N-1 contract carries.
    restored = adapt_inbound(n_minus_1_payload, PLAN_DAG_VERSION - 1)
    assert restored.to_dict()["nodes"] == plan.to_dict()["nodes"]
    assert restored.producer_id == plan.producer_id
    assert restored.consumer_id == plan.consumer_id
    assert restored.budget is None  # lost on the N-1 hop, by design


def test_plan_dag_adapt_outbound_rejects_older_than_n_minus_1() -> None:
    plan = _current_plan()
    with pytest.raises(UnsupportedCompatVersionError):
        adapt_outbound(plan, PLAN_DAG_VERSION - 2)


def test_plan_dag_adapt_inbound_rejects_older_than_n_minus_1() -> None:
    payload = _load_fixture("plan_dag_n_minus_1_simple.json")
    with pytest.raises(UnsupportedCompatVersionError):
        adapt_inbound(payload, PLAN_DAG_VERSION - 2)


def test_plan_dag_adapt_outbound_rejects_current_version_itself() -> None:
    plan = _current_plan()
    with pytest.raises(UnsupportedCompatVersionError):
        adapt_outbound(plan, PLAN_DAG_VERSION)


# --- Expiry -------------------------------------------------------------------


def test_adapter_refuses_once_expiry_threshold_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    import simplicio.plan_compiler.compat_adapter as compat_adapter

    # Simulate the schema having advanced far enough that this N-1 adapter's
    # expiry policy has kicked in.
    monkeypatch.setattr(
        compat_adapter, "PLAN_DAG_VERSION", compat_adapter.PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION
    )
    plan = _current_plan()
    with pytest.raises(CompatAdapterExpiredError):
        compat_adapter.adapt_outbound(plan, compat_adapter.PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION - 1)


def test_goal_envelope_adapter_refuses_once_expiry_threshold_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import simplicio.plan_compiler.compat_adapter as compat_adapter

    monkeypatch.setattr(
        compat_adapter, "GOAL_ENVELOPE_VERSION", compat_adapter.GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION
    )
    goal = _current_goal()
    with pytest.raises(CompatAdapterExpiredError):
        compat_adapter.adapt_goal_envelope_outbound(
            goal, compat_adapter.GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION - 1
        )
