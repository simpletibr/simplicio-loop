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
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .atomic_execution import AttemptContext, execute_work_item_once
from .observability import emit_event
from .pipeline_task_result import _task_result
from .plan_compiler import EffectAuthorization, PlanCompilationError, compile_task_spec_to_plan
from .plan_compiler.authority import AuthorizationError, ChangeProposal, build_change_proposal
from .plan_compiler.effect_sink import EffectDispatchContext, EffectSink, IntegratedModeRequiresSinkError
from .plan_compiler.mapper_context import (
    ContextBinding,
    ContextBindingCache,
    MapperContextError,
    bind_mapper_context,
    load_mapper_context,  # noqa: F401 - retained as a monkeypatchable compatibility boundary
    verify_context_sources,
)
from .plan_compiler.models import EffectPlan, PlanDAG, VerificationPlan
from .plan_compiler.runtime_effect_sink import RuntimeEffectSink
from .task_spec import TaskSpec

__all__ = [
    "IntegratedModeRequiresSinkError",
    "IntegratedPreparationError",
    "PreparedIntegratedWorkItem",
    "prepare_integrated_work_item",
    "run_integrated_route",
    "run_integrated",
]

DEFAULT_INTEGRATED_POLICY_REVISION = "dev-cli-integrated-v1"


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
        extra_fields={
            **(
                {"artifact_ref": os.environ["SIMPLICIO_EFFECT_ARTIFACT_REF"]}
                if os.environ.get("SIMPLICIO_EFFECT_ARTIFACT_REF")
                else {}
            ),
            "causal_read_set": [target],
            "causal_write_set": [target],
        },
    )


class IntegratedPreparationError(RuntimeError):
    def __init__(self, code: str, message: str, *, warning: str | None = None) -> None:
        self.code = code
        self.warning = warning or code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PreparedIntegratedWorkItem:
    plan: PlanDAG
    effect: EffectPlan
    verifications: list[VerificationPlan]
    binding: ContextBinding
    dispatch_context: EffectDispatchContext
    task_spec: TaskSpec
    cache_receipt: dict[str, Any]
    verification_metrics: dict[str, Any]
    goal_id: str


def _causal_verification_paths(plan: PlanDAG) -> tuple[str, ...] | None:
    """Return the typed plan read/write surface, or request safe full scan."""

    paths = {
        str(path).strip()
        for node in plan.nodes
        for path in (*node.read_set, *node.write_set)
        if str(path).strip()
    }
    return tuple(sorted(paths)) or None


def _validate_write_set(write_set: list[str]) -> None:
    seen = set()
    for raw in write_set:
        path = str(raw).replace("\\", "/")
        relative = PurePosixPath(path)
        if not path or relative.is_absolute() or ".." in relative.parts:
            raise IntegratedPreparationError("WRITE_SET_ESCAPE", f"unsafe write path: {raw}")
        if path in seen:
            raise IntegratedPreparationError("WRITE_SET_DUPLICATE", f"duplicate write path: {raw}")
        seen.add(path)


def _context_binding_payload(binding: ContextBinding) -> dict[str, Any]:
    handle = dict(binding.context_handle.to_dict())
    view = getattr(getattr(binding, "snapshot", None), "view", None)
    pack = getattr(binding, "pack", None)
    for field, value in (
        ("snapshot_id", getattr(view, "snapshot_id", "")),
        ("revision", getattr(view, "revision", "")),
        ("root_hash", getattr(view, "root_hash", "")),
        ("pack_hash", getattr(pack, "pack_hash", handle.get("pack_hash", ""))),
        ("projection_digest", getattr(pack, "projection_digest", handle.get("projection_digest", ""))),
    ):
        if value and field not in handle:
            handle[field] = value
    handle["context_handle"] = binding.context_handle.value
    return handle


