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
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .adaptive import get_validation_mode
from .atomic_execution import AttemptContext
from .execution_receipts import execution_mode_blocker
from .mapper import map_ask
from .observability import emit_event, estimate_tokens, info, log_run
from .pipeline_fixers import try_static_fixers
from .pipeline_integrated import run_integrated_route
from .pipeline_preparation import (
    PreparedPipeline,
    TaskPreflight,
    prepare_pipeline_inputs,
    prepare_task_preflight,
)
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
from .pipeline_state import result_trace
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
        final_status=_final_receipt_status(result, dry_run=result.get("status") == "dry_run"),
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


def _publish_execution_mode_selection(
    *, root: str, profile: Any, proposal_only: bool, dry_run_task: bool
) -> tuple[Any, str]:
    """Publish route selection and return the policy consumed by later stages."""
    from .standalone_migration import StandalonePolicy, emit_mutation_route, mutation_route_for_mode

    policy = StandalonePolicy(**profile.standalone_policy)
    route = "blocked" if dry_run_task else mutation_route_for_mode(profile.effective_mode)
    if proposal_only:
        return policy, route
    emit_mutation_route(
        root=root,
        entrypoint="task",
        route=route,
        reason_code=profile.reason_code,
        policy=policy,
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
    return policy, route


def _promote_transaction(attempt: Any) -> tuple[bool, str | None]:
    """Promote a verified attempt and normalize transaction failures."""
    try:
        if attempt.tx is not None and attempt.receipt is not None:
            attempt.tx.promote(attempt.receipt)
    except Exception as exc:
        return False, str(exc)
    return True, None


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
            "route": "standalone",
            "runtime_gated": False,
            "legacy": False,
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


def _run_dry_run_task(
    *,
    root: str | Path,
    target: str,
    prompt: str,
    context_pack: dict | None,
    requested_execution_mode: str | None,
    bound_paths: list[str] | None,
    declared_repo_root: str,
    declared_scope_root: str,
) -> dict[str, Any]:
    """Run the standalone dry-run phase without entering the mutation loop."""
    blockers = _dry_run_preconditions(
        root,
        target,
        context_pack=context_pack,
        allow_degraded_mapper=requested_execution_mode == "standalone",
    )
    if blockers:
        return _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[item["message"] for item in blockers],
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
    # Bind paths before generate() so an out-of-band mutation during provider
    # execution is caught even when the returned diff does not mention it.
    bound_path_baseline = snapshot_bound_paths(str(root), bound_paths)
    output = generate(prompt)
    drift_warnings = bound_path_drift(str(root), bound_paths, bound_path_baseline)
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


def _blocked_preflight_result(
    target: str,
    error: TaskContextError,
    *,
    profile: Any | None = None,
    task_context: TaskContext | None = None,
    authorization: EffectAuthorization | None = None,
    include_reason: bool = True,
) -> dict[str, Any]:
    blocked = {
        "code": error.code,
        "message": str(error),
    }
    if include_reason:
        blocked["reason"] = "target_outside_root" if error.code == "TARGET_OUTSIDE_SCOPE" else error.code
    result = _task_result(
        target,
        "",
        "",
        applied=False,
        status="blocked",
        warnings=[error.code],
        blocked_preconditions=[blocked],
    )
    if profile is None:
        return result
    result["execution_profile"] = profile.to_dict()
    if profile.effective_mode == "integrated" and task_context is not None:
        return _attach_contract_receipt(
            result,
            task_context=task_context,
            route="blocked",
            effective_mode=profile.effective_mode,
            authorization=authorization,
            verification_status="not_run",
        )
    return result


def _resolve_task_preflight(
    preflight: TaskPreflight,
    *,
    target: str,
    authorization: EffectAuthorization | None,
    effect_sink: EffectSink | None,
    proposal_only: bool,
) -> tuple[TaskContext | None, dict[str, Any] | None]:
    if preflight.context_error is not None:
        return None, _blocked_preflight_result(target, preflight.context_error)
    task_context = preflight.task_context
    assert task_context is not None
    if preflight.identity_error is not None or preflight.identity_required:
        try:
            if preflight.identity_error is not None:
                raise preflight.identity_error
            task_context = TaskContext.from_values(
                repo_root=preflight.pipeline_input.actual_root,
                scope_root=preflight.pipeline_input.declared_scope_root,
                target=target,
                context_snapshot_id=preflight.pipeline_input.snapshot_identity,
                context_pack_hash=preflight.pipeline_input.pack_identity,
                attempt_id=preflight.pipeline_input.attempt_identity,
                require_identity=preflight.identity_required,
            )
        except TaskContextError as exc:
            return None, _blocked_preflight_result(
                target,
                exc,
                profile=preflight.profile,
                task_context=task_context,
                authorization=authorization,
            )
        if (
            preflight.profile.effective_mode == "integrated"
            and authorization is None
            and isinstance(effect_sink, RuntimeEffectSink)
            and not proposal_only
        ):
            error = TaskContextError(
                "AUTHORIZATION_REQUIRED",
                "integrated mutation requires a Runtime EffectAuthorization",
            )
            result = _blocked_preflight_result(
                target,
                error,
                profile=preflight.profile,
                task_context=task_context,
                authorization=None,
                include_reason=False,
            )
            return None, result
    return task_context, None


def _route_prepared_task(
    *,
    root: str | Path,
    stack: str,
    goal: str,
    target: str,
    criteria: str,
    constraints: str,
    prompt: str,
    primary_test_cmd: str | None,
    profile: Any,
    task_spec: TaskSpec | None,
    effect_sink: EffectSink | None,
    authorization: EffectAuthorization | None,
    context_snapshot: dict | None,
    context_pack: dict | None,
    context_delta: dict | None,
    execution_context: dict | None,
    context_refresh: bool,
    integrated_attempt: AttemptContext | None,
    coordinator_kind: str | None,
    session_id: str,
    turn_id: str,
    attempt_number: int,
    subworkflow_id: str,
    deadline: str | None,
    policy_revision: str,
    base_hash: str,
    supplied_pack_hash: str | None,
    proposal_only: bool,
    task_context: TaskContext,
) -> dict[str, Any] | None:
    """Resolve terminal route decisions before entering the mutation loop."""
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
        return run_integrated_route(
            root=str(root),
            stack=stack,
            goal=goal,
            target=target,
            criteria=criteria,
            constraints=constraints,
            prompt=prompt,
            primary_test_cmd=primary_test_cmd,
            effect_sink=effect_sink,
            authorization=authorization,
            context_snapshot=context_snapshot,
            context_pack=context_pack,
            context_delta=context_delta,
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
            proposal_only=proposal_only,
            execution_profile=profile.to_dict(),
            task_context=task_context,
            attach_contract_receipt=_attach_contract_receipt,
            final_receipt_status=_final_receipt_status,
        )
    if primary_test_cmd is None:
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
    return None


def _generate_attempt_output(
    *,
    root: str | Path,
    target: str,
    prompt: str,
    feedback: str | None,
    bound_paths: list[str] | None,
    attempt_number: int,
    last_output: str,
    last_verify_receipt: dict[str, Any] | None,
    impact_results: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Generate one bounded attempt and return output or a terminal result."""
    bound_path_baseline = snapshot_bound_paths(str(root), bound_paths)
    try:
        output = generate(prompt, feedback)
    except ProviderExecutionError as exc:
        receipt = dict(exc.receipt)
        emit_event("provider_terminal", receipt, level="warning", root=str(root))
        emit_event(
            "task_terminal",
            {
                "target": target,
                "attempt": attempt_number,
                "status": receipt.get("status", "failed"),
                "reason_code": receipt.get("reason_code", "provider_failure"),
                "provider_terminal": receipt,
            },
            level="warning",
            root=str(root),
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
        return None, result
    except SystemExit as exc:
        reloaded_receipt = getattr(exc, "receipt", None)
        if isinstance(reloaded_receipt, dict):
            receipt = dict(reloaded_receipt)
            emit_event("provider_terminal", receipt, level="warning", root=str(root))
            emit_event(
                "task_terminal",
                {
                    "target": target,
                    "attempt": attempt_number,
                    "status": receipt.get("status", "failed"),
                    "reason_code": receipt.get("reason_code", "provider_failure"),
                    "provider_terminal": receipt,
                },
                level="warning",
                root=str(root),
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
            return None, result
        reason = str(exc) or "provider produced no progress before its bounded deadline"
        emit_event(
            "task_no_progress",
            {"target": target, "attempt": attempt_number, "reason": reason},
            level="warning",
            root=str(root),
        )
        return None, _task_result(
            target,
            prompt,
            last_output,
            applied=False,
            status="stalled",
            warnings=[reason],
            verify=last_verify_receipt,
            impact=impact_results,
        )
    drift_warnings = bound_path_drift(str(root), bound_paths, bound_path_baseline)
    if drift_warnings:
        emit_event(
            "validation_fail",
            {"target": target, "attempt": attempt_number, "warnings": drift_warnings},
            level="warning",
            root=str(root),
        )
        return None, _task_result(
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
    return output, None


@dataclass(frozen=True)
class _FixerAttemptOutcome:
    """Result of one optional static-fixer retry pass."""

    ok: bool
    log: str
    verify_receipt: dict[str, Any] | None
    impact: dict[str, Any] | None
    terminal_result: dict[str, Any] | None = None


def _run_static_fixer_attempt(
    *,
    output: str,
    log: str,
    root: str | Path,
    target: str,
    stack: str,
    prompt: str,
    bound_paths: list[str] | None,
    declared_repo_root: str,
    declared_scope_root: str,
    scope_root: str | os.PathLike[str] | None,
    primary_test_cmd: str | None,
    attempt_number: int,
    quiet: bool,
    profile: Any,
    mutation_route: str,
    task_context: TaskContext,
    authorization: EffectAuthorization | None,
) -> _FixerAttemptOutcome | None:
    """Run, verify and promote one authorized static-fixer result."""
    fixer_paths = authorized_path_warnings(
        extract_changed_files(output),
        root=root,
        repo_root=declared_repo_root,
        scope_root=declared_scope_root,
    )
    fixer_result = None if fixer_paths or scope_root is not None else try_static_fixers(log, root)
    if fixer_result is None or not fixer_result.applied:
        return None
    attempt = _apply_and_test_attempt(
        output,
        str(root),
        bound_paths,
        promote_on_success=False,
        repo_root=declared_repo_root,
        scope_root=declared_scope_root,
    )
    ok, fixed_log = attempt.ok, attempt.log
    verify_receipt = _LAST_VERIFY_RECEIPT
    log_run(
        str(root),
        {
            "mode": "fixer",
            "attempt": attempt_number,
            "ok": ok,
            "fixer": fixer_result.fixer,
            "details": fixer_result.details,
            "failure_class": "none" if ok else classify_failure(fixed_log).kind,
            "target": target,
            "stack": stack,
        },
    )
    effective_log = fixed_log if ok else f"{fixer_result.details}\n{fixed_log}"
    if not ok:
        return _FixerAttemptOutcome(False, effective_log, verify_receipt, None)

    files_changed = extract_changed_files(output)
    candidate_root = str(attempt.tx.candidate) if attempt.tx is not None else root
    impact = _run_impact_tests_compat(candidate_root, files_changed, primary_test_cmd)
    impact_result = impact.get("result", IMPACT_RESULT_UNVERIFIED) if impact else IMPACT_RESULT_UNVERIFIED
    if impact_result == IMPACT_RESULT_FAILED:
        failure = (
            "impact test failure after fixer — callers: "
            + ", ".join(impact.get("callers", []))[:200]
            + "\n"
            + impact.get("output_tail", "")[:1500]
        )
        if not quiet:
            info("impact test failed after fixer: %s", failure[:300])
        return _FixerAttemptOutcome(False, failure, verify_receipt, impact)
    if impact_result not in (IMPACT_RESULT_PASSED, IMPACT_RESULT_NOT_NEEDED):
        failure = "impact verification unavailable after fixer — " + (impact or {}).get("status", "unknown")
        return _FixerAttemptOutcome(False, failure, verify_receipt, impact)

    promoted, promotion_error = _promote_transaction(attempt)
    if not promoted:
        return _FixerAttemptOutcome(
            False, promotion_error or "transaction promotion failed", verify_receipt, impact
        )
    if not quiet:
        suffix = " (impact verified)" if impact_result == IMPACT_RESULT_PASSED else " (impact unverifiable)"
        info(f"PASSED after static fixer {fixer_result.fixer}.{suffix} DONE.")
    emit_event(
        "task_complete",
        {"target": target, "attempt": attempt_number, "fixer": fixer_result.fixer},
        root=str(root),
        tokens_saved=0,
    )
    result = _task_result(
        target,
        prompt,
        output,
        applied=True,
        verify=verify_receipt,
        impact=impact,
    )
    result["execution_profile"] = profile.to_dict()
    terminal_result = _attach_contract_receipt(
        result,
        task_context=task_context,
        route=mutation_route,
        effective_mode=profile.effective_mode,
        authorization=authorization,
        verification_status=(
            "verified" if result.get("verify", {}).get("status") == "verified" else "unverified"
        ),
    )
    return _FixerAttemptOutcome(True, "", verify_receipt, impact, terminal_result)


def _handle_primary_attempt_success(
    *,
    output: str,
    attempt: Any,
    root: str | Path,
    target: str,
    prompt: str,
    primary_test_cmd: str | None,
    attempt_number: int,
    quiet: bool,
    verify_receipt: dict[str, Any] | None,
    profile: Any,
    mutation_route: str,
    task_context: TaskContext,
    authorization: EffectAuthorization | None,
) -> tuple[bool, str, dict[str, Any] | None, dict[str, Any] | None]:
    """Handle impact verification and promotion after primary verification passes."""
    files_changed = extract_changed_files(output)
    candidate_root = str(attempt.tx.candidate) if attempt.tx is not None else root
    impact = _run_impact_tests_compat(candidate_root, files_changed, primary_test_cmd)
    impact_result = impact.get("result", IMPACT_RESULT_UNVERIFIED) if impact else IMPACT_RESULT_UNVERIFIED
    if impact_result == IMPACT_RESULT_FAILED:
        failure = (
            "impact test failure — callers: "
            + ", ".join(impact.get("callers", []))[:200]
            + "\n"
            + impact.get("output_tail", "")[:1500]
        )
        if not quiet:
            info("impact test failed: %s", failure[:300])
        return False, failure, impact, None
    if impact_result not in (IMPACT_RESULT_PASSED, IMPACT_RESULT_NOT_NEEDED):
        failure = (
            "impact verification unavailable — "
            + impact.get("status", "unknown")
            + ": "
            + impact.get("error", "no executable impact receipt")
        )
        if not quiet:
            info("impact verification unavailable: %s", failure[:300])
        emit_event(
            "validation_fail",
            {"target": target, "attempts": attempt_number, "warnings": [failure[:500]]},
            level="warning",
            root=str(root),
        )
        terminal = _task_result(
            target,
            prompt,
            output,
            applied=False,
            warnings=[failure],
            verify=verify_receipt,
            impact=impact,
        )
        return False, failure, impact, terminal
    promoted, promotion_error = _promote_transaction(attempt)
    if not promoted:
        return False, promotion_error or "transaction promotion failed", impact, None
    if not quiet:
        info("PASSED the contract (impact verified). DONE.")
    emit_event(
        "task_complete",
        {"target": target, "attempt": attempt_number, "impact": "verified"},
        root=str(root),
        tokens_saved=0,
    )
    result = _task_result(
        target,
        prompt,
        output,
        applied=True,
        verify=verify_receipt,
        impact=impact,
    )
    result["execution_profile"] = profile.to_dict()
    terminal = _attach_contract_receipt(
        result,
        task_context=task_context,
        route=mutation_route,
        effective_mode=profile.effective_mode,
        authorization=authorization,
        verification_status=(
            "verified" if result.get("verify", {}).get("status") == "verified" else "unverified"
        ),
    )
    return True, "", impact, terminal


def _build_retry_feedback_state(
    *,
    root: str | Path,
    target: str,
    attempt_number: int,
    quiet: bool,
    last_validation: Any,
    log: str,
    last_output: str,
    last_failure_fingerprint: str | None,
    consecutive_same_failure: int,
) -> tuple[str, int, str]:
    """Build bounded retry diagnostics and escalation feedback for one failure."""
    fingerprint = _failure_fingerprint(log)
    if fingerprint == last_failure_fingerprint:
        consecutive_same_failure += 1
    else:
        last_failure_fingerprint = fingerprint
        consecutive_same_failure = 1
    feedback = build_retry_feedback(attempt_number + 1, last_validation, log)
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
            {
                "target": target,
                "attempt": attempt_number,
                "consecutive_same_failure": consecutive_same_failure,
            },
            level="warning",
            root=str(root),
        )
        feedback = (
            f"{feedback}\n\nESCALATION: the last {consecutive_same_failure} attempts failed with "
            "the same failure signature. Do not repeat the previous diff verbatim. Narrow the "
            "change to the smallest possible localized edit (a single hunk touching the minimum "
            "number of lines) and use a different approach than the previous attempt."
        )
    return last_failure_fingerprint, consecutive_same_failure, feedback


def _build_attempts_exhausted_result(
    *,
    root: str | Path,
    target: str,
    prompt: str,
    quiet: bool,
    last_output: str,
    last_validation: Any,
    last_log: str,
    last_verify_receipt: dict[str, Any] | None,
    impact_results: dict[str, Any] | None,
    attempts_limit: int,
) -> dict[str, Any]:
    """Build the fail-closed terminal result after all attempts are exhausted."""
    if not quiet:
        info("attempts exhausted — manual review needed.")
    warnings: list[str] = []
    if last_validation and not last_validation.ok:
        warnings.append(last_validation.reason)
    elif last_log:
        warnings.append(last_log[:500])
    emit_event(
        "validation_fail",
        {"target": target, "attempts": attempts_limit, "warnings": warnings[:1]},
        level="warning",
        root=str(root),
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


def _run_attempt_loop(
    *,
    root,
    stack,
    target,
    prompt,
    primary_test_cmd,
    bound_paths,
    quiet,
    profile,
    mutation_route,
    task_context,
    authorization,
    declared_repo_root,
    declared_scope_root,
    scope_root,
):
    """Run generation, application, fixer and retry state for one task."""
    feedback = None
    last_output = ""
    last_validation = None
    last_log = ""
    last_verify_receipt: dict[str, Any] | None = None
    impact_results: dict[str, Any] | None = None
    attempts_limit = _resolve_max_attempts()
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
            info("--- attempt %s (provider=%s, validation=%s) ---", t, _prov, get_validation_mode())
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
                "SIMPLICIO_TASK_DEADLINE_S) with no successful attempt; stopping after "
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
        output, terminal_result = _generate_attempt_output(
            root=root,
            target=target,
            prompt=prompt,
            feedback=feedback,
            bound_paths=bound_paths,
            attempt_number=t,
            last_output=last_output,
            last_verify_receipt=last_verify_receipt,
            impact_results=impact_results,
        )
        if terminal_result is not None:
            return terminal_result
        assert output is not None
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
            ok, log, impact_results, terminal_result = _handle_primary_attempt_success(
                output=output,
                attempt=attempt,
                root=root,
                target=target,
                prompt=prompt,
                primary_test_cmd=primary_test_cmd,
                attempt_number=t,
                quiet=quiet,
                verify_receipt=last_verify_receipt,
                profile=profile,
                mutation_route=mutation_route,
                task_context=task_context,
                authorization=authorization,
            )
            if terminal_result is not None:
                return terminal_result
            last_log = log

        fixer_outcome = _run_static_fixer_attempt(
            output=output,
            log=log,
            root=root,
            target=target,
            stack=stack,
            prompt=prompt,
            bound_paths=bound_paths,
            declared_repo_root=str(declared_repo_root),
            declared_scope_root=str(declared_scope_root),
            scope_root=scope_root,
            primary_test_cmd=primary_test_cmd,
            attempt_number=t,
            quiet=quiet,
            profile=profile,
            mutation_route=mutation_route,
            task_context=task_context,
            authorization=authorization,
        )
        if fixer_outcome is not None:
            last_verify_receipt = fixer_outcome.verify_receipt
            impact_results = fixer_outcome.impact
            if fixer_outcome.terminal_result is not None:
                return fixer_outcome.terminal_result
            ok = fixer_outcome.ok
            log = fixer_outcome.log
            last_log = log
        if not quiet:
            info("failed: %s", log[:300])
        last_failure_fingerprint, consecutive_same_failure, feedback = _build_retry_feedback_state(
            root=root,
            target=target,
            attempt_number=t,
            quiet=quiet,
            last_validation=last_validation,
            log=log,
            last_output=last_output,
            last_failure_fingerprint=last_failure_fingerprint,
            consecutive_same_failure=consecutive_same_failure,
        )
    return _build_attempts_exhausted_result(
        root=root,
        target=target,
        prompt=prompt,
        quiet=quiet,
        last_output=last_output,
        last_validation=last_validation,
        last_log=last_log,
        last_verify_receipt=last_verify_receipt,
        impact_results=impact_results,
        attempts_limit=attempts_limit,
    )


def _run_prepared_task_route(
    *,
    root,
    stack,
    goal,
    target,
    criteria,
    constraints,
    preflight: TaskPreflight,
    task_context: TaskContext,
    task_spec: TaskSpec | None,
    effect_sink: EffectSink | None,
    authorization: EffectAuthorization | None,
    context_delta: dict | None,
    context_refresh: bool,
    coordinator_kind: str | None,
    session_id: str,
    turn_id: str,
    attempt_number: int,
    subworkflow_id: str,
    deadline: str | None,
    policy_revision: str,
    base_hash: str,
    proposal_only: bool,
    dry_run_task: bool,
    bound_paths,
    quiet: bool,
    scope_root,
) -> dict[str, Any]:
    """Run route selection and attempts after deterministic preflight."""
    context_snapshot = preflight.context_snapshot
    context_pack = preflight.context_pack
    execution_context = preflight.execution_context
    integrated_attempt = preflight.integrated_attempt
    profile = preflight.profile
    requested_execution_mode = preflight.requested_execution_mode
    declared_repo_root = preflight.pipeline_input.declared_repo_root
    declared_scope_root = preflight.pipeline_input.declared_scope_root
    supplied_pack_hash = preflight.pipeline_input.supplied_pack_hash
    migration_policy, mutation_route = _publish_execution_mode_selection(
        root=root, profile=profile, proposal_only=proposal_only, dry_run_task=dry_run_task
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
    if dry_run_task:
        # Dry-run is a non-mutating preview lane.  It must evaluate its own
        # artifact/target preconditions before route-level write/read policy;
        # otherwise a blocked standalone profile prevents valid previews from
        # reaching the provider and masks the structured dry-run blockers.
        return _run_dry_run_task(
            root=root,
            target=target,
            prompt=prompt,
            context_pack=context_pack,
            requested_execution_mode=requested_execution_mode,
            bound_paths=bound_paths,
            declared_repo_root=str(declared_repo_root),
            declared_scope_root=str(declared_scope_root),
        )

    routed_result = _route_prepared_task(
        root=root,
        stack=stack,
        goal=goal,
        target=target,
        criteria=criteria,
        constraints=constraints,
        prompt=prompt,
        primary_test_cmd=primary_test_cmd,
        profile=profile,
        task_spec=task_spec,
        effect_sink=effect_sink,
        authorization=authorization,
        context_snapshot=context_snapshot,
        context_pack=context_pack,
        context_delta=context_delta,
        execution_context=execution_context,
        context_refresh=context_refresh,
        integrated_attempt=integrated_attempt,
        coordinator_kind=coordinator_kind,
        session_id=session_id,
        turn_id=turn_id,
        attempt_number=attempt_number,
        subworkflow_id=subworkflow_id,
        deadline=deadline,
        policy_revision=policy_revision,
        base_hash=base_hash,
        supplied_pack_hash=supplied_pack_hash,
        proposal_only=proposal_only,
        task_context=task_context,
    )
    if routed_result is not None:
        return routed_result
    # Issue #107: structured task_start event for the unified evidence flow.
    emit_event("task_start", {"target": target, "stack": stack, "goal": goal}, root=root)
    return _run_attempt_loop(
        root=root,
        stack=stack,
        target=target,
        prompt=prompt,
        primary_test_cmd=primary_test_cmd,
        bound_paths=bound_paths,
        quiet=quiet,
        profile=profile,
        mutation_route=mutation_route,
        task_context=task_context,
        authorization=authorization,
        declared_repo_root=declared_repo_root,
        declared_scope_root=declared_scope_root,
        scope_root=scope_root,
    )


def _prepare_pipeline_or_blocked(
    mode: PipelineMode | None,
    *,
    root,
    repo_root,
    scope_root,
    context_snapshot,
    context_pack,
    context_snapshot_id,
    context_pack_hash,
    execution_context,
    authorization,
    context_snapshot_path,
    context_pack_path,
    execution_context_path,
    authorization_path,
    effect_sink,
    proposal_only,
    runtime_handshake,
    integrated_attempt,
    attempt_id,
    lease_id,
    fencing_token,
    context_handle,
    dry_run_task,
    coordinator_kind,
    coordinator_id,
    target,
    task_spec,
) -> tuple[PreparedPipeline | None, dict[str, Any] | None]:
    """Prepare execution inputs and preserve the fail-closed input result."""
    from .execution_mode import ExecutionInputError, blocked_input_profile

    try:
        prepared = prepare_pipeline_inputs(
            mode,
            root=root,
            repo_root=repo_root,
            scope_root=scope_root,
            context_snapshot=context_snapshot,
            context_pack=context_pack,
            context_snapshot_id=context_snapshot_id,
            context_pack_hash=context_pack_hash,
            execution_context=execution_context,
            authorization=authorization,
            context_snapshot_path=context_snapshot_path,
            context_pack_path=context_pack_path,
            execution_context_path=execution_context_path,
            authorization_path=authorization_path,
            effect_sink=effect_sink,
            proposal_only=proposal_only,
            runtime_handshake=runtime_handshake,
            integrated_attempt=integrated_attempt,
            attempt_id=attempt_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            context_handle=context_handle,
            dry_run_task=dry_run_task,
            coordinator_kind=coordinator_kind,
            coordinator_id=coordinator_id,
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
        return None, result
    return prepared, None


def _run_task(
    root,
    stack,
    goal,
    target,
    criteria,
    constraints,
    *,
    dry_run_task=False,
    proposal_only=False,
    bound_paths=None,
    quiet=False,
    mode: PipelineMode | None = None,
    effect_sink: EffectSink | None = None,
    authorization: EffectAuthorization | None = None,
    context_snapshot: dict | None = None,
    context_pack: dict | None = None,
    context_delta: dict | None = None,
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
    in this mode). ``dry_run_task`` performs a typed Runtime preflight and
    returns before plan compilation or sink dispatch.
    """
    prepared, blocked_result = _prepare_pipeline_or_blocked(
        mode,
        root=root,
        repo_root=repo_root,
        scope_root=scope_root,
        context_snapshot=context_snapshot,
        context_pack=context_pack,
        context_snapshot_id=context_snapshot_id,
        context_pack_hash=context_pack_hash,
        execution_context=execution_context,
        authorization=authorization,
        context_snapshot_path=context_snapshot_path,
        context_pack_path=context_pack_path,
        execution_context_path=execution_context_path,
        authorization_path=authorization_path,
        effect_sink=effect_sink,
        proposal_only=proposal_only,
        runtime_handshake=runtime_handshake,
        integrated_attempt=integrated_attempt,
        attempt_id=attempt_id,
        lease_id=lease_id,
        fencing_token=fencing_token,
        context_handle=context_handle,
        dry_run_task=dry_run_task,
        coordinator_kind=coordinator_kind,
        coordinator_id=coordinator_id,
        target=target,
        task_spec=task_spec,
    )
    if blocked_result is not None:
        return blocked_result
    assert prepared is not None
    preflight = prepare_task_preflight(prepared, target=target, dry_run_task=dry_run_task)
    authorization = authorization or preflight.authorization
    effect_sink = cast(EffectSink | None, preflight.effect_sink)
    task_context, blocked_result = _resolve_task_preflight(
        preflight,
        target=target,
        authorization=authorization,
        effect_sink=effect_sink,
        proposal_only=proposal_only,
    )
    if blocked_result is not None:
        return blocked_result
    assert task_context is not None
    profile = preflight.profile
    if profile.effective_mode == "integrated" and dry_run_task:
        result = _task_result(
            target,
            "",
            "",
            applied=False,
            status="dry_run",
            warnings=["integrated_effect_preflight_only"],
            blocked_preconditions=[],
        )
        result["execution_profile"] = profile.to_dict()
        return result
    return _run_prepared_task_route(
        root=root,
        stack=stack,
        goal=goal,
        target=target,
        criteria=criteria,
        constraints=constraints,
        preflight=preflight,
        task_context=task_context,
        task_spec=task_spec,
        effect_sink=effect_sink,
        authorization=authorization,
        context_delta=context_delta,
        context_refresh=context_refresh,
        coordinator_kind=coordinator_kind,
        session_id=session_id,
        turn_id=turn_id,
        attempt_number=attempt_number,
        subworkflow_id=subworkflow_id,
        deadline=deadline,
        policy_revision=policy_revision,
        base_hash=base_hash,
        proposal_only=proposal_only,
        dry_run_task=dry_run_task,
        bound_paths=bound_paths,
        quiet=quiet,
        scope_root=scope_root,
    )


def _final_receipt_status(result: dict[str, Any], *, dry_run: bool) -> str:
    if result.get("applied") is True:
        return "applied"
    status = str(result.get("status") or "blocked")
    if dry_run and status == "dry_run":
        return "dry_run"
    if status == "integrated_atomic":
        observation = result.get("observation")
        outcome = observation.get("outcome") if isinstance(observation, dict) else None
        return (
            "blocked"
            if outcome in {"rejected", "precondition_failed", "authorization_required"}
            else "failed"
        )
    return status


def _receipt_context(root: str, target: str, kwargs: dict[str, Any]) -> TaskContext:
    actual_root = Path(root).resolve()
    scope = Path(kwargs.get("scope_root") or actual_root).resolve()
    snapshot = kwargs.get("context_snapshot") or {}
    pack = kwargs.get("context_pack") or {}
    pack_hash = str(pack.get("pack_hash") or kwargs.get("context_pack_hash") or "").strip()
    if not pack_hash and pack:
        pack_hash = hashlib.sha256(
            json.dumps(pack, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
    try:
        return TaskContext.from_values(
            repo_root=actual_root,
            scope_root=scope,
            target=target,
            context_snapshot_id=str(snapshot.get("snapshot_id") or kwargs.get("context_snapshot_id") or ""),
            context_pack_hash=pack_hash,
            attempt_id=str(
                kwargs.get("attempt_id") or getattr(kwargs.get("integrated_attempt"), "attempt_id", "") or ""
            ),
            require_identity=False,
        )
    except (TaskContextError, ValueError):
        return TaskContext.from_values(
            repo_root=actual_root,
            scope_root=actual_root,
            target=".",
            context_snapshot_id="",
            context_pack_hash="",
            attempt_id="",
            require_identity=False,
        )


def _finalize_task_result(
    result: dict[str, Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    if result.get("mutation_authorization_receipt") is not None:
        result.setdefault("pipeline_state", result_trace(result).to_dict())
        return result
    root = str(kwargs.get("root") if kwargs.get("root") is not None else args[0])
    target = str(kwargs.get("target") if kwargs.get("target") is not None else args[3])
    mode = str(kwargs.get("mode") or "standalone")
    profile = result.get("execution_profile")
    effective_mode = str(profile.get("effective_mode") if isinstance(profile, dict) else mode)
    dry_run = bool(kwargs.get("dry_run_task", False))
    if dry_run or result.get("status") == "blocked":
        route = "blocked"
    elif effective_mode == "integrated":
        route = "runtime_effect_api"
    else:
        route = "standalone"
    context = _receipt_context(root, target, kwargs)
    attempt = kwargs.get("integrated_attempt")
    result["pipeline_state"] = result_trace(result).to_dict()
    return _attach_contract_receipt(
        result,
        task_context=context,
        route=route,
        effective_mode=effective_mode,
        authorization=kwargs.get("authorization"),
        verification_status=str(result.get("status") or "unverified"),
        attempt=attempt,
        retry={"attempt": kwargs.get("attempt_number", 1), "max_attempts": 1, "retryable": False},
    )


def run_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    result = _run_task(*args, **kwargs)
    return _finalize_task_result(result, args, kwargs)


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
