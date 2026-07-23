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
from .mapper import map_ask
from .observability import emit_event, estimate_tokens, info, log_run
from .pipeline_fixers import try_static_fixers
from .pipeline_integrated import run_integrated
from .pipeline_stages import (
    IMPACT_RESULT_FAILED,
    IMPACT_RESULT_NOT_NEEDED,
    IMPACT_RESULT_PASSED,
    IMPACT_RESULT_UNVERIFIED,
    ApplyStageResult,
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
from .plan_compiler.effect_sink import EffectSink
from .prompt import build_prompt, set_prompt_retry_delta
from .providers import ProviderExecutionError, _provider_id, generate
from .runtime_env import prepare_project_command
from .task_spec import TaskSpec
from .transaction import VerificationReceipt

MAX_ATTEMPTS = 5

# mode="integrated" (issues #166, #167) delegates to pipeline_integrated.run_integrated
# instead of housing the plan-compile/effect-sink logic here — see that
# module's docstring for the full contract and pipeline.py's token-budget
# rationale (issue #141 AC).
PipelineMode = Literal["auto", "standalone", "integrated"]


def _resolve_max_attempts() -> int:
    """Read the per-call attempt budget, honoring an external opt-out.

    Issue #166 (control-plane inventory, see
    docs/plan-compiler.md#control-plane-ownership-inventory-retry--feature-sprint-scheduling)
    flags this loop as a genuine double-retry risk: a host loop that already
    owns retry policy (e.g. simplicio-loop) can invoke ``simplicio-py task``
    once per its own attempt, and this internal loop would still retry
    ``MAX_ATTEMPTS`` times underneath it, multiplying attempts.
    ``SIMPLICIO_MAX_ATTEMPTS`` lets such a caller opt into a single atomic
    attempt (set it to ``1``) without changing standalone use, which keeps
    reading the ``MAX_ATTEMPTS`` module constant unchanged by default.
    """

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
    _LAST_PATCH_RECEIPT = None if receipt is None else dict(receipt)


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


def _apply_and_test_attempt(output, root, bound_paths=None, *, promote_on_success=True):
    if _apply_and_test is not _DEFAULT_APPLY_AND_TEST:
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
    )
    _LAST_VERIFY_RECEIPT = result.verify_receipt
    _LAST_PATCH_RECEIPT = result.patch_receipt
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
    context_snapshot: dict | None = None,
    runtime_handshake: dict | None = None,
    coordinator_kind: str | None = None,
    coordinator_id: str | None = None,
    integrated_attempt: AttemptContext | None = None,
    task_spec: TaskSpec | None = None,
    context_snapshot_path: str | os.PathLike[str] | None = None,
    attempt_id: str | None = None,
    lease_id: str | None = None,
    fencing_token: str | None = None,
    context_handle: str | None = None,
):
    """Run one task through the pipeline.

    ``mode="standalone"`` (the default, unchanged) applies the generated
    patch directly against ``root`` via ``git apply`` and runs
    ``SIMPLICIO_TEST_CMD`` locally, exactly as before this parameter existed
    — see issue #166 plan step 4.5 ("Manter modo standalone apenas como
    adaptador explícito e deprecável").

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
        require_coordinator_attempt,
    )

    try:
        prepared = prepare_execution_inputs(
            mode,
            root=root,
            context_snapshot=context_snapshot,
            context_snapshot_path=context_snapshot_path,
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
            blocked_preconditions=[{"code": exc.code, "message": str(exc)}],
        )
        result["execution_profile"] = blocked_input_profile(
            mode,
            exc,
            root=root,
            coordinator_kind=coordinator_kind,
            coordinator_id=coordinator_id,
        ).to_dict()
        return result
    context_snapshot = prepared.context_snapshot
    effect_sink = cast(EffectSink | None, prepared.effect_sink)
    runtime_handshake = prepared.runtime_handshake
    integrated_attempt = prepared.attempt

    profile = negotiate_execution_mode(
        mode,
        root=root,
        runtime_handshake=runtime_handshake,
        context_snapshot=context_snapshot,
        effect_sink=effect_sink,
        coordinator_kind=coordinator_kind,
        coordinator_id=coordinator_id,
    )
    profile = require_coordinator_attempt(profile, integrated_attempt)
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
    if profile.effective_mode == "blocked":
        result = _task_result(
            target,
            prompt,
            "",
            applied=False,
            status="blocked",
            warnings=[profile.reason_code],
            blocked_preconditions=[
                {"code": profile.reason_code, "message": "execution-mode negotiation failed closed"}
            ],
        )
        result["execution_profile"] = profile.to_dict()
        return result
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
            context_snapshot=context_snapshot,
            attempt=integrated_attempt,
            task_spec=task_spec,
        )
        result["execution_profile"] = profile.to_dict()
        return result
    if not dry_run_task and primary_test_cmd is None:
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
    if dry_run_task:
        blockers = _dry_run_preconditions(root, target)
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
        # Issue #210 AC6: snapshot bound paths BEFORE generate() so an
        # out-of-band mutation that happens while the provider subprocess is
        # running (e.g. the target deleted mid-stall) is caught even though
        # nothing in the returned diff would ever mention it.
        bound_path_baseline = snapshot_bound_paths(root, bound_paths)
        output = generate(prompt)
        drift_warnings = bound_path_drift(root, bound_paths, bound_path_baseline)
        validation = validate_generated_output(output, bound_paths, mode=get_validation_mode(), root=root)
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
        last_validation = validate_generated_output(output, bound_paths, root=root)
        if getattr(_apply_and_test, "__module__", __name__) != __name__:
            legacy_ok, legacy_log = _apply_and_test(output, root, bound_paths)
            attempt = ApplyStageResult(legacy_ok, legacy_log, None, None)
        else:
            attempt = _apply_and_test_attempt(output, root, bound_paths, promote_on_success=False)
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
            attempt = _apply_and_test_attempt(output, root, bound_paths, promote_on_success=False)
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


def run(root, stack, goal, target, criteria, constraints, bound_paths=None):
    result = run_task(root, stack, goal, target, criteria, constraints, bound_paths=bound_paths)
    if result["applied"]:
        return result
    return None


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