def _dispatch_context_payload(context: EffectDispatchContext) -> dict[str, Any]:
    return {
        "plan_id": context.plan_id,
        "goal_id": context.goal_id,
        "plan_node": context.plan_node.to_dict(),
        "verifications": [item.to_dict() for item in context.verifications],
        "coordinator_kind": context.coordinator_kind,
        "coordinator_id": context.coordinator_id,
        "session_id": context.session_id,
        "turn_id": context.turn_id,
        "attempt": context.attempt,
        "subworkflow_id": context.subworkflow_id,
        "deadline": context.deadline,
        "policy_revision": context.policy_revision,
        "base_hash": context.base_hash,
        "source_hash": context.source_hash,
        "context_handle": context.context_handle,
        "lease_id": context.lease_id,
        "fencing_token": context.fencing_token,
        "authorization": None,
        "plan_digest": context.plan.canonical_hash() if context.plan else "",
    }


def _proposal_envelope(prepared: PreparedIntegratedWorkItem, proposal: ChangeProposal) -> dict[str, Any]:
    pp = proposal.to_dict()
    binding = _context_binding_payload(prepared.binding)
    effect = prepared.effect.to_dict()
    return {
        **pp,
        "envelope": "simplicio.change-proposal-envelope/v1",
        "proposal": pp,
        "proposal_digest": proposal.digest(),
        "plan": prepared.plan.to_dict(),
        "plan_digest": prepared.plan.canonical_hash(),
        "effect": effect,
        "effect_digest": proposal.effect_digest,
        "verifications": [item.to_dict() for item in prepared.verifications],
        "context_binding": binding,
        "source": {
            "task_source_hash": prepared.task_spec.source_hash,
            "mapper_source_digest": str(binding.get("source_digest", "")),
            "snapshot_id": str(binding.get("snapshot_id", "")),
            "revision": str(binding.get("revision", "")),
            "root_hash": str(binding.get("root_hash", "")),
            "pack_hash": str(binding.get("pack_hash", "")),
            "projection_digest": str(binding.get("projection_digest", "")),
        },
        "identity": {
            "attempt_id": proposal.attempt_id,
            "lease_id": proposal.lease_id,
            "fencing_token": proposal.fencing_token,
            "context_handle": proposal.context_handle,
            "policy_revision": proposal.policy_revision,
        },
        "dispatch_context": _dispatch_context_payload(prepared.dispatch_context),
    }


