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

from .observability import emit_event
from .pipeline_task_result import _task_result
from .plan_compiler import PlanCompilationError, compile_task_spec_to_plan
from .plan_compiler.effect_sink import EffectSink, IntegratedModeRequiresSinkError
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
) -> dict[str, Any]:
    """Compile a plan and hand its effects to ``effect_sink``; never write.

    Never calls ``git apply``/writes to ``root`` -- that is the whole point
    of this mode (#166, #167). Refuses to proceed
    (:class:`IntegratedModeRequiresSinkError`) instead of silently falling
    back to direct writes when no ``effect_sink`` is given.
    """
    if effect_sink is None:
        raise IntegratedModeRequiresSinkError(
            "mode='integrated' requires an effect_sink; refusing to fall back to "
            "direct writes. The sink is the local stub boundary for the real "
            "simplicio-runtime Effect API (issue #166 dependency on Runtime "
            "#3134/#3135) -- see simplicio/plan_compiler/effect_sink.py and "
            "docs/plan-compiler.md."
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

    task_spec = _build_task_spec(
        target=target,
        goal=goal,
        criteria=criteria,
        constraints=constraints,
        verification_command=primary_test_cmd,
    )
    goal_id = f"goal-{hashlib.sha256(goal.encode('utf-8')).hexdigest()[:16]}"
    context_snapshot_id = f"snap-{hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:16]}"
    try:
        plan, effects, verifications = compile_task_spec_to_plan(
            task_spec,
            goal_id=goal_id,
            context_snapshot_id=context_snapshot_id,
            revision="1",
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

    # The sink is the ONLY thing allowed to apply/commit an effect. It is a
    # local stub today (see module docstring); a real integration swaps it
    # for a sink that forwards to simplicio-runtime's Effect API.
    sink_results = [effect_sink(effect) for effect in effects]

    result = _task_result(target, prompt, "", applied=False, status="integrated_planned")
    result["plan"] = plan.to_dict()
    result["effects"] = [effect.to_dict() for effect in effects]
    result["verifications"] = [verification.to_dict() for verification in verifications]
    result["effect_sink_results"] = [
        {"effect_id": sink_result.effect_id, "accepted": sink_result.accepted, "detail": sink_result.detail}
        for sink_result in sink_results
    ]
    emit_event(
        "task_complete",
        {"target": target, "mode": "integrated", "effects": len(effects)},
        root=root,
        tokens_saved=0,
    )
    return result
