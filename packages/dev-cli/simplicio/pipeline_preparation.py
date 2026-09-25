"""Typed preparation and route selection for the task pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from os import PathLike
from typing import Any, Literal

from .atomic_execution import AttemptContext
from .execution_mode import (
    ExecutionMode,
    ExecutionProfile,
    PreparedExecutionInputs,
    negotiate_execution_mode,
    prepare_execution_inputs,
    requested_mode,
    require_coordinator_attempt,
)
from .pipeline_input import PipelineInput, prepare_pipeline_input
from .plan_compiler.authority import EffectAuthorization
from .task_context import TaskContext, TaskContextError
from .task_spec import TaskSpec

TASK_SPEC_REQUIRES_INTEGRATED_MODE = "TASK_SPEC_REQUIRES_INTEGRATED_MODE"
TASK_SPEC_ROUTE_MESSAGE = "typed TaskSpec input is accepted only by the integrated execution path"


@dataclass(frozen=True)
class TaskSpecRouteDecision:
    """Typed decision for routing a TaskSpec without consuming it."""

    blocked: bool
    code: str = ""
    message: str = ""


def resolve_task_spec_route(
    task_spec: TaskSpec | None,
    effective_mode: Literal["integrated", "standalone", "blocked"],
) -> TaskSpecRouteDecision:
    """Select the TaskSpec route without mutating the task or execution profile."""
    if task_spec is None or effective_mode == "integrated":
        return TaskSpecRouteDecision(blocked=False)
    return TaskSpecRouteDecision(
        blocked=True,
        code=TASK_SPEC_REQUIRES_INTEGRATED_MODE,
        message=TASK_SPEC_ROUTE_MESSAGE,
    )


@dataclass(frozen=True)
class PreparedPipeline:
    """Immutable inputs and selected route consumed by pipeline stages."""

    execution: PreparedExecutionInputs
    input: PipelineInput
    requested_execution_mode: ExecutionMode
    profile: ExecutionProfile


@dataclass(frozen=True)
class TaskPreflight:
    """Prepared task context and identity decisions before route execution."""

    context_snapshot: dict[str, Any] | None
    context_pack: dict[str, Any] | None
    execution_context: dict[str, Any] | None
    authorization: EffectAuthorization | None
    effect_sink: object | None
    runtime_handshake: dict[str, Any] | None
    integrated_attempt: AttemptContext | None
    pipeline_input: PipelineInput
    requested_execution_mode: ExecutionMode
    profile: ExecutionProfile
    task_context: TaskContext | None
    context_error: TaskContextError | None
    identity_error: TaskContextError | None
    identity_required: bool


def prepare_pipeline_inputs(
    mode: str | None = None,
    *,
    root: str | PathLike[str] = ".",
    repo_root: str | PathLike[str] | None = None,
    scope_root: str | PathLike[str] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
    context_snapshot_id: str | None = None,
    context_pack_hash: str | None = None,
    execution_context: dict[str, Any] | None = None,
    authorization: EffectAuthorization | None = None,
    context_snapshot_path: str | PathLike[str] | None = None,
    context_pack_path: str | PathLike[str] | None = None,
    execution_context_path: str | PathLike[str] | None = None,
    authorization_path: str | PathLike[str] | None = None,
    effect_sink: object | None = None,
    proposal_only: bool = False,
    runtime_handshake: dict[str, Any] | None = None,
    integrated_attempt: AttemptContext | None = None,
    attempt_id: str | None = None,
    lease_id: str | None = None,
    fencing_token: str | None = None,
    context_handle: str | None = None,
    dry_run_task: bool = False,
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
) -> PreparedPipeline:
    execution = prepare_execution_inputs(
        mode,
        root=root,
        context_snapshot=context_snapshot,
        context_pack=context_pack,
        execution_context=execution_context,
        authorization=authorization,
        context_snapshot_path=context_snapshot_path,
        context_pack_path=context_pack_path,
        execution_context_path=execution_context_path,
        authorization_path=authorization_path,
        effect_sink=effect_sink,
        proposal_only=proposal_only,
        runtime_handshake=runtime_handshake,
        attempt=integrated_attempt,
        attempt_id=attempt_id,
        lease_id=lease_id,
        fencing_token=fencing_token,
        context_handle=context_handle,
    )
    pipeline_input = prepare_pipeline_input(
        str(root),
        repo_root=repo_root,
        scope_root=scope_root,
        context_snapshot=execution.context_snapshot,
        context_pack=execution.context_pack,
        context_snapshot_id=context_snapshot_id,
        context_pack_hash=context_pack_hash,
        attempt_id=attempt_id,
        integrated_attempt=execution.attempt,
    )
    requested_execution_mode = requested_mode(mode, root)
    profile = negotiate_execution_mode(
        mode,
        root=root,
        runtime_handshake=execution.runtime_handshake,
        context_snapshot=execution.context_snapshot,
        effect_sink=execution.effect_sink,
        coordinator_kind=coordinator_kind,
        coordinator_id=coordinator_id,
        # ``dry_run_task`` is itself the non-mutating route.  Passing
        # ``read_only`` here short-circuits preparation before the dry-run
        # preconditions can inspect artifacts and, in valid cases, before the
        # provider can produce a preview diff.  Keep execution negotiation
        # honest and let the dedicated dry-run path enforce no mutation.
        read_only=False,
        proposal_only=proposal_only,
    )
    profile = require_coordinator_attempt(profile, execution.attempt)
    return PreparedPipeline(
        execution=execution,
        input=pipeline_input,
        requested_execution_mode=requested_execution_mode,
        profile=profile,
    )


def _identity_requirements(
    *,
    effective_mode: str,
    requested_execution_mode: str | None,
    context_snapshot: dict[str, Any] | None,
    context_pack: dict[str, Any] | None,
    snapshot_identity: str,
    pack_identity: str,
    attempt_identity: str,
    supplied_snapshot_id: str | None,
    canonical_snapshot_id: str,
    supplied_pack_hash: str | None,
    canonical_pack_hash: str,
    dry_run_task: bool,
) -> tuple[TaskContextError | None, bool]:
    """Compute identity mismatch and authority requirements for one task."""
    identity_error: TaskContextError | None = None
    if supplied_snapshot_id is not None and supplied_snapshot_id != canonical_snapshot_id:
        identity_error = TaskContextError(
            "CONTEXT_SNAPSHOT_ID_MISMATCH",
            "supplied context_snapshot_id does not match the canonical Mapper snapshot",
        )
    elif supplied_pack_hash is not None and canonical_pack_hash and supplied_pack_hash != canonical_pack_hash:
        identity_error = TaskContextError(
            "CONTEXT_PACK_HASH_MISMATCH",
            "supplied context_pack_hash does not match the canonical Mapper ContextPack",
        )
    strict_authority = os.environ.get("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    identity_required = not dry_run_task and (
        (
            effective_mode == "integrated"
            and context_snapshot is not None
            and context_pack is not None
            and bool(snapshot_identity and pack_identity and attempt_identity)
        )
        or (
            effective_mode == "standalone"
            and requested_execution_mode != "standalone"
            and (
                strict_authority
                or context_snapshot is not None
                or context_pack is not None
                or supplied_snapshot_id is not None
                or supplied_pack_hash is not None
            )
        )
    )
    return identity_error, identity_required


def prepare_task_preflight(
    prepared: PreparedPipeline,
    *,
    target: str,
    dry_run_task: bool,
) -> TaskPreflight:
    """Build the task context and identity decisions before route execution."""
    pipeline_input = prepared.input
    context_error: TaskContextError | None = None
    task_context: TaskContext | None = None
    try:
        if pipeline_input.declared_repo_root != pipeline_input.actual_root:
            raise TaskContextError(
                "REPO_ROOT_MISMATCH",
                "declared repo_root must equal the actual mutation root",
            )
        task_context = TaskContext.from_values(
            repo_root=pipeline_input.actual_root,
            scope_root=pipeline_input.declared_scope_root,
            target=target,
            context_snapshot_id=pipeline_input.snapshot_identity,
            context_pack_hash=pipeline_input.pack_identity,
            attempt_id=pipeline_input.attempt_identity,
            require_identity=False,
        )
    except TaskContextError as exc:
        context_error = exc

    identity_error: TaskContextError | None = None
    identity_required = False
    if task_context is not None:
        identity_error, identity_required = _identity_requirements(
            effective_mode=prepared.profile.effective_mode,
            requested_execution_mode=prepared.requested_execution_mode,
            context_snapshot=prepared.execution.context_snapshot,
            context_pack=prepared.execution.context_pack,
            snapshot_identity=pipeline_input.snapshot_identity,
            pack_identity=pipeline_input.pack_identity,
            attempt_identity=pipeline_input.attempt_identity,
            supplied_snapshot_id=pipeline_input.supplied_snapshot_id,
            canonical_snapshot_id=pipeline_input.canonical_snapshot_id,
            supplied_pack_hash=pipeline_input.supplied_pack_hash,
            canonical_pack_hash=pipeline_input.canonical_pack_hash,
            dry_run_task=dry_run_task,
        )

    return TaskPreflight(
        context_snapshot=prepared.execution.context_snapshot,
        context_pack=prepared.execution.context_pack,
        execution_context=prepared.execution.execution_context,
        authorization=prepared.execution.authorization,
        effect_sink=prepared.execution.effect_sink,
        runtime_handshake=prepared.execution.runtime_handshake,
        integrated_attempt=prepared.execution.attempt,
        pipeline_input=pipeline_input,
        requested_execution_mode=prepared.requested_execution_mode,
        profile=prepared.profile,
        task_context=task_context,
        context_error=context_error,
        identity_error=identity_error,
        identity_required=identity_required,
    )
