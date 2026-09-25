"""Conformance and adversarial coverage for canonical PlanDAG projections."""

from __future__ import annotations

import pytest

from simplicio.plan_compiler import (
    PLAN_DAG_SCHEMA,
    PLAN_PROJECTION_SCHEMA,
    PlanDAG,
    PlanNode,
    PlanProjection,
    PlanValidationError,
    SchemaMismatchError,
    create_plan_projection,
    plan_contract_manifest,
    validate_plan_projection,
)
from simplicio.plan_compiler.canonical_hash import canonical_hash


def _plan() -> PlanDAG:
    return PlanDAG(
        plan_id="plan-298",
        goal_id="goal-298",
        context_snapshot_id="snapshot-298",
        revision="7",
        nodes=[
            PlanNode(
                node_id="edit",
                capability="edit.apply",
                conflicts_with=["publish"],
                requires_gate=True,
            ),
            PlanNode(
                node_id="publish",
                capability="receipt.publish",
                depends_on=["edit"],
                conflicts_with=["edit"],
            ),
        ],
        producer_id="simplicio-dev-cli",
        consumer_id="simplicio-runtime",
        trace_id="trace-298",
    )


def test_manifest_names_one_owner_and_registered_consumers() -> None:
    manifest = plan_contract_manifest()

    assert manifest["contract"] == PLAN_DAG_SCHEMA
    assert manifest["owner"] == "simplicio-dev-cli"
    assert manifest["consumers"] == ["simplicio-loop", "simplicio-runtime"]
    assert manifest["projection_contract"] == PLAN_PROJECTION_SCHEMA
    assert {"plan_id", "goal_id", "nodes"} <= set(manifest["required_fields"])


def test_projection_round_trip_preserves_canonical_digest_and_identity() -> None:
    plan = _plan()
    projection = create_plan_projection(
        plan,
        target_consumer="simplicio-loop",
        transformation_id="loop.plan-view/v1",
    )

    restored = PlanProjection.from_dict(projection.to_dict())
    validate_plan_projection(restored, source_plan=plan)

    assert restored.source_digest == plan.canonical_hash()
    assert restored.payload == plan.to_dict()


def test_projection_rejects_tampered_source_digest() -> None:
    plan = _plan()
    projection = create_plan_projection(
        plan,
        target_consumer="simplicio-runtime",
        transformation_id="runtime.exec-view/v1",
    )
    tampered = PlanProjection(
        source_schema=projection.source_schema,
        source_digest="0" * 64,
        target_consumer=projection.target_consumer,
        transformation_id=projection.transformation_id,
        payload_digest=projection.payload_digest,
        payload=projection.payload,
    )

    with pytest.raises(PlanValidationError, match="source_digest"):
        validate_plan_projection(tampered, source_plan=plan)


def test_projection_rejects_identity_loss_and_unregistered_consumer() -> None:
    plan = _plan()
    payload = plan.to_dict()
    payload["goal_id"] = "different-goal"
    projection = PlanProjection(
        source_schema=PLAN_DAG_SCHEMA,
        source_digest=plan.canonical_hash(),
        target_consumer="unregistered-scheduler",
        transformation_id="unsafe/v1",
        payload_digest=canonical_hash(payload),
        payload=payload,
    )

    with pytest.raises(PlanValidationError) as raised:
        validate_plan_projection(projection, source_plan=plan)

    diagnostics = " ".join(raised.value.diagnostics)
    assert "target_consumer" in diagnostics
    assert "goal_id" in diagnostics


def test_projection_rejects_unknown_schema_major() -> None:
    payload = create_plan_projection(
        _plan(),
        target_consumer="simplicio-loop",
        transformation_id="loop.plan-view/v1",
    ).to_dict()
    payload["schema"] = "simplicio.plan-projection/v2"

    with pytest.raises(SchemaMismatchError):
        PlanProjection.from_dict(payload)


def test_projection_rejects_wrong_source_schema_and_blank_transformation() -> None:
    plan = _plan()
    projection = PlanProjection(
        source_schema="simplicio.plan-dag/v2",
        source_digest=plan.canonical_hash(),
        target_consumer="simplicio-loop",
        transformation_id="",
        payload_digest=canonical_hash(plan.to_dict()),
        payload=plan.to_dict(),
    )

    with pytest.raises(PlanValidationError) as raised:
        validate_plan_projection(projection, source_plan=plan)

    diagnostics = " ".join(raised.value.diagnostics)
    assert "source_schema" in diagnostics
    assert "transformation_id" in diagnostics


