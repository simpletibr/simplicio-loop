import pytest

from simplicio.plan_compiler import (
    EFFECT_PLAN_SCHEMA,
    EffectPlan,
    GoalEnvelope,
    PlanDAG,
    PlanNode,
    PlanValidationError,
    SchemaMismatchError,
    VerificationPlan,
)
from simplicio.runtime_contracts import AGENT_FIRST_BOUNDARY_FORBIDDEN_FIELDS


def _simple_plan() -> PlanDAG:
    return PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[
            PlanNode(
                node_id="n1",
                capability="edit.apply",
                acceptance_criteria_refs=["AC1"],
            ),
            PlanNode(
                node_id="n2",
                capability="test.run",
                depends_on=["n1"],
            ),
        ],
    )


def test_canonical_hash_is_deterministic() -> None:
    plan_a = _simple_plan()
    plan_b = _simple_plan()
    assert plan_a.canonical_hash() == plan_b.canonical_hash()


def test_canonical_hash_changes_with_content() -> None:
    plan_a = _simple_plan()
    plan_b = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="2",
        nodes=plan_a.nodes,
    )
    assert plan_a.canonical_hash() != plan_b.canonical_hash()


def test_validate_rejects_cycle() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[
            PlanNode(node_id="n1", capability="a", depends_on=["n2"]),
            PlanNode(node_id="n2", capability="b", depends_on=["n1"]),
        ],
    )
    with pytest.raises(PlanValidationError):
        plan.validate()


def test_validate_rejects_orphan_dependency() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[PlanNode(node_id="n1", capability="a", depends_on=["missing"])],
    )
    with pytest.raises(PlanValidationError):
        plan.validate()


def test_validate_rejects_unmapped_acceptance_criteria() -> None:
    plan = _simple_plan()
    with pytest.raises(PlanValidationError):
        plan.validate(verifications=[])
    with pytest.raises(PlanValidationError):
        plan.validate(
            verifications=[
                VerificationPlan(
                    verification_id="v1",
                    plan_node_id="n2",
                    verifier="pytest",
                    command_or_capability="pytest -q",
                    timeout_s=60.0,
                    acceptance_criteria_refs=["AC_OTHER"],
                )
            ]
        )


def test_validate_accepts_fully_covered_acceptance_criteria() -> None:
    plan = _simple_plan()
    plan.validate(
        verifications=[
            VerificationPlan(
                verification_id="v1",
                plan_node_id="n1",
                verifier="pytest",
                command_or_capability="pytest -q",
                timeout_s=60.0,
                acceptance_criteria_refs=["AC1"],
            )
        ]
    )


def test_validate_rejects_irreversible_effect_without_gate() -> None:
    plan = _simple_plan()
    effect = EffectPlan(
        effect_id="e1",
        plan_node_id="n1",
        kind="delete",
        authority_required="runtime.write",
        idempotency_key="k1",
    )
    with pytest.raises(PlanValidationError):
        plan.validate(effects=[effect])


def test_validate_accepts_irreversible_effect_with_checkpoint() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[
            PlanNode(
                node_id="n1",
                capability="edit.apply",
                checkpoint_required=True,
            )
        ],
    )
    effect = EffectPlan(
        effect_id="e1",
        plan_node_id="n1",
        kind="delete",
        authority_required="runtime.write",
        idempotency_key="k1",
    )
    plan.validate(effects=[effect])


def test_validate_rejects_effect_missing_authority() -> None:
    plan = _simple_plan()
    effect = EffectPlan(
        effect_id="e1",
        plan_node_id="n2",
        kind="read",
        authority_required="   ",
        idempotency_key="k1",
    )
    with pytest.raises(PlanValidationError):
        plan.validate(effects=[effect])


def test_validate_rejects_budget_overflow() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[
            PlanNode(node_id="n1", capability="a", estimated_cost=5.0),
            PlanNode(node_id="n2", capability="b", estimated_cost=10.0),
        ],
    )
    with pytest.raises(PlanValidationError):
        plan.validate(budget=10.0)
    plan.validate(budget=15.0)


def test_verifications_for_acceptance_criterion_resolves_verifier_and_evidence() -> None:
    plan = _simple_plan()
    verifications = [
        VerificationPlan(
            verification_id="v1",
            plan_node_id="n1",
            verifier="pytest",
            command_or_capability="pytest -q tests/test_ac1.py",
            timeout_s=60.0,
            acceptance_criteria_refs=["AC1"],
            expected_evidence=["pytest-junit.xml"],
        )
    ]
    plan.validate(verifications=verifications)

    matches = plan.verifications_for_acceptance_criterion("AC1", verifications)

    assert len(matches) == 1
    assert matches[0].verifier == "pytest"
    assert matches[0].command_or_capability == "pytest -q tests/test_ac1.py"
    assert matches[0].expected_evidence == ["pytest-junit.xml"]


