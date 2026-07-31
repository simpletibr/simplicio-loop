"""pipeline.py — build -> generate -> validate -> test -> fix -> verify (loop).

The 6-layer contract (mapper→precedent→prompt→diff→test→verify) is
implemented by this module plus :mod:`simplicio.mapper` for the first two
layers.  Issue #93 adds impact-test verification to the ``verify`` layer:
after the primary test passes, ``_run_impact_tests`` queries the mapper's
``impact`` and ``tests-for`` verbs to find callers of the changed symbols
and runs their tests too.  When impact tests fail, the failure enters the
retry loop just like any verify failure.
"""

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Literal, cast

from .adaptive import get_validation_mode
from .atomic_execution import AttemptContext
from .execution_receipts import execution_mode_blocker
from .mapper import map_ask
from .observability import emit_event, estimate_tokens, info, log_run
from .pipeline_fixers import try_static_fixers
from .pipeline_integrated import run_integrated
from .pipeline_stages import (
    IMPACT_RESULT_FAILED,
    IMPACT_RESULT_NOT_NEEDED,
    IMPACT_RESULT_PASSED,
    IMPACT_RESULT_UNVERIFIED,
    authorized_path_warnings,
    bound_path_drift,
    build_retry_feedback,
    classify_failure,
    extract_changed_files,
    run_apply_stage,
    run_impact_tests,
    snapshot_bound_paths,
    validate_generated_output,
)
from .pipeline_stages import (
    _git_apply_patch as _stage_git_apply_patch,
)
from .pipeline_task_result import (
    _dry_run_preconditions,
    _task_result,
    target_kind,
)
from .plan_compiler.authority import EffectAuthorization
from .plan_compiler.effect_sink import EffectSink
from .plan_compiler.runtime_effect_sink import RuntimeEffectSink
from .prompt import build_prompt, set_prompt_retry_delta
from .providers import ProviderExecutionError, _provider_id, generate
from .runtime_env import prepare_project_command
from .task_context import TaskContext, TaskContextError
from .task_spec import TaskSpec
from .transaction import VerificationReceipt

MAX_ATTEMPTS = 5

# mode="integrated" (issues #166, #167) delegates to pipeline_integrated.run_integrated
# instead of housing the plan-compile/effect-sink logic here — see that
# module's docstring for the full contract and pipeline.py's token-budget
# rationale (issue #141 AC).
PipelineMode = Literal["auto", "standalone", "integrated"]