def prepare_integrated_work_item(
    root: str,
    stack: str,
    goal: str,
    target: str,
    criteria: str,
    constraints: str,
    primary_test_cmd: str | None,
    *,
    authorization: EffectAuthorization | None = None,
    context_snapshot: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
    execution_context: dict[str, Any] | None = None,
    context_refresh: bool = False,
    attempt: AttemptContext | None = None,
    task_spec: TaskSpec | None = None,
    coordinator_kind: str = "simplicio-dev-cli",
    session_id: str = "",
    turn_id: str = "",
    attempt_number: int = 1,
    subworkflow_id: str = "",
    deadline: str | None = None,
    policy_revision: str = DEFAULT_INTEGRATED_POLICY_REVISION,
    base_hash: str = "",
    context_pack_hash: str | None = None,
    proposal_only: bool = False,
) -> PreparedIntegratedWorkItem:
    if attempt is None:
        raise IntegratedPreparationError(
            "COORDINATOR_CONTEXT_REQUIRED",
            "integrated proposal requires attempt, lease, fence, and context handle",
        )
    if context_refresh and proposal_only:
        raise IntegratedPreparationError(
            "PROPOSAL_CONTEXT_REFRESH_FORBIDDEN", "proposal-only cannot refresh or write the context cache"
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
    if not task_spec.verification_commands:
        raise IntegratedPreparationError(
            "verification_command_missing",
            "verification command missing; set SIMPLICIO_TEST_CMD before execution",
            warning="verification command missing; set SIMPLICIO_TEST_CMD before execution",
        )
    if context_snapshot is None:
        raise IntegratedPreparationError("CONTEXT_REQUIRED", "canonical Mapper ContextSnapshot is required")
    if context_pack is None:
        raise IntegratedPreparationError("CONTEXT_PACK_REQUIRED", "Mapper ContextPack is required")
    binding = bind_mapper_context(
        context_snapshot, context_pack, source_root=root, execution_context_payload=execution_context
    )
    # Do not hash the complete ContextPack here. The plan below determines the
    # causal read/write set; verification is performed once, immediately
    # before effect dispatch, against that set. Keeping an explicit receipt
    # entry preserves observability without paying for a redundant full scan.
    bind_verification_metrics = {
        "files_considered": 0,
        "files_hashed": 0,
        "bytes_read": 0,
        "generation": str(
            getattr(
                binding.context_handle,
                "generation",
                getattr(getattr(binding.snapshot, "view", None), "revision", ""),
            )
        ),
        "paths_requested": [],
        "engine": "deferred-causal",
        "fallback_reason": "causal_verification_deferred",
    }
    canonical_pack_hash = str(getattr(getattr(binding, "pack", None), "pack_hash", "") or "")
    supplied_pack_hash = None if context_pack_hash is None else str(context_pack_hash).strip()
    if supplied_pack_hash is not None and supplied_pack_hash != canonical_pack_hash:
        raise IntegratedPreparationError(
            "CONTEXT_PACK_HASH_MISMATCH",
            "supplied context_pack_hash does not match the canonical Mapper ContextPack",
        )
    context_snapshot_id = binding.snapshot.view.snapshot_id
    revision = binding.snapshot.view.revision
    context_handle = binding.context_handle.value
    if attempt.context_handle != context_handle:
        raise IntegratedPreparationError(
            "CONTEXT_HANDLE_MISMATCH",
            "attempt context_handle must match the snapshot/projection digest binding",
        )
    cache = ContextBindingCache(root)
    cache_receipt = cache.refresh(binding) if context_refresh else cache.lookup(binding.context_handle)
    goal_material = task_spec.canonical_hash() if typed_input else goal
    goal_id = f"goal-{hashlib.sha256(goal_material.encode('utf-8')).hexdigest()[:16]}"
    plan, effects, verifications = compile_task_spec_to_plan(
        task_spec,
        goal_id=goal_id,
        context_snapshot_id=context_snapshot_id,
        revision=revision,
        context_handle=context_handle,
    )
    causal_paths = _causal_verification_paths(plan)
    pre_effect_verification_metrics = (
        verify_context_sources(binding, source_root=root, paths=causal_paths) or {}
    )
    if supplied_pack_hash is not None and supplied_pack_hash != str(
        getattr(getattr(binding, "pack", None), "pack_hash", "") or ""
    ):
        raise IntegratedPreparationError(
            "CONTEXT_PACK_HASH_MISMATCH",
            "supplied context_pack_hash does not match the canonical Mapper ContextPack",
        )
    if len(effects) != 1:
        raise IntegratedPreparationError(
            "MULTI_EFFECT", "proposal-only dispatch requires exactly one EffectPlan"
        )
    effect = effects[0]
    nodes = [node for node in plan.nodes if node.node_id == effect.plan_node_id]
    if len(nodes) != 1:
        raise IntegratedPreparationError("EFFECT_PLAN_NODE_INVALID", "effect must bind exactly one PlanNode")
    node = nodes[0]
    _validate_write_set(node.write_set)
    dispatch = EffectDispatchContext(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        plan_node=node,
        verifications=[item for item in verifications if item.plan_node_id == node.node_id],
        coordinator_kind=coordinator_kind,
        coordinator_id=attempt.attempt_id,
        session_id=session_id,
        turn_id=turn_id,
        attempt=attempt_number,
        subworkflow_id=subworkflow_id,
        deadline=deadline,
        policy_revision=policy_revision,
        base_hash=base_hash,
        source_hash=task_spec.source_hash,
        context_handle=context_handle,
        lease_id=attempt.lease_id,
        fencing_token=attempt.fencing_token,
        authorization=authorization,
        plan=plan,
    )
    try:
        build_change_proposal(effect, dispatch)
    except AuthorizationError as exc:
        raise IntegratedPreparationError(exc.code, str(exc)) from exc
    return PreparedIntegratedWorkItem(
        plan,
        effect,
        verifications,
        binding,
        dispatch,
        task_spec,
        cache_receipt,
        {
            "bind": bind_verification_metrics,
            "pre_effect": pre_effect_verification_metrics,
        },
        goal_id,
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
    context_refresh: bool = False,
    attempt: AttemptContext | None = None,
    task_spec: TaskSpec | None = None,
    coordinator_kind: str = "simplicio-dev-cli",
    session_id: str = "",
    turn_id: str = "",
    attempt_number: int = 1,
    subworkflow_id: str = "",
    deadline: str | None = None,
    policy_revision: str = DEFAULT_INTEGRATED_POLICY_REVISION,
    base_hash: str = "",
    context_pack_hash: str | None = None,
    proposal_only: bool = False,
) -> dict[str, Any]:
    if effect_sink is None and not proposal_only:
        effect_sink = RuntimeEffectSink.from_environment(root=root)
    if not proposal_only:
        emit_event(
            "task_start", {"target": target, "stack": stack, "goal": goal, "mode": "integrated"}, root=root
        )
    try:
        prepared = prepare_integrated_work_item(
            root,
            stack,
            goal,
            target,
            criteria,
            constraints,
            primary_test_cmd,
            authorization=authorization,
            context_snapshot=context_snapshot,
            context_pack=context_pack,
            execution_context=execution_context,
            context_refresh=context_refresh,
            attempt=attempt,
            task_spec=task_spec,
            coordinator_kind=coordinator_kind,
            session_id=session_id,
            turn_id=turn_id,
            attempt_number=attempt_number,
            subworkflow_id=subworkflow_id,
            deadline=deadline,
            policy_revision=policy_revision,
            base_hash=base_hash,
            context_pack_hash=context_pack_hash,
            proposal_only=proposal_only,
        )
    except IntegratedPreparationError as exc:
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[exc.warning],
            blocked_preconditions=[{"code": exc.code, "message": str(exc)}],
        )
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
                {"code": warning, "message": f"{exc.code}: snapshot/projection binding rejected"}
            ],
        )
    except PlanCompilationError as exc:
        if not proposal_only:
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
    proposal = build_change_proposal(prepared.effect, prepared.dispatch_context)
    if proposal_only:
        envelope = _proposal_envelope(prepared, proposal)
        result = _task_result(
            target, prompt, "", applied=False, status="proposal_only", warnings=[], blocked_preconditions=[]
        )
        result.update(
            {
                "proposal": envelope,
                "proposal_digest": envelope["proposal_digest"],
                "plan": prepared.plan.to_dict(),
                "effects": [prepared.effect.to_dict()],
                "verifications": [item.to_dict() for item in prepared.verifications],
                "context_binding": _context_binding_payload(prepared.binding),
                "verification_metrics": prepared.verification_metrics,
                "dispatch_context": _dispatch_context_payload(prepared.dispatch_context),
                "task_spec_hash": prepared.task_spec.canonical_hash(),
            }
        )
        return result
    if effect_sink is None:
        raise IntegratedModeRequiresSinkError("integrated mode requires a Runtime EffectSink")
    if attempt is None:
        raise IntegratedModeRequiresSinkError("integrated mode requires a coordinator attempt")
    observation = execute_work_item_once(
        prepared.dispatch_context.plan_node,
        attempt,
        effects=[prepared.effect],
        verifications=prepared.verifications,
        effect_sink=effect_sink,
        dispatch_context=prepared.dispatch_context,
    )
    result = _task_result(
        target,
        prompt,
        "",
        applied=isinstance(effect_sink, RuntimeEffectSink) and observation.outcome == "effect_submitted",
        status="integrated_atomic",
    )
    result.update(
        {
            "plan": prepared.plan.to_dict(),
            "effects": [prepared.effect.to_dict()],
            "verifications": [item.to_dict() for item in prepared.verifications],
            "observation": observation.to_dict(),
            "task_spec_hash": prepared.task_spec.canonical_hash(),
            "context_binding": {
                **_context_binding_payload(prepared.binding),
                "cache": prepared.cache_receipt,
            },
            "verification_metrics": prepared.verification_metrics,
        }
    )
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