def test_verifications_for_acceptance_criterion_resolves_multiple_verifiers() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[
            PlanNode(node_id="n1", capability="edit.apply", acceptance_criteria_refs=["AC1"]),
        ],
    )
    verifications = [
        VerificationPlan(
            verification_id="v1",
            plan_node_id="n1",
            verifier="pytest",
            command_or_capability="pytest -q",
            timeout_s=60.0,
            acceptance_criteria_refs=["AC1"],
            expected_evidence=["pytest-junit.xml"],
        ),
        VerificationPlan(
            verification_id="v2",
            plan_node_id="n1",
            verifier="playwright",
            command_or_capability="npx playwright test",
            timeout_s=120.0,
            acceptance_criteria_refs=["AC1"],
            expected_evidence=["trace.zip", "screenshot.png"],
        ),
    ]

    matches = plan.verifications_for_acceptance_criterion("AC1", verifications)

    assert {match.verifier for match in matches} == {"pytest", "playwright"}
    evidence = {ev for match in matches for ev in match.expected_evidence}
    assert evidence == {"pytest-junit.xml", "trace.zip", "screenshot.png"}


def test_verifications_for_acceptance_criterion_empty_for_uncovered_ac() -> None:
    plan = _simple_plan()
    verifications = [
        VerificationPlan(
            verification_id="v1",
            plan_node_id="n1",
            verifier="pytest",
            command_or_capability="pytest -q",
            timeout_s=60.0,
            acceptance_criteria_refs=["AC1"],
        )
    ]

    matches = plan.verifications_for_acceptance_criterion("AC_UNKNOWN", verifications)

    assert matches == []


def test_schema_mismatch_on_load() -> None:
    payload = _simple_plan().to_dict()
    payload["schema"] = "simplicio.wrong-schema/v1"
    with pytest.raises(SchemaMismatchError):
        PlanDAG.from_dict(payload)


def test_effect_plan_round_trip() -> None:
    effect = EffectPlan(
        effect_id="e1",
        plan_node_id="n1",
        kind="write",
        authority_required="runtime.write",
        idempotency_key="k1",
        preconditions=["base_sha==abc"],
        patch_ref="content://patch/1",
    )
    payload = effect.to_dict()
    assert payload["schema"] == EFFECT_PLAN_SCHEMA
    assert EffectPlan.from_dict(payload) == effect


def test_plan_dag_round_trip() -> None:
    plan = _simple_plan()
    restored = PlanDAG.from_dict(plan.to_dict())
    assert restored == plan
    assert restored.canonical_hash() == plan.canonical_hash()


def test_goal_envelope_round_trip() -> None:
    envelope = GoalEnvelope(
        goal_id="goal-1",
        revision="1",
        context_snapshot_id="snap-1",
        text="do the thing",
        acceptance_criteria=["AC1"],
        producer_id="simplicio-agent",
        consumer_id="simplicio-dev-cli",
    )
    payload = envelope.to_dict()
    assert payload["producer_id"] == "simplicio-agent"
    assert GoalEnvelope.from_dict(payload) == envelope


def test_goal_envelope_defaults_producer_and_consumer_id() -> None:
    envelope = GoalEnvelope(
        goal_id="goal-1",
        revision="1",
        context_snapshot_id="snap-1",
        text="do the thing",
    )
    assert envelope.producer_id == ""
    assert envelope.consumer_id == ""


def test_validate_accepts_registered_consumer_id() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[],
        consumer_id="simplicio-runtime",
    )
    plan.validate()


def test_validate_rejects_unregistered_consumer_id() -> None:
    plan = PlanDAG(
        plan_id="plan-1",
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="1",
        nodes=[],
        consumer_id="some-other-runtime",
    )
    with pytest.raises(PlanValidationError):
        plan.validate()


def test_compiled_runtime_handoff_payloads_exclude_agent_owned_control_plane_fields() -> None:
    from simplicio.plan_compiler import compile_task_spec_to_plan
    from simplicio.task_spec import TaskSpec

    task_spec = TaskSpec(
        task_id="src/app.py",
        source={"kind": "argument"},
        source_hash="deadbeef",
        language="pt-BR",
        acceptance_criteria=[{"id": "AC1"}],
        verification_commands=[{"command": "pytest -q"}],
    )

    plan, effects, verifications = compile_task_spec_to_plan(
        task_spec,
        goal_id="goal-1",
        context_snapshot_id="snap-1",
        revision="rev-1",
        trace_id="trace-1",
    )

    handoff_payloads = [plan.to_dict(), *(effect.to_dict() for effect in effects), *(v.to_dict() for v in verifications)]

    def _walk_keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from _walk_keys(nested)
        elif isinstance(value, list):
            for item in value:
                yield from _walk_keys(item)

    observed = {key for payload in handoff_payloads for key in _walk_keys(payload)}
    forbidden = set(AGENT_FIRST_BOUNDARY_FORBIDDEN_FIELDS)

    assert forbidden.isdisjoint(observed), (
        "compiled Runtime handoff unexpectedly contains Agent-owned control-plane "
        f"fields: {sorted(forbidden & observed)}"
    )
