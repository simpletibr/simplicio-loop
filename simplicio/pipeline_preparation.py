"""Typed preparation and route selection for the task pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import Any

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


@dataclass(frozen=True)
class PreparedPipeline:
    """Immutable inputs and selected route consumed by pipeline stages."""

    execution: PreparedExecutionInputs
    input: PipelineInput
    requested_execution_mode: ExecutionMode
    profile: ExecutionProfile


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
