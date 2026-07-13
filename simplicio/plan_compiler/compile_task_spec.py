"""Deterministic TaskSpec -> PlanDAG compiler (issue #166 slice 2).

Turns an existing :class:`simplicio.task_spec.TaskSpec` into the typed
``PlanDAG``/``EffectPlan``/``VerificationPlan`` bundle defined in
:mod:`simplicio.plan_compiler.models`, with no model call and no embedded
execution: the same TaskSpec plus the same ``goal_id``/
``context_snapshot_id``/``revision`` always compiles to the same
``PlanDAG.canonical_hash()``.

Still purely additive: nothing in ``cli.py``/``pipeline.py``/
``orchestrator/multi_task.py`` calls this yet (see
``docs/plan-compiler.md``).
"""

from __future__ import annotations

import hashlib

from simplicio.plan_compiler.errors import PlanCompilerError
from simplicio.plan_compiler.models import EffectPlan, PlanDAG, PlanNode, VerificationPlan
from simplicio.task_spec import TaskSpec

EDIT_NODE_ID = "edit"
VERIFY_NODE_ID = "verify"


class PlanCompilationError(PlanCompilerError):
    """Raised when a TaskSpec lacks what the compiler needs to build a plan.

    Every diagnostic here is a NEEDS_CLARIFICATION signal: the compiler never
    silently assumes acceptance criteria or a verification command that
    aren't present on the TaskSpec.
    """


def _idempotency_key(task_spec: TaskSpec, *, goal_id: str, context_snapshot_id: str, revision: str) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                task_spec.task_id,
                task_spec.source_hash,
                goal_id,
                context_snapshot_id,
                revision,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"edit-{digest[:16]}"


def compile_task_spec_to_plan(
    task_spec: TaskSpec,
    *,
    goal_id: str,
    context_snapshot_id: str,
    revision: str,
    budget: float | None = None,
) -> tuple[PlanDAG, list[EffectPlan], list[VerificationPlan]]:
    """Compile ``task_spec`` into a validated ``(PlanDAG, effects, verifications)``.

    Raises :class:`PlanCompilationError` when the TaskSpec has no acceptance
    criteria or no verification commands -- there is nothing deterministic
    to map nodes to AC coverage or verifiers in that case. Raises
    :class:`~simplicio.plan_compiler.errors.PlanValidationError` if the
    compiled bundle itself is inconsistent (should not happen for a
    well-formed TaskSpec; kept as a defense-in-depth check).

    ``budget``, when passed, is stored on the compiled ``PlanDAG`` (round-trips
    through ``to_dict()``/``from_dict()`` and is enforced by ``plan.validate()``
    against the summed ``estimated_cost`` of every node) so a caller-supplied
    cost ceiling survives the compile step observably, the same way
    ``goal_id``/``revision`` already do.
    """
    diagnostics: list[str] = []
    if not task_spec.acceptance_criteria:
        diagnostics.append(
            "NEEDS_CLARIFICATION: task_spec has no acceptance_criteria; cannot map plan nodes to AC coverage"
        )
    if not task_spec.verification_commands:
        diagnostics.append(
            "NEEDS_CLARIFICATION: task_spec has no verification_commands; cannot build a VerificationPlan"
        )
    if diagnostics:
        raise PlanCompilationError("; ".join(diagnostics))

    ac_refs = [str(criterion["id"]) for criterion in task_spec.acceptance_criteria]

    edit_node = PlanNode(
        node_id=EDIT_NODE_ID,
        capability="edit.apply",
        outputs=[task_spec.task_id],
        acceptance_criteria_refs=ac_refs,
        risk="medium",
        reason_codes=["task_spec_compile"],
        requires_gate=True,
    )
    verify_node = PlanNode(
        node_id=VERIFY_NODE_ID,
        capability="test.run",
        depends_on=[EDIT_NODE_ID],
        acceptance_criteria_refs=ac_refs,
        reason_codes=["task_spec_compile"],
    )

    plan = PlanDAG(
        plan_id=f"plan-{task_spec.task_id}",
        goal_id=goal_id,
        context_snapshot_id=context_snapshot_id,
        revision=revision,
        nodes=[edit_node, verify_node],
        budget=budget,
    )

    effects = [
        EffectPlan(
            effect_id=f"effect-{task_spec.task_id}",
            plan_node_id=EDIT_NODE_ID,
            kind="write",
            authority_required="dev-cli.edit",
            idempotency_key=_idempotency_key(
                task_spec,
                goal_id=goal_id,
                context_snapshot_id=context_snapshot_id,
                revision=revision,
            ),
            preconditions=[f"context_snapshot:{context_snapshot_id}"],
        )
    ]

    verifications = [
        VerificationPlan(
            verification_id=f"verify-{task_spec.task_id}-{index}",
            plan_node_id=VERIFY_NODE_ID,
            verifier=str(command.get("verifier", "pytest")),
            command_or_capability=str(command["command"]),
            timeout_s=float(command.get("timeout_s", 300.0)),
            acceptance_criteria_refs=ac_refs,
        )
        for index, command in enumerate(task_spec.verification_commands)
    ]

    plan.validate(effects=effects, verifications=verifications)
    return plan, effects, verifications
