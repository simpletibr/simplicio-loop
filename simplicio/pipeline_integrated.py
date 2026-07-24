"""Integrated-mode entry point for pipeline.py's run_task (issues #166, #167).

Extracted into its own module (mirroring ``pipeline_stages.py`` and
``pipeline_task_result.py``'s existing extraction pattern -- see issue #141's
coordinator refactor and its AC "keep pipeline.py under its token budget") so
``pipeline.py`` only needs a thin ``mode == "integrated"`` branch instead of
housing this whole code path itself.

Both #166 ("No modo integrado, zero escrita/commit fora da Effect API do
Runtime") and #167 ("Modo integrado não executa writes diretamente") name the
same invariant: when ``run_task`` runs in integrated mode, it must compile a
``PlanDAG``/``EffectPlan`` bundle (via
``simplicio.plan_compiler.compile_task_spec_to_plan``) and hand every
``EffectPlan`` to the caller-supplied ``effect_sink`` instead of ever calling
``git apply`` or writing to the worktree itself. The sink is a local stub
boundary standing in for the real ``simplicio-runtime`` Effect API (Runtime
issues #3134/#3135, which do not exist as code in this repo yet) -- see
``simplicio/plan_compiler/effect_sink.py`` and ``docs/plan-compiler.md``.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .atomic_execution import AttemptContext, execute_work_item_once
from .observability import emit_event
from .pipeline_task_result import _task_result
from .plan_compiler import EffectAuthorization, PlanCompilationError, compile_task_spec_to_plan
from .plan_compiler.effect_sink import EffectDispatchContext, EffectSink, IntegratedModeRequiresSinkError
from .plan_compiler.mapper_context import (
    MapperContextError,
    bind_mapper_context,
    load_mapper_context,  # noqa: F401 - retained as a monkeypatchable compatibility boundary
    verify_context_sources,
)
from .plan_compiler.runtime_effect_sink import RuntimeEffectSink
from .task_spec import TaskSpec

__all__ = ["IntegratedModeRequiresSinkError", "run_integrated"]


def _build_task_spec(
    *,
    target: str,
    goal: str,
    criteria: str,
    constraints: str,
    verification_command: str | None,
) -> TaskSpec:
    """Build a minimal ``TaskSpec`` from ``run_task``'s raw arguments.

    ``run_task`` takes free-form ``goal``/``criteria``/``constraints``
    strings, not an already-parsed ``TaskSpec`` -- this is a deterministic,
    no-model bridge from that shape to the one
    ``compile_task_spec_to_plan()`` consumes. It does not attempt full
    Markdown intake (see ``simplicio.task_spec`` for that); each non-blank
    line of ``criteria`` becomes one acceptance criterion.
    """
    lines = [line.strip() for line in (criteria or "").splitlines() if line.strip()]
    acceptance_criteria = [
        {"id": f"AC{index + 1}", "text": line.lstrip("-* ").strip()} for index, line in enumerate(lines)
    ]
    verification_commands = (
        [{"command": verification_command, "verifier": "pytest"}] if verification_command else []
    )
    source_text = f"{goal}\n{criteria}\n{constraints}"
    return TaskSpec(
        task_id=target,
        source={"kind": "argument"},
        source_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        language="text",
        narrative={"goal": goal, "constraints": constraints},
        acceptance_criteria=acceptance_criteria,
        verification_commands=verification_commands,
        original_text=source_text,
    )


def run_integrated(
    root: str,
    stack: str,
    goal: str,
    target: str,
    criteria: str,
    constraints: str,
    prompt: str,
    primary_test_cmd: str | None,
    effect_sink: EffectSink | None,
    *,
    authorization: EffectAuthorization | None = None,
    context_snapshot: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
    execution_context: dict[str, Any] | None = None,
    attempt: AttemptContext | None = None,
    task_spec: TaskSpec | None = None,
) -> dict[str, Any]:
    """Compile a plan and hand its effects to ``effect_sink``; never write.

    Never calls ``git apply``/writes to ``root`` -- that is the whole point
    of this mode (#166, #167). Refuses to proceed
    (:class:`IntegratedModeRequiresSinkError`) instead of silently falling
    back to direct writes when no ``effect_sink`` is given.
    """
    if effect_sink is None:
        effect_sink = RuntimeEffectSink.from_environment(root=root)
    if attempt is None:
        raise IntegratedModeRequiresSinkError(
            "mode='integrated' requires coordinator-supplied attempt_id, lease, fence, and context handle"
        )
    if primary_test_cmd is None:
        blocker = {
            "code": "verification_command_missing",
            "message": "verification command missing; set SIMPLICIO_TEST_CMD before execution",
        }
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[blocker["message"]],
            blocked_preconditions=[blocker],
        )

    emit_event(
        "task_start",
        {"target": target, "stack": stack, "goal": goal, "mode": "integrated"},
        root=root,
    )

    typed_input = task_spec is not None
    if task_spec is None:
        task_spec = _build_task_spec(
            target=target,
            goal=goal,
            criteria=criteria,
            constraints=constraints,
            verification_command=primary_test_cmd,
        )
    goal_material = task_spec.canonical_hash() if typed_input else goal
    goal_id = f"goal-{hashlib.sha256(goal_material.encode('utf-8')).hexdigest()[:16]}"
    if context_snapshot is None:
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=["CONTEXT_REQUIRED"],
            blocked_preconditions=[
                {"code": "CONTEXT_REQUIRED", "message": "canonical Mapper ContextSnapshot is required"}
            ],
        )
    if context_pack is None:
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=["CONTEXT_PACK_REQUIRED"],
            blocked_preconditions=[
                {
                    "code": "CONTEXT_PACK_REQUIRED",
                    "message": "Mapper ContextPack with snapshot provenance is required",
                }
            ],
        )
    try:
        binding = bind_mapper_context(
            context_snapshot,
            context_pack,
            source_root=root,
            execution_context_payload=execution_context,
        )
        verify_context_sources(binding, source_root=root)
    except MapperContextError as exc:
        warning = (
            exc.code if exc.code in {"SOURCE_DRIFT", "CONTEXT_ROOT_PATH_MISMATCH"} else "INCOMPATIBLE_CONTEXT"
        )
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[warning],
            blocked_preconditions=[
                {
                    "code": warning,
                    "message": f"{exc.code}: snapshot/projection binding rejected",
                }
            ],
        )
    context_snapshot_id = binding.snapshot.view.snapshot_id
    revision = binding.snapshot.view.revision
    context_handle = binding.context_handle.value
    if attempt.context_handle != context_handle:
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=["CONTEXT_HANDLE_MISMATCH"],
            blocked_preconditions=[
                {
                    "code": "CONTEXT_HANDLE_MISMATCH",
                    "message": "attempt context_handle must match the snapshot/projection digest binding",
                }
            ],
        )
    try:
        plan, effects, verifications = compile_task_spec_to_plan(
            task_spec,
            goal_id=goal_id,
            context_snapshot_id=context_snapshot_id,
            revision=revision,
            context_handle=context_handle,
        )
    except PlanCompilationError as exc:
        emit_event(
            "validation_fail",
            {"target": target, "warnings": [str(exc)[:500]], "mode": "integrated"},
            level="warning",
            root=root,
        )
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[str(exc)],
            blocked_preconditions=[{"code": "plan_compilation_failed", "message": str(exc)}],
        )

    effect_node = next(
        node for node in plan.nodes if any(effect.plan_node_id == node.node_id for effect in effects)
    )
    dispatch_context = EffectDispatchContext(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        plan_node=effect_node,
        verifications=[item for item in verifications if item.plan_node_id == effect_node.node_id],
        coordinator_id=attempt.attempt_id,
        source_hash=task_spec.source_hash,
        context_handle=context_handle,
        lease_id=attempt.lease_id,
        fencing_token=attempt.fencing_token,
        authorization=authorization,
    )
    observation = execute_work_item_once(
        effect_node,
        attempt,
        effects=effects,
        verifications=verifications,
        effect_sink=effect_sink,
        dispatch_context=dispatch_context,
    )

    result = _task_result(target, prompt, "", applied=False, status="integrated_atomic")
    result["plan"] = plan.to_dict()
    result["effects"] = [effect.to_dict() for effect in effects]
    result["verifications"] = [verification.to_dict() for verification in verifications]
    result["observation"] = observation.to_dict()
    result["task_spec_hash"] = task_spec.canonical_hash()
    result["context_binding"] = {
        **binding.context_handle.to_dict(),
        "context_handle": context_handle,
    }
    emit_event(
        "task_complete",
        {
            "target": target,
            "mode": "integrated",
            "attempt_id": attempt.attempt_id,
            "outcome": observation.outcome,
            "effects": len(observation.effect_ids),
        },
        root=root,
        tokens_saved=0,
    )
    return result
