"""Canonical PlanDAG ownership and projection conformance.

The Dev CLI owns compilation of ``simplicio.plan-dag/v1``. Loop and Runtime
consume that contract; they must not silently reshape it into an unrelated
plan. A consumer-specific projection remains possible, but it carries the
canonical source digest and a registered transformation identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.errors import PlanValidationError, SchemaMismatchError
from simplicio.plan_compiler.models import (
    PLAN_COMPILER_COMPATIBILITY,
    PLAN_DAG_SCHEMA,
    PlanDAG,
)

PLAN_PROJECTION_SCHEMA = "simplicio.plan-projection/v1"
PLAN_CONTRACT_OWNER = "simplicio-dev-cli"
PLAN_CONTRACT_CONSUMERS = ("simplicio-loop", "simplicio-runtime")
REGISTERED_PLAN_TRANSFORMATIONS = {
    "simplicio-loop": frozenset({"loop.plan-view/v1"}),
    "simplicio-runtime": frozenset({"runtime.exec-view/v1"}),
}
REQUIRED_PLAN_FIELDS = frozenset(
    {
        "schema",
        "plan_id",
        "goal_id",
        "context_snapshot_id",
        "revision",
        "nodes",
        "producer_id",
        "consumer_id",
        "budget",
        "trace_id",
    }
)


def plan_contract_manifest() -> dict[str, Any]:
    """Return the machine-readable ownership and compatibility manifest."""
    return {
        "schema": "simplicio.plan-contract-manifest/v1",
        "contract": PLAN_DAG_SCHEMA,
        "owner": PLAN_CONTRACT_OWNER,
        "consumers": list(PLAN_CONTRACT_CONSUMERS),
        "compatibility": dict(PLAN_COMPILER_COMPATIBILITY),
        "canonicalization": "utf-8-json-sort-keys-compact-sha256",
        "required_fields": sorted(REQUIRED_PLAN_FIELDS),
        "projection_contract": PLAN_PROJECTION_SCHEMA,
        "projection_rule": "registered-transformation-with-source-digest",
        "registered_transformations": {
            consumer: sorted(transforms) for consumer, transforms in REGISTERED_PLAN_TRANSFORMATIONS.items()
        },
    }


@dataclass(frozen=True)
class PlanProjection:
    """A consumer view that remains bound to one canonical PlanDAG."""

    source_schema: str
    source_digest: str
    target_consumer: str
    transformation_id: str
    payload_digest: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_PROJECTION_SCHEMA,
            "source_schema": self.source_schema,
            "source_digest": self.source_digest,
            "target_consumer": self.target_consumer,
            "transformation_id": self.transformation_id,
            "payload_digest": self.payload_digest,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanProjection:
        if payload.get("schema") != PLAN_PROJECTION_SCHEMA:
            raise SchemaMismatchError(
                "simplicio.plan-projection",
                PLAN_PROJECTION_SCHEMA,
                str(payload.get("schema")),
            )
        return cls(
            source_schema=str(payload["source_schema"]),
            source_digest=str(payload["source_digest"]),
            target_consumer=str(payload["target_consumer"]),
            transformation_id=str(payload["transformation_id"]),
            payload_digest=str(payload["payload_digest"]),
            payload=dict(payload["payload"]),
        )


def _registered_projection_payload(plan: PlanDAG, transformation_id: str) -> dict[str, Any]:
    """Apply one deterministic registered transformation.

    Both initial v1 views intentionally preserve the complete canonical
    payload. Consumers may optimize their in-memory representation after this
    verified boundary, but a new wire projection requires a separately
    registered transformation and tests.
    """
    if transformation_id in {"loop.plan-view/v1", "runtime.exec-view/v1"}:
        return plan.to_dict()
    raise KeyError(transformation_id)


def create_plan_projection(
    plan: PlanDAG,
    *,
    target_consumer: str,
    transformation_id: str,
    payload: dict[str, Any] | None = None,
) -> PlanProjection:
    """Create and validate a digest-bound consumer projection."""
    plan.validate()
    normalized_transformation = transformation_id.strip()
    registered = REGISTERED_PLAN_TRANSFORMATIONS.get(target_consumer, frozenset())
    if normalized_transformation not in registered:
        raise PlanValidationError(
            [
                f"projection transformation {normalized_transformation!r} is not registered "
                f"for {target_consumer!r}"
            ]
        )
    expected_payload = _registered_projection_payload(plan, normalized_transformation)
    candidate_payload = dict(expected_payload if payload is None else payload)
    projection = PlanProjection(
        source_schema=PLAN_DAG_SCHEMA,
        source_digest=plan.canonical_hash(),
        target_consumer=target_consumer,
        transformation_id=normalized_transformation,
        payload_digest=canonical_hash(candidate_payload),
        payload=candidate_payload,
    )
    validate_plan_projection(projection, source_plan=plan)
    return projection


def validate_plan_projection(projection: PlanProjection, *, source_plan: PlanDAG) -> None:
    """Fail closed when a projection loses identity or changes its source."""
    diagnostics: list[str] = []
    try:
        source_plan.validate()
    except PlanValidationError as exc:
        diagnostics.extend(f"source PlanDAG invalid: {item}" for item in exc.diagnostics)
    if projection.source_schema != PLAN_DAG_SCHEMA:
        diagnostics.append(
            f"projection source_schema must be {PLAN_DAG_SCHEMA}, got {projection.source_schema!r}"
        )
    if projection.source_digest != source_plan.canonical_hash():
        diagnostics.append("projection source_digest does not match canonical PlanDAG")
    if projection.target_consumer not in PLAN_CONTRACT_CONSUMERS:
        diagnostics.append(f"projection target_consumer {projection.target_consumer!r} is not registered")
    if not projection.transformation_id:
        diagnostics.append("projection transformation_id is required")
    registered = REGISTERED_PLAN_TRANSFORMATIONS.get(projection.target_consumer, frozenset())
    if projection.transformation_id not in registered:
        diagnostics.append(
            f"projection transformation {projection.transformation_id!r} is not registered "
            f"for {projection.target_consumer!r}"
        )

    payload = projection.payload
    source = source_plan.to_dict()
    if canonical_hash(payload) != projection.payload_digest:
        diagnostics.append("projection payload_digest does not match payload")
    try:
        expected_payload = _registered_projection_payload(source_plan, projection.transformation_id)
    except KeyError:
        expected_payload = None
    if expected_payload is not None and payload != expected_payload:
        diagnostics.append("projection payload does not match registered transformation")
    for field in ("plan_id", "goal_id", "context_snapshot_id", "revision"):
        if payload.get(field) != source[field]:
            diagnostics.append(f"projection must preserve canonical {field}")
    if payload.get("schema") == PLAN_DAG_SCHEMA:
        missing = REQUIRED_PLAN_FIELDS - set(payload)
        if missing:
            diagnostics.append(f"canonical projection is missing fields {sorted(missing)}")
        elif canonical_hash(payload) != projection.source_digest:
            diagnostics.append("canonical projection payload digest does not match source_digest")

    if diagnostics:
        raise PlanValidationError(diagnostics)
