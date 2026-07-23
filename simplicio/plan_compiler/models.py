"""Typed contracts for the plan compiler (issue #166).

Reference implementation of ``GoalEnvelope``, ``PlanDAG``,
``EffectPlan`` and ``VerificationPlan`` — the interchange contract between a
Goal producer and this compiler, and between this compiler and the Runtime
that owns execution/commit. These schemas do not currently exist as an
importable package anywhere in the simplicio ecosystem (see the #166 planning
note); they are defined here, versioned exactly like
``simplicio.task-spec/v2`` (:mod:`simplicio.task_spec`), so that
simplicio-runtime/simplicio-loop can adopt this shape as a consumer contract
without this package importing their code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.errors import PlanValidationError, SchemaMismatchError

GOAL_ENVELOPE_SCHEMA = "simplicio.goal-envelope/v1"
PLAN_DAG_SCHEMA = "simplicio.plan-dag/v1"
EFFECT_PLAN_SCHEMA = "simplicio.effect-plan/v1"
VERIFICATION_PLAN_SCHEMA = "simplicio.verification-plan/v1"

PLAN_COMPILER_COMPATIBILITY: dict[str, Any] = {
    "major": 1,
    "minimum_consumer_major": 1,
    "contract": "additive-fields-within-major",
    "consumers": ["simplicio-runtime", "simplicio-loop"],
}

IRREVERSIBLE_EFFECT_KINDS = frozenset({"write", "delete", "commit", "irreversible"})


def _check_schema(payload: dict[str, Any], *, expected: str) -> None:
    got = payload.get("schema")
    if got != expected:
        raise SchemaMismatchError(expected.split("/")[0], expected, str(got))


@dataclass(frozen=True)
class GoalEnvelope:
    goal_id: str
    revision: str
    context_snapshot_id: str
    text: str
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    producer_id: str = ""
    consumer_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GOAL_ENVELOPE_SCHEMA,
            "goal_id": self.goal_id,
            "revision": self.revision,
            "context_snapshot_id": self.context_snapshot_id,
            "text": self.text,
            "acceptance_criteria": self.acceptance_criteria,
            "constraints": self.constraints,
            "producer_id": self.producer_id,
            "consumer_id": self.consumer_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GoalEnvelope:
        _check_schema(payload, expected=GOAL_ENVELOPE_SCHEMA)
        return cls(
            goal_id=str(payload["goal_id"]),
            revision=str(payload["revision"]),
            context_snapshot_id=str(payload["context_snapshot_id"]),
            text=str(payload["text"]),
            acceptance_criteria=list(payload.get("acceptance_criteria", [])),
            constraints=dict(payload.get("constraints", {})),
            producer_id=str(payload.get("producer_id", "")),
            consumer_id=str(payload.get("consumer_id", "")),
        )


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    capability: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    _conflicts_with_explicit: bool = field(default=False, repr=False, compare=False)
    read_set: list[str] = field(default_factory=list)
    write_set: list[str] = field(default_factory=list)
    risk: str = "low"
    uncertainty: str = "low"
    estimated_cost: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    acceptance_criteria_refs: list[str] = field(default_factory=list)
    requires_gate: bool = False
    checkpoint_required: bool = False
    rollback_strategy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "node_id": self.node_id,
            "capability": self.capability,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "depends_on": self.depends_on,
            "read_set": self.read_set,
            "write_set": self.write_set,
            "risk": self.risk,
            "uncertainty": self.uncertainty,
            "estimated_cost": self.estimated_cost,
            "reason_codes": self.reason_codes,
            "acceptance_criteria_refs": self.acceptance_criteria_refs,
            "requires_gate": self.requires_gate,
            "checkpoint_required": self.checkpoint_required,
            "rollback_strategy": self.rollback_strategy,
        }
        if self.conflicts_with or self._conflicts_with_explicit:
            payload["conflicts_with"] = self.conflicts_with
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanNode:
        return cls(
            node_id=str(payload["node_id"]),
            capability=str(payload["capability"]),
            inputs=list(payload.get("inputs", [])),
            outputs=list(payload.get("outputs", [])),
            depends_on=list(payload.get("depends_on", [])),
            conflicts_with=list(payload.get("conflicts_with", [])),
            _conflicts_with_explicit="conflicts_with" in payload,
            read_set=list(payload.get("read_set", [])),
            write_set=list(payload.get("write_set", [])),
            risk=str(payload.get("risk", "low")),
            uncertainty=str(payload.get("uncertainty", "low")),
            estimated_cost=float(payload.get("estimated_cost", 0.0)),
            reason_codes=list(payload.get("reason_codes", [])),
            acceptance_criteria_refs=list(payload.get("acceptance_criteria_refs", [])),
            requires_gate=bool(payload.get("requires_gate", False)),
            checkpoint_required=bool(payload.get("checkpoint_required", False)),
            rollback_strategy=payload.get("rollback_strategy"),
        )


@dataclass(frozen=True)
class EffectPlan:
    effect_id: str
    plan_node_id: str
    kind: str
    authority_required: str
    idempotency_key: str
    preconditions: list[str] = field(default_factory=list)
    patch_ref: str | None = None
    artifact_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EFFECT_PLAN_SCHEMA,
            "effect_id": self.effect_id,
            "plan_node_id": self.plan_node_id,
            "kind": self.kind,
            "authority_required": self.authority_required,
            "idempotency_key": self.idempotency_key,
            "preconditions": self.preconditions,
            "patch_ref": self.patch_ref,
            "artifact_ref": self.artifact_ref,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EffectPlan:
        _check_schema(payload, expected=EFFECT_PLAN_SCHEMA)
        return cls(
            effect_id=str(payload["effect_id"]),
            plan_node_id=str(payload["plan_node_id"]),
            kind=str(payload["kind"]),
            authority_required=str(payload["authority_required"]),
            idempotency_key=str(payload["idempotency_key"]),
            preconditions=list(payload.get("preconditions", [])),
            patch_ref=payload.get("patch_ref"),
            artifact_ref=payload.get("artifact_ref"),
        )


@dataclass(frozen=True)
class VerificationPlan:
    verification_id: str
    plan_node_id: str
    verifier: str
    command_or_capability: str
    timeout_s: float
    environment: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria_refs: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    stop_criteria: list[str] = field(default_factory=list)
    abstention_criteria: list[str] = field(default_factory=list)
    replan_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VERIFICATION_PLAN_SCHEMA,
            "verification_id": self.verification_id,
            "plan_node_id": self.plan_node_id,
            "verifier": self.verifier,
            "command_or_capability": self.command_or_capability,
            "timeout_s": self.timeout_s,
            "environment": self.environment,
            "acceptance_criteria_refs": self.acceptance_criteria_refs,
            "expected_evidence": self.expected_evidence,
            "stop_criteria": self.stop_criteria,
            "abstention_criteria": self.abstention_criteria,
            "replan_criteria": self.replan_criteria,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VerificationPlan:
        _check_schema(payload, expected=VERIFICATION_PLAN_SCHEMA)
        return cls(
            verification_id=str(payload["verification_id"]),
            plan_node_id=str(payload["plan_node_id"]),
            verifier=str(payload["verifier"]),
            command_or_capability=str(payload["command_or_capability"]),
            timeout_s=float(payload["timeout_s"]),
            environment=dict(payload.get("environment", {})),
            acceptance_criteria_refs=list(payload.get("acceptance_criteria_refs", [])),
            expected_evidence=list(payload.get("expected_evidence", [])),
            stop_criteria=list(payload.get("stop_criteria", [])),
            abstention_criteria=list(payload.get("abstention_criteria", [])),
            replan_criteria=list(payload.get("replan_criteria", [])),
        )


@dataclass(frozen=True)
class PlanDAG:
    plan_id: str
    goal_id: str
    context_snapshot_id: str
    revision: str
    nodes: list[PlanNode] = field(default_factory=list)
    producer_id: str = ""
    consumer_id: str = ""
    budget: float | None = None
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_DAG_SCHEMA,
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "context_snapshot_id": self.context_snapshot_id,
            "revision": self.revision,
            "nodes": [node.to_dict() for node in self.nodes],
            "producer_id": self.producer_id,
            "consumer_id": self.consumer_id,
            "budget": self.budget,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanDAG:
        _check_schema(payload, expected=PLAN_DAG_SCHEMA)
        raw_budget = payload.get("budget")
        raw_trace_id = payload.get("trace_id")
        return cls(
            plan_id=str(payload["plan_id"]),
            goal_id=str(payload["goal_id"]),
            context_snapshot_id=str(payload["context_snapshot_id"]),
            revision=str(payload["revision"]),
            nodes=[PlanNode.from_dict(node) for node in payload.get("nodes", [])],
            producer_id=str(payload.get("producer_id", "")),
            consumer_id=str(payload.get("consumer_id", "")),
            budget=float(raw_budget) if raw_budget is not None else None,
            trace_id=str(raw_trace_id) if raw_trace_id is not None else None,
        )

    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def validate(
        self,
        *,
        effects: Sequence[EffectPlan] = (),
        verifications: Sequence[VerificationPlan] | None = None,
        budget: float | None = None,
    ) -> None:
        """Reject an invalid PlanDAG/EffectPlan/VerificationPlan bundle.

        Structural checks (duplicate/orphan/cyclic nodes) always run. Effect
        checks (authority, irreversible-without-gate) only run when
        ``effects`` is non-empty. AC-coverage checks run whenever
        ``verifications`` is passed (including an empty list, meaning "no
        verifiers exist yet") — pass ``None`` (the default) to skip AC
        coverage entirely while compiling a bare PlanDAG.

        ``budget`` here is an explicit override for this one call; when it is
        left ``None`` (the default), the check falls back to ``self.budget``
        — the value that was compiled onto the plan itself — so a caller
        that never passes ``budget=`` still gets the check for free whenever
        the plan carries one.
        """
        effective_budget = budget if budget is not None else self.budget
        diagnostics: list[str] = []
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            diagnostics.append("duplicate node_id in PlanDAG")
        known = set(ids)
        for node in self.nodes:
            unknown = set(node.depends_on) - known
            if unknown:
                diagnostics.append(f"node {node.node_id} depends on unknown node(s) {sorted(unknown)}")
            unknown_conflicts = set(node.conflicts_with) - known
            if unknown_conflicts:
                diagnostics.append(
                    f"node {node.node_id} conflicts with unknown node(s) {sorted(unknown_conflicts)}"
                )
            if node.node_id in node.conflicts_with:
                diagnostics.append(f"node {node.node_id} cannot conflict with itself")
            for conflict_id in node.conflicts_with:
                counterpart = next(
                    (candidate for candidate in self.nodes if candidate.node_id == conflict_id),
                    None,
                )
                if counterpart is not None and node.node_id not in counterpart.conflicts_with:
                    diagnostics.append(f"node conflict must be symmetric: {node.node_id} -> {conflict_id}")

        if not diagnostics and self._has_cycle():
            diagnostics.append("PlanDAG contains a dependency cycle")

        if self.consumer_id and self.consumer_id not in PLAN_COMPILER_COMPATIBILITY["consumers"]:
            diagnostics.append(
                f"consumer_id {self.consumer_id!r} is not a registered consumer "
                f"(expected one of {sorted(PLAN_COMPILER_COMPATIBILITY['consumers'])})"
            )

        if effective_budget is not None:
            total_cost = sum(node.estimated_cost for node in self.nodes)
            if total_cost > effective_budget:
                diagnostics.append(f"estimated cost {total_cost} exceeds budget {effective_budget}")

        for effect in effects:
            if effect.plan_node_id not in known:
                diagnostics.append(
                    f"EffectPlan {effect.effect_id} references unknown node {effect.plan_node_id}"
                )
                continue
            if not effect.authority_required.strip():
                diagnostics.append(f"EffectPlan {effect.effect_id} is missing required authority")
            if effect.kind in IRREVERSIBLE_EFFECT_KINDS:
                target_node = self._node_by_id(effect.plan_node_id)
                gated = target_node is not None and (
                    target_node.requires_gate or target_node.checkpoint_required
                )
                if target_node is not None and not gated:
                    diagnostics.append(
                        f"irreversible EffectPlan {effect.effect_id} on node {target_node.node_id} "
                        "requires a gate or checkpoint"
                    )

        if verifications is not None:
            covered: set[str] = set()
            for verification in verifications:
                covered.update(verification.acceptance_criteria_refs)
            for node in self.nodes:
                missing = set(node.acceptance_criteria_refs) - covered
                if missing:
                    diagnostics.append(
                        f"node {node.node_id} acceptance criteria {sorted(missing)} have no verifier"
                    )

        if diagnostics:
            raise PlanValidationError(diagnostics)

    def verifications_for_acceptance_criterion(
        self,
        acceptance_criterion_id: str,
        verifications: Sequence[VerificationPlan],
    ) -> list[VerificationPlan]:
        """Trace an AC id to the ``VerificationPlan``(s) that cover it.

        Given the same ``verifications`` bundle passed to
        :meth:`validate`, returns every ``VerificationPlan`` whose
        ``acceptance_criteria_refs`` includes ``acceptance_criterion_id`` —
        so a caller can look up, for a single AC, exactly which verifier,
        command/capability and expected evidence will prove it passed.
        Returns an empty list for an AC with no coverage (structurally
        possible on an unvalidated bundle; :meth:`validate` rejects this
        when ``verifications`` is passed to it). Does not require the AC to
        be referenced by any node in this PlanDAG — callers that need that
        guarantee should call :meth:`validate` first.
        """
        return [
            verification
            for verification in verifications
            if acceptance_criterion_id in verification.acceptance_criteria_refs
        ]

    def _node_by_id(self, node_id: str) -> PlanNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def _has_cycle(self) -> bool:
        depends_on = {node.node_id: set(node.depends_on) for node in self.nodes}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> bool:
            if node_id in visited:
                return False
            if node_id in visiting:
                return True
            visiting.add(node_id)
            for dep in depends_on.get(node_id, ()):
                if visit(dep):
                    return True
            visiting.discard(node_id)
            visited.add(node_id)
            return False

        return any(visit(node_id) for node_id in depends_on)
