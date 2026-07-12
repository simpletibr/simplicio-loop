"""pipeline.py — build -> generate -> validate -> test -> fix -> verify (loop).

The 6-layer contract (mapper→precedent→prompt→diff→test→verify) is
implemented by this module plus :mod:`simplicio.mapper` for the first two
layers.  Issue #93 adds impact-test verification to the ``verify`` layer:
after the primary test passes, ``_run_impact_tests`` queries the mapper's
``impact`` and ``tests-for`` verbs to find callers of the changed symbols
and runs their tests too.  When impact tests fail, the failure enters the
retry loop just like any verify failure.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

from .adaptive import get_validation_mode
from .mapper import artifact_status, map_ask, map_handoff
from .observability import emit_event, estimate_tokens, info, log_run
from .orchestrator.cost_governor import _price as _estimate_price
from .pipeline_fixers import try_static_fixers
from .pipeline_stages import (
    IMPACT_RESULT_FAILED,
    IMPACT_RESULT_NOT_NEEDED,
    IMPACT_RESULT_PASSED,
    IMPACT_RESULT_UNVERIFIED,
    ApplyStageResult,
    build_retry_feedback,
    classify_failure,
    extract_changed_files,
    run_apply_stage,
    run_impact_tests,
    validate_generated_output,
)
from .pipeline_stages import (
    _git_apply_patch as _stage_git_apply_patch,
)
from .pipeline_task_result import (
    _diff_summary,
    _dry_run_preconditions,
    _task_result,
    _verify_receipt_payload,
)
from .prompt import build_prompt, latest_prompt_envelope, set_prompt_retry_delta
from .providers import _provider_id, generate
from .runtime_env import prepare_project_command
from .transaction import VerificationReceipt

MAX_ATTEMPTS = 5

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


def _diff_summary(files_changed):
    if not files_changed:
        return "no changed files reported"
    return "changed " + ", ".join(files_changed)


def _task_result(
    task_id,
    prompt,
    output,
    *,
    applied,
    status=None,
    warnings=None,
    blocked_preconditions=None,
    verify=None,
    impact=None,
    prompt_envelope=None,
):
    files_changed = extract_changed_files(output)
    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(output or "")
    priced = os.environ.get("SIMPLICIO_PRICE_PER_MTOK") or (
        os.environ.get("SIMPLICIO_PRICE_PROMPT_PER_MTOK")
        or os.environ.get("SIMPLICIO_PRICE_COMPLETION_PER_MTOK")
    )
    model = os.environ.get("SIMPLICIO_MODEL", "")
    cost_usd = float(_estimate_price(model, prompt_tokens, completion_tokens)) if priced else 0.0
    result = {
        "task_id": task_id,
        "applied": bool(applied),
        "status": status or ("applied" if applied else "failed"),
        "files_changed": files_changed,
        "tokens_used": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
        "cost_usd": cost_usd,
        "cost_basis": "estimated" if priced else "unknown_no_pricing_configured",
        "diff_summary": _diff_summary(files_changed),
        "warnings": warnings or [],
        "model": {
            "requested": os.environ.get("SIMPLICIO_MODEL", ""),
            "effective": os.environ.get("SIMPLICIO_EFFECTIVE_MODEL", os.environ.get("SIMPLICIO_MODEL", "")),
            "effort": os.environ.get("SIMPLICIO_REASONING_EFFORT", os.environ.get("SIMPLICIO_EFFORT", "")),
            "tier": os.environ.get("SIMPLICIO_MODEL_TIER", ""),
            "provider": _provider_id(
                os.environ.get("SIMPLICIO_MODEL", ""), os.environ.get("SIMPLICIO_BASE_URL", "")
            ),
        },
    }
    envelope = prompt_envelope or latest_prompt_envelope()
    if envelope is not None:
        result["prompt_envelope"] = envelope.receipt()
    if blocked_preconditions:
        result["blocked_preconditions"] = blocked_preconditions
    verify_receipt = _verify_receipt_payload(verify)
    if verify_receipt is not None:
        exit_codes = verify_receipt.get("exit_codes", [])
        if exit_codes:
            status = "verified" if all(code == 0 for code in exit_codes) else "failed"
        else:
            status = IMPACT_RESULT_UNVERIFIED
        result["verify"] = {
            "status": status,
            "receipt": verify_receipt,
        }
    # Issue #93: impact-test evidence block
    if impact is not None:
        result["impact"] = {
            "callers": impact.get("callers", []),
            "tests_run": impact.get("tests_run", []),
            "result": impact.get("result", IMPACT_RESULT_UNVERIFIED),
        }
        receipt = impact.get("receipt")
        if isinstance(receipt, dict):
            result["impact"]["receipt"] = dict(receipt)
        else:
            receipt = {
                "command": impact.get("command"),
                "exit_code": impact.get("returncode"),
                "output_tail": impact.get("output_tail", ""),
                "status": impact.get("status"),
            }
            if any(value not in (None, "", []) for value in receipt.values()):
                result["impact"]["receipt"] = receipt
        if impact.get("status") in ("ok", "passed"):
            result["impact"]["status"] = "verified"
        elif impact.get("status") in ("failed", "error"):
            result["impact"]["status"] = impact["status"]
        else:
            result["impact"]["status"] = IMPACT_RESULT_UNVERIFIED
    if _LAST_PATCH_RECEIPT is not None:
        result["patch"] = dict(_LAST_PATCH_RECEIPT)
    return result


def run_task(
    root, stack, goal, target, criteria, constraints, *, dry_run_task=False, bound_paths=None, quiet=False
):
    _remember_patch_receipt(None)
    prompt = build_prompt(root, stack, goal, target, criteria, constraints)
    primary_test_cmd = os.environ.get("SIMPLICIO_TEST_CMD", "").strip() or None
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
            )
        output = generate(prompt)
        validation = validate_generated_output(output, bound_paths, mode=get_validation_mode())
        warnings = [] if validation.ok else [validation.reason]
        return _task_result(target, prompt, output, applied=False, status="dry_run", warnings=warnings)

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
    for t in range(1, MAX_ATTEMPTS + 1):
        if not quiet:
            _model = os.environ.get("SIMPLICIO_MODEL", "")
            _base = os.environ.get("SIMPLICIO_BASE_URL", "")
            _prov = (
                _provider_id(_model, _base)
                if (_model or _base)
                else os.environ.get("SIMPLICIO_PROVIDER", "unknown")
            )
            info(f"--- attempt {t} (provider={_prov}, validation={get_validation_mode()}) ---")
        output = generate(prompt, feedback)
        last_output = output or ""
        last_validation = validate_generated_output(output, bound_paths)
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
                    return _task_result(
                        target,
                        prompt,
                        output,
                        applied=True,
                        verify=last_verify_receipt,
                        impact=impact_results,
                    )
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
                        return _task_result(
                            target,
                            prompt,
                            output,
                            applied=True,
                            verify=last_verify_receipt,
                            impact=impact_results,
                        )
                else:
                    ok = False
                    log = "impact verification unavailable after fixer — " + (impact_results or {}).get(
                        "status", "unknown"
                    )
        if not quiet:
            info("failed: %s", log[:300])
        feedback = build_retry_feedback(t + 1, last_validation, log)
        retry_feedback = set_prompt_retry_delta(
            reason="verification-failed",
            failure_class=classify_failure(log).kind,
            diagnostics=feedback,
            affected_files=extract_changed_files(last_output),
        )
        if retry_feedback:
            feedback = retry_feedback
    if not quiet:
        info("attempts exhausted — manual review needed.")
    warnings = []
    if last_validation and not last_validation.ok:
        warnings.append(last_validation.reason)
    elif last_log:
        warnings.append(last_log[:500])
    emit_event(
        "validation_fail",
        {"target": target, "attempts": MAX_ATTEMPTS, "warnings": warnings[:1]},
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