def _attach_contract_receipt(
    result: dict[str, Any],
    *,
    task_context: TaskContext,
    route: str,
    effective_mode: str,
    authorization: EffectAuthorization | None = None,
    verification_status: str = "unverified",
    attempt: AttemptContext | None = None,
    duration_ms: int | float | None = None,
    retry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patch_value = result.get("patch")
    patch: dict[str, Any] = patch_value if isinstance(patch_value, dict) else {}
    verify_value = result.get("verify")
    verify: dict[str, Any] = verify_value if isinstance(verify_value, dict) else {}
    binding = result.get("context_binding")
    if isinstance(binding, dict):
        binding_snapshot = str(binding.get("snapshot_id") or "").strip()
        binding_pack = str(binding.get("pack_hash") or "").strip()
        if binding_snapshot and binding_pack:
            task_context = TaskContext.from_values(
                repo_root=task_context.repo_root,
                scope_root=task_context.scope_root,
                target=task_context.target,
                context_snapshot_id=binding_snapshot,
                context_pack_hash=binding_pack,
                attempt_id=task_context.attempt_id,
                require_identity=False,
            )
    observation = result.get("observation")
    observation_payload = observation if isinstance(observation, dict) else {}
    verification_plans = result.get("verifications")
    commands = (
        [
            str(item.get("command"))
            for item in verification_plans
            if isinstance(item, dict) and item.get("command")
        ]
        if isinstance(verification_plans, list)
        else []
    )
    verification_results = observation_payload.get("validation", [])
    if not isinstance(verification_results, list):
        verification_results = []
    if not verification_results and verify:
        verification_results = [verify]
    files = result.get("files_changed")
    if not isinstance(files, list):
        files = patch.get("files", []) if isinstance(patch.get("files"), list) else []
    retry_payload = dict(retry or {})
    retry_payload.setdefault("attempt", 1)
    retry_payload.setdefault("max_attempts", 1)
    retry_payload.setdefault("retryable", observation_payload.get("retryability") == "retryable")
    receipt = task_context.receipt(
        route=route,
        effective_mode=effective_mode,
        authorization_id=(authorization.authorization_digest if authorization is not None else None),
        before_digest=patch.get("base_sha"),
        after_digest=patch.get("candidate_sha"),
        verification_status=verification_status or str(verify.get("status", "unverified")),
        lease_id=attempt.lease_id if attempt is not None else None,
        fencing_token=attempt.fencing_token if attempt is not None else None,
        context_handle=attempt.context_handle if attempt is not None else None,
        plan=result.get("plan"),
        changeset=result.get("changeset", result.get("effects")),
        files=files,
        verification={"commands": commands, "results": verification_results},
        retry=retry_payload,
        duration_ms=duration_ms if duration_ms is not None else result.get("duration_ms"),
        final_status="applied" if result.get("applied") else str(result.get("status", "blocked")),
    )
    result["mutation_authorization_receipt"] = receipt
    return result


def _resolve_max_attempts() -> int:
    """Resolve the host-configurable attempt budget."""
    raw = os.environ.get("SIMPLICIO_MAX_ATTEMPTS", "").strip()
    if not raw:
        return MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        return MAX_ATTEMPTS
    return value if value >= 1 else MAX_ATTEMPTS


# Issue #219: opt-in whole-task wall-clock deadline (0 = disabled), on top
# of #210's per-provider-call bound.
def _task_deadline_s() -> float:
    raw = os.environ.get("SIMPLICIO_TASK_DEADLINE_S", "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if value > 0 else 0.0


# Issue #219: consecutive same-fingerprint failures before retry feedback escalates.
def _retry_escalation_after() -> int:
    raw = os.environ.get("SIMPLICIO_RETRY_ESCALATION_AFTER", "").strip()
    if not raw:
        return 2
    try:
        value = int(raw)
    except ValueError:
        return 2
    return value if value >= 1 else 2


def _failure_fingerprint(log: str | None) -> str:
    kind = classify_failure(log).kind
    digest = hashlib.sha256((log or "").encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{kind}:{digest}"


# Live receipt state — written by the apply stage (``_apply_and_test_attempt``)
# and read both here (for the patch receipt) and by ``_task_result`` in
# ``pipeline_task_result.py``.  Kept in the coordinator module because it is
# coordination state, not a self-contained feature (issue #141).
_LAST_VERIFY_RECEIPT: dict[str, Any] | None = None
_LAST_PATCH_RECEIPT: dict[str, Any] | None = None


def _remember_verify_receipt(receipt: VerificationReceipt | None) -> None:
    global _LAST_VERIFY_RECEIPT
    _LAST_VERIFY_RECEIPT = receipt.to_dict() if receipt is not None else None


def _remember_patch_receipt(receipt: dict[str, Any] | None) -> None:
    global _LAST_PATCH_RECEIPT
    if receipt is None:
        _LAST_PATCH_RECEIPT = None
        return
    payload = dict(receipt)
    payload.setdefault(
        "mutation_route",
        {
            "schema": "simplicio.dev-cli.mutation-route/v1",
            "entrypoint": "task",
            "route": "legacy_standalone",
            "runtime_gated": False,
            "legacy": True,
        },
    )
    _LAST_PATCH_RECEIPT = payload


# ---------------------------------------------------------------------------
# Impact-test verification — issue #93 / stage extraction for #141
# ---------------------------------------------------------------------------


def _run_impact_tests(
    root: str | Path, files_changed: list[str], *, test_cmd: str | None = None
) -> dict[str, Any]:
    return run_impact_tests(
        root,
        files_changed,
        test_cmd=test_cmd,
        map_ask_fn=map_ask,
        prepare_project_command_fn=prepare_project_command,
    )


def _run_impact_tests_compat(
    root: str | Path, files_changed: list[str], test_cmd: str | None
) -> dict[str, Any]:
    """Call the impact hook without breaking legacy two-argument test doubles."""

    if test_cmd is None:
        return _run_impact_tests(root, files_changed)
    return _run_impact_tests(root, files_changed, test_cmd=test_cmd)


def _git_apply_patch(root, patch):
    return _stage_git_apply_patch(root, patch, subprocess_run=subprocess.run)


def _apply_and_test_attempt(
    output,
    root,
    bound_paths=None,
    *,
    promote_on_success=True,
    repo_root=None,
    scope_root=None,
):
    if _apply_and_test is not _DEFAULT_APPLY_AND_TEST:
        path_warnings = authorized_path_warnings(
            extract_changed_files(output),
            root=root,
            repo_root=repo_root,
            scope_root=scope_root,
        )
        if path_warnings:
            ok, log = False, "pre-apply validation failed: " + "; ".join(path_warnings)
        else:
            ok, log = _apply_and_test(output, root, bound_paths)

        class _PatchedAttempt:
            def __init__(self, ok, log):
                self.ok = ok
                self.log = log
                self.tx = None
                self.receipt = None
                self.changed_files = None

        return _PatchedAttempt(ok, log)
    global _LAST_VERIFY_RECEIPT, _LAST_PATCH_RECEIPT
    result = run_apply_stage(
        output,
        root,
        bound_paths=bound_paths,
        git_apply_patch_fn=_git_apply_patch,
        prepare_project_command_fn=prepare_project_command,
        promote_on_success=promote_on_success,
        repo_root=repo_root,
        scope_root=scope_root,
    )
    _LAST_VERIFY_RECEIPT = result.verify_receipt
    _remember_patch_receipt(result.patch_receipt)
    return result


def _apply_and_test(output, root, bound_paths=None):
    attempt = _apply_and_test_attempt(output, root, bound_paths, promote_on_success=True)
    return attempt.ok, attempt.log


_DEFAULT_APPLY_AND_TEST = _apply_and_test


def run_task(
    root,
    stack,
    goal,
    target,
    criteria,
    constraints,
    *,
    dry_run_task=False,
    bound_paths=None,
    quiet=False,
    mode: PipelineMode | None = None,
    effect_sink: EffectSink | None = None,
    authorization: EffectAuthorization | None = None,
    context_snapshot: dict | None = None,
    context_pack: dict | None = None,
    execution_context: dict | None = None,
    context_refresh: bool = False,
    runtime_handshake: dict | None = None,
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
    integrated_attempt: AttemptContext | None = None,
    task_spec: TaskSpec | None = None,
    context_snapshot_path: str | os.PathLike[str] | None = None,
    context_pack_path: str | os.PathLike[str] | None = None,
    execution_context_path: str | os.PathLike[str] | None = None,
    authorization_path: str | os.PathLike[str] | None = None,
    attempt_id: str | None = None,
    lease_id: str | None = None,
    fencing_token: str | None = None,
    context_handle: str | None = None,
    session_id: str = "",
    turn_id: str = "",
    attempt_number: int = 1,
    subworkflow_id: str = "",
    deadline: str | None = None,
    policy_revision: str = "dev-cli-integrated-v1",
    base_hash: str = "",
    repo_root: str | os.PathLike[str] | None = None,
    scope_root: str | os.PathLike[str] | None = None,
    context_snapshot_id: str | None = None,
    context_pack_hash: str | None = None,
):
    """Run one task through the pipeline.

    ``mode="standalone"`` applies the generated patch directly against
    ``root`` via ``git apply`` and runs ``SIMPLICIO_TEST_CMD`` locally. It is
    an explicit legacy adapter; automatic negotiation requires an explicit
    standalone-fallback opt-in before selecting it.

    ``mode="integrated"`` (issues #166, #167) never applies anything itself:
    it delegates to :func:`simplicio.pipeline_integrated.run_integrated`,
    which compiles a ``PlanDAG``/``EffectPlan`` bundle from the task's
    goal/criteria and hands each ``EffectPlan`` to ``effect_sink`` (required
    in this mode). ``dry_run_task`` is not consulted in this mode since
    nothing is ever applied to begin with.
    """
    from .execution_mode import (
        ExecutionInputError,
        blocked_input_profile,
        negotiate_execution_mode,
        prepare_execution_inputs,
        requested_mode,
        require_coordinator_attempt,
    )

    try:
        prepared = prepare_execution_inputs(
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
            runtime_handshake=runtime_handshake,
            attempt=integrated_attempt,
            attempt_id=attempt_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            context_handle=context_handle,
        )
    except ExecutionInputError as exc:
        result = _task_result(
            target,
            "",
            "",
            applied=False,
            status="blocked",
            warnings=[exc.code],
            blocked_preconditions=[
                {
                    "code": exc.code,
                    "reason": ("target_outside_root" if exc.code == "TARGET_OUTSIDE_SCOPE" else exc.code),
                    "message": str(exc),
                }
            ],
        )
        if task_spec is not None:
            result["task_spec_hash"] = task_spec.canonical_hash()
        result["execution_profile"] = blocked_input_profile(
            mode,
            exc,
            root=root,
            coordinator_kind=coordinator_kind,
            coordinator_id=coordinator_id,
        ).to_dict()
        return result
    context_snapshot = prepared.context_snapshot
    context_pack = prepared.context_pack
    execution_context = prepared.execution_context
    authorization = authorization or prepared.authorization
    effect_sink = cast(EffectSink | None, prepared.effect_sink)
    runtime_handshake = prepared.runtime_handshake
    integrated_attempt = prepared.attempt
    actual_root = Path(root).resolve()
    declared_repo_root = Path(repo_root if repo_root is not None else actual_root).resolve()
    declared_scope_root = scope_root if scope_root is not None else actual_root
    canonical_snapshot_id = str((context_snapshot or {}).get("snapshot_id") or "").strip()
    canonical_pack_hash = str((context_pack or {}).get("pack_hash") or "").strip()
    supplied_snapshot_id = None if context_snapshot_id is None else str(context_snapshot_id).strip()
    supplied_pack_hash = None if context_pack_hash is None else str(context_pack_hash).strip()
    snapshot_identity = canonical_snapshot_id
    # Issue #301 compatibility: older ContextPack payloads may omit the raw
    # pack_hash; integrated binding remains authoritative for that identity.
    pack_identity = canonical_pack_hash or supplied_pack_hash or ""
    attempt_identity = (
        attempt_id
        if attempt_id is not None
        else (integrated_attempt.attempt_id if integrated_attempt else "")
    )
    try:
        if declared_repo_root != actual_root:
            raise TaskContextError(
                "REPO_ROOT_MISMATCH",
                "declared repo_root must equal the actual mutation root",
            )
        task_context = TaskContext.from_values(
            repo_root=actual_root,
            scope_root=declared_scope_root,
            target=target,
            context_snapshot_id=snapshot_identity,
            context_pack_hash=pack_identity,
            attempt_id=attempt_identity,
            require_identity=False,
        )
    except TaskContextError as exc:
        result = _task_result(
            target,
            "",
            "",
            applied=False,
            status="blocked",
            warnings=[exc.code],
            blocked_preconditions=[
                {
                    "code": exc.code,
                    "reason": ("target_outside_root" if exc.code == "TARGET_OUTSIDE_SCOPE" else exc.code),
                    "message": str(exc),
                }
            ],
        )
        return result
    from .standalone_migration import (
        StandalonePolicy,
        emit_mutation_route,
        mutation_route_for_mode,
    )

    requested_execution_mode = requested_mode(mode, root)
    profile = negotiate_execution_mode(
        mode,
        root=root,
        runtime_handshake=runtime_handshake,
        context_snapshot=context_snapshot,
        effect_sink=effect_sink,
        coordinator_kind=coordinator_kind,
        coordinator_id=coordinator_id,
        # An explicit integrated run is already effect-safe: the Runtime
        # sink owns the effect boundary. Loop uses --dry-run-task while
        # preflighting this path, so it must not downgrade the typed handoff
        # to the legacy standalone profile.
        read_only=dry_run_task and requested_execution_mode != "integrated",
    )
    profile = require_coordinator_attempt(profile, integrated_attempt)
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
            profile.effective_mode == "integrated"
            and context_snapshot is not None
            and context_pack is not None
            and bool(snapshot_identity and pack_identity and attempt_identity)
        )
        or (
            profile.effective_mode == "standalone"
            and (
                strict_authority
                or context_snapshot is not None
                or context_pack is not None
                or supplied_snapshot_id is not None
                or supplied_pack_hash is not None
            )
        )
    )
    if identity_error is not None or identity_required:
        try:
            if identity_error is not None:
                raise identity_error
            task_context = TaskContext.from_values(
                repo_root=actual_root,
                scope_root=declared_scope_root,
                target=target,
                context_snapshot_id=snapshot_identity,
                context_pack_hash=pack_identity,
                attempt_id=attempt_identity,
                require_identity=identity_required,
            )
        except TaskContextError as exc:
            result = _task_result(
                target,
                "",
                "",
                applied=False,
                status="blocked",
                warnings=[exc.code],
                blocked_preconditions=[
                    {
                        "code": exc.code,
                        "reason": ("target_outside_root" if exc.code == "TARGET_OUTSIDE_SCOPE" else exc.code),
                        "message": str(exc),
                    }
                ],
            )
            result["execution_profile"] = profile.to_dict()
            if profile.effective_mode == "integrated":
                return _attach_contract_receipt(
                    result,
                    task_context=task_context,
                    route="blocked",
                    effective_mode=profile.effective_mode,
                    authorization=authorization,
                    verification_status="not_run",
                )
            return result
        if (
            profile.effective_mode == "integrated"
            and authorization is None
            and isinstance(effect_sink, RuntimeEffectSink)
        ):
            result = _task_result(
                target,
                "",
                "",
                applied=False,
                status="blocked",
                warnings=["AUTHORIZATION_REQUIRED"],
                blocked_preconditions=[
                    {
                        "code": "AUTHORIZATION_REQUIRED",
                        "message": "integrated mutation requires a Runtime EffectAuthorization",
                    }
                ],
            )
            result["execution_profile"] = profile.to_dict()
            return _attach_contract_receipt(
                result,
                task_context=task_context,
                route="blocked",
                effective_mode=profile.effective_mode,
                authorization=None,
                verification_status="not_run",
            )
    migration_policy = StandalonePolicy(**profile.standalone_policy)
    mutation_route = "blocked" if dry_run_task else mutation_route_for_mode(profile.effective_mode)
    emit_mutation_route(
        root=root,
        entrypoint="task",
        route=mutation_route,
        reason_code=profile.reason_code,
        policy=migration_policy,
    )
    emit_event(
        "execution_mode_selected",
        {
            "requested": profile.requested_mode,
            "effective": profile.effective_mode,
            "reason_code": profile.reason_code,
            "fallback_reason": profile.fallback_reason,
            "rollout": profile.rollout,
        },
        level="warning" if profile.effective_mode == "blocked" else "info",
        root=root,
    )
    _remember_patch_receipt(None)
    prompt = build_prompt(root, stack, goal, target, criteria, constraints)
    primary_test_cmd = os.environ.get("SIMPLICIO_TEST_CMD", "").strip() or None
    if primary_test_cmd is None and task_spec is not None:
        primary_test_cmd = next(
            (
                str(item.get("command", "")).strip()
                for item in task_spec.verification_commands
                if isinstance(item, dict) and str(item.get("command", "")).strip()
            ),
            None,
        )
    if profile.effective_mode == "blocked":
        blocker = execution_mode_blocker(profile)
        result = _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[profile.reason_code],
            blocked_preconditions=[blocker],
        )
        if task_spec is not None:
            result["task_spec_hash"] = task_spec.canonical_hash()
        result["execution_profile"] = profile.to_dict()
        return _attach_contract_receipt(
            result,
            task_context=task_context,
            route="blocked",
            effective_mode=profile.effective_mode,
            authorization=authorization,
            verification_status="not_run",
        )
    if task_spec is not None and profile.effective_mode != "integrated":
        result = _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=["TASK_SPEC_REQUIRES_INTEGRATED_MODE"],
            blocked_preconditions=[
                {
                    "code": "TASK_SPEC_REQUIRES_INTEGRATED_MODE",
                    "message": "typed TaskSpec input is accepted only by the integrated execution path",
                }
            ],
        )
        result["execution_profile"] = profile.to_dict()
        return result
    if profile.effective_mode == "integrated":
        from .standalone_migration import mutation_receipt, record_effect_unknown

        integrated_started_at = time.monotonic()
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
            attempt=integrated_attempt,
            task_spec=task_spec,
            coordinator_kind=coordinator_kind or "simplicio-dev-cli",
            session_id=session_id,
            turn_id=turn_id,
            attempt_number=attempt_number,
            subworkflow_id=subworkflow_id,
            deadline=deadline,
            policy_revision=policy_revision,
            base_hash=base_hash,
            context_pack_hash=supplied_pack_hash,
        )
        result["duration_ms"] = int((time.monotonic() - integrated_started_at) * 1000)
        result["execution_profile"] = profile.to_dict()
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
        observation_payload = result.get("observation")
        observation_payload = observation_payload if isinstance(observation_payload, dict) else {}
        result["mutation_receipt"] = mutation_receipt(
            "runtime_effect_api",
            entrypoint="task",
            plan=result.get("plan"),
            changeset=result.get("effects"),
            files=result.get("files_changed"),
            verification={
                "commands": verification_commands,
                "results": observation_payload.get("validation", []),
            },
            retry={
                "attempt": attempt_number,
                "max_attempts": 1,
                "retryable": observation_payload.get("retryability") == "retryable",
            },
            duration_ms=result.get("duration_ms"),
            final_status="applied" if result.get("applied") else str(result.get("status", "blocked")),
        )
        result = _attach_contract_receipt(
            result,
            task_context=task_context,
            route="runtime_effect_api",
            effective_mode=profile.effective_mode,
            authorization=authorization,
            verification_status=str(result.get("observation", {}).get("outcome", "unverified")),
            attempt=integrated_attempt,
            duration_ms=result.get("duration_ms"),
            retry={
                "attempt": attempt_number,
                "max_attempts": 1,
                "retryable": result.get("observation", {}).get("retryability") == "retryable",
            },
        )
        if result.get("observation", {}).get("outcome") == "effect_unknown":
            record_effect_unknown(root)
        return result
    if not dry_run_task and primary_test_cmd is None:
        blocker = {
            "code": "verification_command_missing",
            "message": "verification command missing; set SIMPLICIO_TEST_CMD before execution",
            "retryable": True,
            "next_action": "set SIMPLICIO_TEST_CMD to a real project verification command, then retry",
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
    if dry_run_task:
        blockers = _dry_run_preconditions(
            root,
            target,
            context_pack=context_pack,
            allow_degraded_mapper=requested_execution_mode == "standalone",
        )
        if blockers:
            warnings = [item["message"] for item in blockers]
            return _task_result(
                target,
                prompt,
                "",
                applied=False,
                status="blocked",
                warnings=warnings,
                blocked_preconditions=blockers,
                target_kind=target_kind(root, target),
            )
        if os.environ.get("SIMPLICIO_STANDALONE_PREFLIGHT", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return _task_result(
                target,
                prompt,
                "",
                applied=False,
                status="dry_run",
                warnings=["standalone_preflight_provider_skipped"],
                target_kind=target_kind(root, target),
            )
        # Issue #210 AC6: snapshot bound paths BEFORE generate() so an
        # out-of-band mutation that happens while the provider subprocess is
        # running (e.g. the target deleted mid-stall) is caught even though
        # nothing in the returned diff would ever mention it.
        bound_path_baseline = snapshot_bound_paths(root, bound_paths)
        output = generate(prompt)
        drift_warnings = bound_path_drift(root, bound_paths, bound_path_baseline)
        validation = validate_generated_output(
            output,
            bound_paths,
            mode=get_validation_mode(),
            root=root,
            repo_root=declared_repo_root,
            scope_root=declared_scope_root,
        )
        warnings = list(drift_warnings)
        if not validation.ok:
            warnings.append(validation.reason)
        return _task_result(
            target,
            prompt,
            output,
            applied=False,
            status="dry_run",
            warnings=warnings,
            target_kind=target_kind(root, target),
        )

    # Issue #107: structured "task_start" event — the dev-cli side of the
    # unified evidence flow a host loop's journal (e.g. simplicio-loop's
    # loop_journal.py) can consume. See observability.emit_event's contract.
    emit_event("task_start", {"target": target, "stack": stack, "goal": goal}, root=root)

    feedback = None
    last_output = ""
    last_validation = None
    last_log = ""
    last_verify_receipt: dict[str, Any] | None = None
    # Issue #93: impact-test tracking across attempts
    impact_results: dict[str, Any] | None = None
    attempts_limit = _resolve_max_attempts()
    # Issue #219: whole-attempt (not just provider-shell-out) progress/deadline tracking.
    task_started_at = time.monotonic()
    task_deadline = _task_deadline_s()
    last_failure_fingerprint: str | None = None
    consecutive_same_failure = 0
    for t in range(1, attempts_limit + 1):
        if not quiet:
            _model = os.environ.get("SIMPLICIO_MODEL", "")
            _base = os.environ.get("SIMPLICIO_BASE_URL", "")
            _prov = (
                _provider_id(_model, _base)
                if (_model or _base)
                else os.environ.get("SIMPLICIO_PROVIDER", "unknown")
            )
            info(f"--- attempt {t} (provider={_prov}, validation={get_validation_mode()}) ---")
        elapsed_before_attempt = time.monotonic() - task_started_at
        emit_event(
            "task_progress",
            {
                "target": target,
                "attempt": t,
                "stage": "generate",
                "elapsed_s": round(elapsed_before_attempt, 2),
            },
            root=root,
        )
        if task_deadline and elapsed_before_attempt >= task_deadline:
            reason = (
                f"task exceeded its configured deadline ({task_deadline:.0f}s, "
                f"SIMPLICIO_TASK_DEADLINE_S) with no successful attempt; stopping after "
                f"{t - 1} attempt(s) instead of hanging indefinitely"
            )
            emit_event(
                "task_no_progress",
                {"target": target, "attempts": t - 1, "elapsed_s": round(elapsed_before_attempt, 2)},
                level="warning",
                root=root,
            )
            return _task_result(
                target,
                prompt,
                last_output,
                applied=False,
                status="stalled",
                warnings=[reason],
                verify=last_verify_receipt,
                impact=impact_results,
            )
        # Issue #210 AC6/AC5: snapshot bound paths right before this attempt's
        # generate() call. If the provider subprocess stalls or is killed by
        # the bounded-timeout path in providers._shell_out and a bound file
        # is deleted/mutated out-of-band in the meantime, this is caught here
        # — before any apply is attempted against a corrupted worktree — and
        # regardless of what the (possibly empty) returned diff claims.
        bound_path_baseline = snapshot_bound_paths(root, bound_paths)
        try:
            output = generate(prompt, feedback)
        except ProviderExecutionError as exc:
            receipt = dict(exc.receipt)
            emit_event("provider_terminal", receipt, level="warning", root=root)
            emit_event(
                "task_terminal",
                {
                    "target": target,
                    "attempt": t,
                    "status": receipt.get("status", "failed"),
                    "reason_code": receipt.get("reason_code", "provider_failure"),
                    "provider_terminal": receipt,
                },
                level="warning",
                root=root,
            )
            result = _task_result(
                target,
                prompt,
                "",
                applied=False,
                status=receipt.get("status", "failed"),
                warnings=[receipt.get("message", "provider execution failed")],
                blocked_preconditions=[
                    {
                        "reason": receipt.get("reason_code", "provider_failure"),
                        "message": receipt.get("message", "provider execution failed"),
                        "next_surface": "provider",
                    }
                ],
            )
            result["provider_terminal"] = receipt
            return result
        except SystemExit as exc:
            # Some test runners and plugin hosts reload ``providers`` while
            # keeping this module alive. The reloaded ProviderExecutionError
            # is still a SystemExit carrying the same stable receipt contract,
            # but it no longer has identical class identity.
            reloaded_receipt = getattr(exc, "receipt", None)
            if isinstance(reloaded_receipt, dict):
                receipt = dict(reloaded_receipt)
                emit_event("provider_terminal", receipt, level="warning", root=root)
                emit_event(
                    "task_terminal",
                    {
                        "target": target,
                        "attempt": t,
                        "status": receipt.get("status", "failed"),
                        "reason_code": receipt.get("reason_code", "provider_failure"),
                        "provider_terminal": receipt,
                    },
                    level="warning",
                    root=root,
                )
                result = _task_result(
                    target,
                    prompt,
                    "",
                    applied=False,
                    status=receipt.get("status", "failed"),
                    warnings=[receipt.get("message", "provider execution failed")],
                    blocked_preconditions=[
                        {
                            "reason": receipt.get("reason_code", "provider_failure"),
                            "message": receipt.get("message", "provider execution failed"),
                            "next_surface": "provider",
                        }
                    ],
                )
                result["provider_terminal"] = receipt
                return result
            # Issue #219: #210's bounded shell-out raises SystemExit on a stall;
            # previously that crashed run_task uncaught with no receipt at all.
            reason = str(exc) or "provider produced no progress before its bounded deadline"
            emit_event(
                "task_no_progress",
                {"target": target, "attempt": t, "reason": reason},
                level="warning",
                root=root,
            )
            return _task_result(
                target,
                prompt,
                last_output,
                applied=False,
                status="stalled",
                warnings=[reason],
                verify=last_verify_receipt,
                impact=impact_results,
            )
        drift_warnings = bound_path_drift(root, bound_paths, bound_path_baseline)
        if drift_warnings:
            emit_event(
                "validation_fail",
                {"target": target, "attempt": t, "warnings": drift_warnings},
                level="warning",
                root=root,
            )
            return _task_result(
                target,
                prompt,
                output,
                applied=False,
                status="blocked",
                warnings=drift_warnings,
                blocked_preconditions=[
                    {
                        "code": "bound_path_out_of_band_mutation",
                        "message": "; ".join(drift_warnings),
                    }
                ],
            )
        last_output = output or ""
        last_validation = validate_generated_output(
            output,
            bound_paths,
            root=root,
            repo_root=declared_repo_root,
            scope_root=declared_scope_root,
        )
        attempt = _apply_and_test_attempt(
            output,
            root,
            bound_paths,
            promote_on_success=False,
            repo_root=declared_repo_root,
            scope_root=declared_scope_root,
        )
        ok, log = attempt.ok, attempt.log
        last_verify_receipt = _LAST_VERIFY_RECEIPT
        last_log = log
        attempt_tokens = estimate_tokens(prompt) + estimate_tokens(output)
        log_run(
            root,
            {
                "mode": "pipeline",
                "attempt": t,
                "ok": ok,
                "failure_class": "none" if ok else classify_failure(log).kind,
                "tokens_estimated": attempt_tokens,
                "target": target,
                "stack": stack,
            },
        )
        emit_event(
            "token_usage",
            {"target": target, "attempt": t, "tokens_estimated": attempt_tokens},
            root=root,
        )
        if ok:
            # Issue #93: run impact tests after the primary test passes
            files_changed = extract_changed_files(output)
            candidate_root = str(attempt.tx.candidate) if attempt.tx is not None else root
            impact_results = _run_impact_tests_compat(candidate_root, files_changed, primary_test_cmd)
            impact_result = (
                impact_results.get("result", IMPACT_RESULT_UNVERIFIED)
                if impact_results
                else IMPACT_RESULT_UNVERIFIED
            )

            if impact_result == IMPACT_RESULT_FAILED:
                # Impact test failure → retry as a verify failure
                ok = False
                log = (
                    "impact test failure — callers: "
                    + ", ".join(impact_results.get("callers", []))[:200]
                    + "\n"
                    + impact_results.get("output_tail", "")[:1500]
                )
                if not quiet:
                    info("impact test failed: %s", log[:300])
            elif impact_result in (IMPACT_RESULT_PASSED, IMPACT_RESULT_NOT_NEEDED):
                # Impact tests passed or nothing to verify → done
                try:
                    if attempt.tx is not None and attempt.receipt is not None:
                        attempt.tx.promote(attempt.receipt)
                except Exception as exc:
                    ok = False
                    log = str(exc)
                    last_log = log
                else:
                    if not quiet:
                        info("PASSED the contract (impact verified). DONE.")
                    emit_event(
                        "task_complete",
                        {"target": target, "attempt": t, "impact": "verified"},
                        root=root,
                        tokens_saved=0,
                    )
                    result = _task_result(
                        target,
                        prompt,
                        output,
                        applied=True,
                        verify=last_verify_receipt,
                        impact=impact_results,
                    )
                    result["execution_profile"] = profile.to_dict()
                    result = _attach_contract_receipt(
                        result,
                        task_context=task_context,
                        route=mutation_route,
                        effective_mode=profile.effective_mode,
                        authorization=authorization,
                        verification_status=(
                            "verified"
                            if result.get("verify", {}).get("status") == "verified"
                            else "unverified"
                        ),
                    )
                    return result
            else:
                ok = False
                log = (
                    "impact verification unavailable — "
                    + impact_results.get("status", "unknown")
                    + ": "
                    + impact_results.get("error", "no executable impact receipt")
                )
                if not quiet:
                    info("impact verification unavailable: %s", log[:300])
                # The patch already passed its primary test, but the impact
                # receipt is missing.  Stop fail-closed here; retrying the
                # identical diff would reapply against the now-mutated file
                # and obscure the real blocker with a secondary hunk error.
                emit_event(
                    "validation_fail",
                    {"target": target, "attempts": t, "warnings": [log[:500]]},
                    level="warning",
                    root=root,
                )
                return _task_result(
                    target,
                    prompt,
                    output,
                    applied=False,
                    warnings=[log],
                    verify=last_verify_receipt,
                    impact=impact_results,
                )

        # ── Primary test or impact test failed — try fixers ──
        fixer_result = try_static_fixers(log, root)
        if fixer_result.applied:
            attempt = _apply_and_test_attempt(
                output,
                root,
                bound_paths,
                promote_on_success=False,
                repo_root=declared_repo_root,
                scope_root=declared_scope_root,
            )
            ok, fixed_log = attempt.ok, attempt.log
            last_verify_receipt = _LAST_VERIFY_RECEIPT
            log_run(
                root,
                {
                    "mode": "fixer",
                    "attempt": t,
                    "ok": ok,
                    "fixer": fixer_result.fixer,
                    "details": fixer_result.details,
                    "failure_class": "none" if ok else classify_failure(fixed_log).kind,
                    "target": target,
                    "stack": stack,
                },
            )
            last_log = fixed_log
            log = fixed_log if ok else f"{fixer_result.details}\n{fixed_log}"
            if ok:
                # Re-run impact tests after fixer pass
                files_changed = extract_changed_files(output)
                candidate_root = str(attempt.tx.candidate) if attempt.tx is not None else root
                impact_results = _run_impact_tests_compat(candidate_root, files_changed, primary_test_cmd)
                impact_result = (
                    impact_results.get("result", IMPACT_RESULT_UNVERIFIED)
                    if impact_results
                    else IMPACT_RESULT_UNVERIFIED
                )

                if impact_result == IMPACT_RESULT_FAILED:
                    ok = False
                    log = (
                        "impact test failure after fixer — callers: "
                        + ", ".join(impact_results.get("callers", []))[:200]
                        + "\n"
                        + impact_results.get("output_tail", "")[:1500]
                    )
                    if not quiet:
                        info("impact test failed after fixer: %s", log[:300])
                elif impact_result in (IMPACT_RESULT_PASSED, IMPACT_RESULT_NOT_NEEDED):
                    try:
                        if attempt.tx is not None and attempt.receipt is not None:
                            attempt.tx.promote(attempt.receipt)
                    except Exception as exc:
                        ok = False
                        log = str(exc)
                        last_log = log
                    else:
                        if not quiet:
                            suffix = (
                                " (impact verified)"
                                if impact_result == IMPACT_RESULT_PASSED
                                else " (impact unverifiable)"
                            )
                            info(f"PASSED after static fixer {fixer_result.fixer}.{suffix} DONE.")
                        emit_event(
                            "task_complete",
                            {"target": target, "attempt": t, "fixer": fixer_result.fixer},
                            root=root,
                            tokens_saved=0,
                        )
                        result = _task_result(
                            target,
                            prompt,
                            output,
                            applied=True,
                            verify=last_verify_receipt,
                            impact=impact_results,
                        )
                        result["execution_profile"] = profile.to_dict()
                        result = _attach_contract_receipt(
                            result,
                            task_context=task_context,
                            route=mutation_route,
                            effective_mode=profile.effective_mode,
                            authorization=authorization,
                            verification_status=(
                                "verified"
                                if result.get("verify", {}).get("status") == "verified"
                                else "unverified"
                            ),
                        )
                        return result
                else:
                    ok = False
                    log = "impact verification unavailable after fixer — " + (impact_results or {}).get(
                        "status", "unknown"
                    )
        if not quiet:
            info("failed: %s", log[:300])
        # Issue #219: escalate once the same failure fingerprint repeats.
        fingerprint = _failure_fingerprint(log)
        if fingerprint == last_failure_fingerprint:
            consecutive_same_failure += 1
        else:
            last_failure_fingerprint = fingerprint
            consecutive_same_failure = 1
        feedback = build_retry_feedback(t + 1, last_validation, log)
        retry_feedback = set_prompt_retry_delta(
            reason="verification-failed",
            failure_class=classify_failure(log).kind,
            diagnostics=feedback,
            affected_files=extract_changed_files(last_output),
        )
        if retry_feedback:
            feedback = retry_feedback
        if consecutive_same_failure >= _retry_escalation_after():
            emit_event(
                "retry_escalated",
                {"target": target, "attempt": t, "consecutive_same_failure": consecutive_same_failure},
                level="warning",
                root=root,
            )
            feedback = (
                f"{feedback}\n\nESCALATION: the last {consecutive_same_failure} attempts failed with "
                "the same failure signature. Do not repeat the previous diff verbatim. Narrow the "
                "change to the smallest possible localized edit (a single hunk touching the minimum "
                "number of lines) and use a different approach than the previous attempt."
            )
    if not quiet:
        info("attempts exhausted — manual review needed.")
    warnings = []
    if last_validation and not last_validation.ok:
        warnings.append(last_validation.reason)
    elif last_log:
        warnings.append(last_log[:500])
    emit_event(
        "validation_fail",
        {"target": target, "attempts": attempts_limit, "warnings": warnings[:1]},
        level="warning",
        root=root,
    )
    return _task_result(
        target,
        prompt,
        last_output,
        applied=False,
        warnings=warnings,
        verify=last_verify_receipt,
        impact=impact_results,
    )


def run(root, stack, goal, target, criteria, constraints, bound_paths=None, **kwargs: Any):
    result = run_task(
        root,
        stack,
        goal,
        target,
        criteria,
        constraints,
        bound_paths=bound_paths,
        **kwargs,
    )
    if result["applied"]:
        return result
    return None


def run_task_spec(root, stack, task_spec: TaskSpec, **kwargs: Any) -> dict[str, Any]:
    """Execute one validated TaskSpec without flattening its typed payload.

    This is the public API counterpart to ``simplicio-py task --task-spec``.
    The narrative fields are used only for the legacy function signature; the
    original object is passed unchanged to the integrated compiler.
    """
    if not isinstance(task_spec, TaskSpec):
        raise TypeError("run_task_spec requires a simplicio.task_spec.TaskSpec")
    narrative = task_spec.narrative
    goal = str(narrative.get("goal") or narrative.get("want") or task_spec.functionality or task_spec.task_id)
    criteria = "\n".join(
        str(item.get("text") or item.get("then") or item["id"]) for item in task_spec.acceptance_criteria
    )
    constraints = "\n".join(
        str(item.get("text") or item.get("description") or item.get("id", ""))
        for item in task_spec.business_rules
    )
    return run_task(
        root,
        stack,
        goal,
        task_spec.task_id,
        criteria,
        constraints,
        task_spec=task_spec,
        **kwargs,
    )


async def run_tasks_async(
    task_specs: list[dict[str, Any]],
    *,
    concurrency: int | None = None,
) -> list[dict[str, Any] | BaseException]:
    """Run several INDEPENDENT tasks concurrently (issue #212).

    ``task_specs`` is a list of kwargs dicts accepted by :func:`run_task`
    (``root``, ``stack``, ``goal``, ``target``, ``criteria``,
    ``constraints``, and any of its optional keyword arguments). Each task
    runs ``run_task`` unchanged inside a bounded worker thread — see
    :mod:`simplicio.runtime_async` for why the pipeline internals are not
    rewritten as native async. Concurrency defaults to
    ``SIMPLICIO_ASYNC_CONCURRENCY`` (or
    :data:`simplicio.runtime_async.DEFAULT_CONCURRENCY`) when not given
    explicitly.

    This function never applies anything by itself and never mutates
    shared retry state across tasks — each ``run_task`` call is fully
    independent, which is what makes concurrent dispatch safe here. A
    failing task's exception is returned in place of its result (never
    raised out of this call), so a batch failure never loses the results
    of its siblings; callers should check each entry with
    ``isinstance(entry, BaseException)``.
    """
    from .runtime_async import gather_bounded, run_sync_in_thread

    def _make_thunk(spec: dict[str, Any]) -> Any:
        return lambda: run_sync_in_thread(run_task, **spec)

    thunks = [_make_thunk(spec) for spec in task_specs]
    return await gather_bounded(thunks, concurrency=concurrency)