def run_integrated_route(
    *,
    root: str,
    stack: str,
    goal: str,
    target: str,
    criteria: str,
    constraints: str,
    prompt: str,
    primary_test_cmd: str | None,
    effect_sink: EffectSink | None,
    authorization: EffectAuthorization | None,
    context_snapshot: dict[str, Any] | None,
    context_pack: dict[str, Any] | None,
    execution_context: dict[str, Any] | None,
    context_refresh: bool,
    attempt: AttemptContext | None,
    task_spec: TaskSpec | None,
    coordinator_kind: str,
    session_id: str,
    turn_id: str,
    attempt_number: int,
    subworkflow_id: str,
    deadline: str | None,
    policy_revision: str,
    base_hash: str,
    context_pack_hash: str | None,
    proposal_only: bool,
    execution_profile: dict[str, Any],
    task_context: Any,
    attach_contract_receipt: Callable[..., dict[str, Any]],
    final_receipt_status: Callable[..., str],
) -> dict[str, Any]:
    """Own the integrated route's receipt and effect-boundary orchestration."""

    from .standalone_migration import mutation_receipt, record_effect_unknown

    started_at = time.monotonic()
    result = run_integrated(
        root,
        stack,
        goal,
        target,
        criteria,
        constraints,
        prompt,
        primary_test_cmd,
        effect_sink,
        authorization=authorization,
        context_snapshot=context_snapshot,
        context_pack=context_pack,
        execution_context=execution_context,
        context_refresh=context_refresh,
        attempt=attempt,
        task_spec=task_spec,
        coordinator_kind=coordinator_kind,
        session_id=session_id,
        turn_id=turn_id,
        attempt_number=attempt_number,
        subworkflow_id=subworkflow_id,
        deadline=deadline,
        policy_revision=policy_revision,
        base_hash=base_hash,
        context_pack_hash=context_pack_hash,
        proposal_only=proposal_only,
    )
    result["duration_ms"] = int((time.monotonic() - started_at) * 1000)
    result["execution_profile"] = execution_profile
    if proposal_only:
        return result

    verification_plans = result.get("verifications")
    verification_commands = (
        [
            str(item.get("command"))
            for item in verification_plans
            if isinstance(item, dict) and item.get("command")
        ]
        if isinstance(verification_plans, list)
        else []
    )
    observation = result.get("observation")
    observation = observation if isinstance(observation, dict) else {}
    retryable = observation.get("retryability") == "retryable"
    result["mutation_receipt"] = mutation_receipt(
        "runtime_effect_api",
        entrypoint="task",
        plan=result.get("plan"),
        changeset=result.get("effects"),
        files=result.get("files_changed"),
        verification={
            "commands": verification_commands,
            "results": observation.get("validation", []),
        },
        retry={"attempt": attempt_number, "max_attempts": 1, "retryable": retryable},
        duration_ms=result.get("duration_ms"),
        final_status=final_receipt_status(result, dry_run=result.get("status") == "dry_run"),
    )
    result = attach_contract_receipt(
        result,
        task_context=task_context,
        route="runtime_effect_api",
        effective_mode=execution_profile.get("effective_mode", "integrated"),
        authorization=authorization,
        verification_status=str(observation.get("outcome", "unverified")),
        attempt=attempt,
        duration_ms=result.get("duration_ms"),
        retry={"attempt": attempt_number, "max_attempts": 1, "retryable": retryable},
    )
    if observation.get("outcome") == "effect_unknown":
        record_effect_unknown(root)
    return result