def test_canonical_projection_rejects_missing_required_field() -> None:
    plan = _plan()
    payload = plan.to_dict()
    payload.pop("trace_id")
    projection = PlanProjection(
        source_schema=PLAN_DAG_SCHEMA,
        source_digest=plan.canonical_hash(),
        target_consumer="simplicio-runtime",
        transformation_id="runtime.exec-view/v1",
        payload_digest=canonical_hash(payload),
        payload=payload,
    )

    with pytest.raises(PlanValidationError, match="missing fields"):
        validate_plan_projection(projection, source_plan=plan)


def test_plan_rejects_unknown_and_self_conflicts() -> None:
    plan = PlanDAG(
        plan_id="plan-invalid",
        goal_id="goal-invalid",
        context_snapshot_id="snapshot-invalid",
        revision="1",
        nodes=[
            PlanNode(
                node_id="edit",
                capability="edit.apply",
                conflicts_with=["edit", "missing"],
            )
        ],
    )

    with pytest.raises(PlanValidationError) as raised:
        plan.validate()

    diagnostics = " ".join(raised.value.diagnostics)
    assert "unknown node" in diagnostics
    assert "cannot conflict with itself" in diagnostics


def test_conflicts_round_trip_without_changing_hash() -> None:
    plan = _plan()

    restored = PlanDAG.from_dict(plan.to_dict())

    assert restored == plan
    assert restored.canonical_hash() == plan.canonical_hash()


def test_projection_rejects_unregistered_or_tampered_custom_payload() -> None:
    plan = _plan()
    malicious = {
        **plan.to_dict(),
        "nodes": [],
        "actions": ["DROP ALL GATES"],
    }

    with pytest.raises(PlanValidationError, match="not registered"):
        create_plan_projection(
            plan,
            target_consumer="simplicio-loop",
            transformation_id="attacker/unregistered",
            payload=malicious,
        )
    with pytest.raises(PlanValidationError, match="registered transformation"):
        create_plan_projection(
            plan,
            target_consumer="simplicio-loop",
            transformation_id="loop.plan-view/v1",
            payload=malicious,
        )


def test_projection_rejects_payload_mutated_after_creation() -> None:
    plan = _plan()
    projection = create_plan_projection(
        plan,
        target_consumer="simplicio-runtime",
        transformation_id="runtime.exec-view/v1",
    )
    projection.payload["nodes"] = []

    with pytest.raises(PlanValidationError, match="payload_digest"):
        validate_plan_projection(projection, source_plan=plan)


def test_projection_rejects_structurally_invalid_source_plan() -> None:
    invalid = PlanDAG(
        plan_id="invalid",
        goal_id="goal",
        context_snapshot_id="snapshot",
        revision="1",
        nodes=[
            PlanNode(node_id="duplicate", capability="edit"),
            PlanNode(node_id="duplicate", capability="verify"),
        ],
    )

    with pytest.raises(PlanValidationError, match="duplicate"):
        create_plan_projection(
            invalid,
            target_consumer="simplicio-loop",
            transformation_id="loop.plan-view/v1",
        )


def test_empty_conflicts_preserve_legacy_v1_canonical_digest() -> None:
    legacy_payload = {
        "schema": "simplicio.plan-dag/v1",
        "plan_id": "legacy",
        "goal_id": "goal",
        "context_snapshot_id": "snapshot",
        "revision": "1",
        "nodes": [
            {
                "node_id": "edit",
                "capability": "edit.apply",
                "inputs": [],
                "outputs": [],
                "depends_on": [],
                "conflicts_with": [],
                "read_set": [],
                "write_set": [],
                "risk": "low",
                "uncertainty": "low",
                "estimated_cost": 0.0,
                "reason_codes": [],
                "acceptance_criteria_refs": [],
                "requires_gate": False,
                "checkpoint_required": False,
                "rollback_strategy": None,
            }
        ],
        "producer_id": "",
        "consumer_id": "",
        "budget": None,
        "trace_id": None,
    }
    legacy_digest = "d019aae40fd01e5044e97af3772d6c22ecc9f64dd00e80a25d55cc4a10772b54"

    restored = PlanDAG.from_dict(legacy_payload)

    assert restored.to_dict() == legacy_payload
    assert restored.canonical_hash() == legacy_digest


def test_plan_rejects_asymmetric_conflicts() -> None:
    plan = PlanDAG(
        plan_id="asymmetric",
        goal_id="goal",
        context_snapshot_id="snapshot",
        revision="1",
        nodes=[
            PlanNode(node_id="a", capability="edit", conflicts_with=["b"]),
            PlanNode(node_id="b", capability="verify"),
        ],
    )

    with pytest.raises(PlanValidationError, match="symmetric"):
        plan.validate()
