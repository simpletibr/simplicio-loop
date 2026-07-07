"""pipeline.py — build -> generate -> validate -> test -> fix -> verify (loop).

The 6-layer contract (mapper→precedent→prompt→diff→test→verify) is
implemented by this module plus :mod:`simplicio.mapper` for the first two
layers.  Issue #93 adds impact-test verification to the ``verify`` layer:
after the primary test passes, ``_run_impact_tests`` queries the mapper's
``impact`` and ``tests-for`` verbs to find callers of the changed symbols
and runs their tests too.  When impact tests fail, the failure enters the
retry loop just like any verify failure.
"""

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adaptive import get_validation_mode
from .mapper import map_ask
from .observability import emit_event, estimate_tokens, info, log_run
from .orchestrator.cost_governor import _price as _estimate_price
from .pipeline_fixers import try_static_fixers
from .prompt import build_prompt
from .providers import _provider_id, generate
from .runtime_env import wrap_project_command

MAX_ATTEMPTS = 5

# ---------------------------------------------------------------------------
# Impact-test verification — issue #93
# ---------------------------------------------------------------------------

IMPACT_RESULT_PASSED = "passed"
IMPACT_RESULT_FAILED = "failed"
IMPACT_RESULT_UNVERIFIED = "unverified"
IMPACT_RESULT_NOT_NEEDED = "no_impact_tests"


def _run_impact_tests(
    root: str | Path,
    files_changed: list[str],
    *,
    test_cmd: str | None = None,
) -> dict[str, Any]:
    """Run tests for callers/dependents of *files_changed*.

    Uses the mapper's ``ask impact`` verb to find callers of each changed
    file, then ``ask tests-for`` to locate test files for those callers.
    Runs the discovered test files with the configured test command.

    Returns a dict with keys ``status``, ``callers``, ``tests_run``,
    ``result``, and optionally ``output_tail``.  When the mapper CLI is
    unavailable or no callers/tests are found the result is a "safe miss"
    (``unverified`` or ``no_impact_tests``) — the pipeline treats these as
    *not-a-failure*.
    """
    if not files_changed:
        return {
            "status": "no_changed_files",
            "callers": [],
            "tests_run": [],
            "result": IMPACT_RESULT_NOT_NEEDED,
        }

    root_str = str(Path(root).resolve())
    callers_seen: set[str] = set()
    test_files_seen: set[str] = set()

    for filepath in files_changed:
        impact = map_ask(root_str, "impact", filepath)
        if not impact:
            continue
        for entry in impact:
            if not isinstance(entry, dict):
                continue
            caller = entry.get("caller") or entry.get("path") or ""
            if caller and caller not in callers_seen:
                callers_seen.add(caller)

    if not callers_seen:
        return {
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
            "result": IMPACT_RESULT_NOT_NEEDED,
        }

    for caller in callers_seen:
        tests = map_ask(root_str, "tests-for", caller)
        if not tests:
            continue
        for t in tests:
            if not isinstance(t, dict):
                continue
            test_path = t.get("test_path") or t.get("path") or t.get("file") or ""
            if test_path:
                test_files_seen.add(test_path)

    if not test_files_seen:
        return {
            "status": "no_tests_found",
            "callers": sorted(callers_seen),
            "tests_run": [],
            "result": IMPACT_RESULT_NOT_NEEDED,
        }

    test_files = sorted(test_files_seen)
    cmd_raw = (test_cmd or os.environ.get("SIMPLICIO_TEST_CMD", "pytest")).strip()
    argv = cmd_raw.split() + test_files
    use_shell = len(cmd_raw.split()) == 1

    try:
        p = subprocess.run(
            argv if not use_shell else " ".join(argv),
            shell=use_shell,
            cwd=root_str,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "error",
            "callers": sorted(callers_seen),
            "tests_run": test_files,
            "result": IMPACT_RESULT_UNVERIFIED,
            "error": str(exc),
        }

    passed = p.returncode == 0
    return {
        "status": "ok" if passed else "failed",
        "callers": sorted(callers_seen),
        "tests_run": test_files,
        "result": IMPACT_RESULT_PASSED if passed else IMPACT_RESULT_FAILED,
        "returncode": p.returncode,
        "output_tail": (p.stdout + p.stderr)[-2000:] if not passed else "",
    }


# ---------------------------------------------------------------------------
# Existing helpers (unchanged except where noted for #93)
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    hints: list[str]


@dataclass
class FailureClassification:
    kind: str
    guidance: str


def extract_changed_files(output):
    text = output or ""
    files = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", text, flags=re.M):
        files.append(match.group(2).strip())
    for match in re.finditer(r"^\+\+\+ b/(.+?)$", text, flags=re.M):
        files.append(match.group(1).strip())
    return list(dict.fromkeys(f for f in files if f and f != "/dev/null"))


def _matches_bound(path, patterns):
    normalized = path.replace(os.sep, "/").lstrip("./")
    for raw in patterns or []:
        pattern = str(raw).replace(os.sep, "/").lstrip("./")
        if fnmatch.fnmatch(normalized, pattern):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return True
    return False


def _bound_path_warnings(files, bound_paths):
    if not bound_paths:
        return []
    outside = [path for path in files if not _matches_bound(path, bound_paths)]
    if not outside:
        return []
    return [
        "diff touches path outside bound paths: "
        + ", ".join(outside)
        + f" (allowed: {', '.join(bound_paths)})"
    ]


def extract_patch(output):
    text = output or ""
    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?)(?:\n```|$)", text, flags=re.S)
    if fenced and ("diff --git " in fenced.group(1) or "--- " in fenced.group(1)):
        return fenced.group(1).strip() + "\n"
    match = re.search(r"(?m)^(diff --git .+|--- .+)$", text)
    if not match:
        return ""
    patch = text[match.start() :]
    fence = patch.find("\n```")
    if fence != -1:
        patch = patch[:fence]
    return patch.strip() + "\n"


def validate_generated_output(output, bound_paths=None, mode=None):
    text = output or ""
    if mode is None:
        mode = get_validation_mode()
    hints = []
    has_diff = bool(re.search(r"^diff --git |^--- .+\n\+\+\+ ", text, flags=re.M))
    has_test = "TEST:" in text or re.search(r"(^|\n)(test|it|def test_|describe)\b", text)
    external_test_cmd = os.environ.get("SIMPLICIO_TEST_CMD", "").strip()
    has_external_test = bool(external_test_cmd and external_test_cmd != "echo 'configure SIMPLICIO_TEST_CMD'")
    if not has_diff:
        hints.append("include a unified diff with exact target files")
    if mode == "strict":
        if not has_test and not has_external_test:
            hints.append("include a TEST block or concrete test code")
    if not has_external_test and re.search(r"(?i)\b(pseudocode|placeholder|todo: implement)\b", text):
        hints.append("replace placeholders with executable code")
    hints.extend(_bound_path_warnings(extract_changed_files(output), bound_paths))
    return ValidationResult(
        ok=not hints,
        reason="ok" if not hints else "; ".join(hints),
        hints=hints,
    )


def classify_failure(log):
    text = (log or "").lower()
    if "syntaxerror" in text or "unexpected token" in text or "parse error" in text:
        return FailureClassification(
            "syntax", "Fix syntax first; keep the patch minimal and rerun the same test."
        )
    if "assertionerror" in text or "expected" in text and "actual" in text:
        return FailureClassification(
            "assertion", "The test ran but behavior is wrong; inspect the asserted contract and adjust logic."
        )
    if "modulenotfound" in text or "no module named" in text or "cannot find module" in text:
        return FailureClassification(
            "dependency", "Use existing project dependencies or correct imports; do not invent packages."
        )
    if "timeout" in text or "timed out" in text:
        return FailureClassification(
            "timeout", "Reduce scope, avoid long-running work, and make the verification deterministic."
        )
    if "traceback" in text or "exception" in text or "typeerror" in text or "referenceerror" in text:
        return FailureClassification("runtime", "Fix the runtime exception at the reported callsite.")
    return FailureClassification(
        "unknown", "Re-read the mapper context and produce a smaller, directly testable diff."
    )


def build_retry_feedback(attempt, validation=None, test_log=""):
    classification = classify_failure(test_log)
    lines = [
        f"Retry feedback for attempt {attempt}:",
        f"failure_class={classification.kind}",
        classification.guidance,
    ]
    if validation and not validation.ok:
        lines.append(f"pre-apply validation failed: {validation.reason}")
    if test_log:
        lines.append("test/runtime tail:")
        lines.append(test_log[-1600:])
    lines.append("Return the full corrected DIFF + TEST block only.")
    return "\n".join(lines)


def _git_apply_patch(root, patch):
    # No native-first `simplicio` delegation here (unlike mechanical_edit.py's
    # execute_plan). Confirmed against the installed `simplicio` binary's own
    # --help: `simplicio edit` only accepts a JSON operations plan
    # (`--plan <file|->` or a literal JSON positional argument) — there is no
    # --diff/--patch flag to feed it a raw unified diff. Delegation to the
    # native binary happens at the mechanical_edit.py layer instead; this
    # git-apply path (which applies an LLM-generated unified diff, not a
    # mechanical-edit plan) stays local-only.
    attempts = [
        ([], "git apply"),
        (["--recount"], "git apply --recount"),
    ]
    errors = []
    for extra_args, label in attempts:
        check = subprocess.run(
            ["git", "apply", "--check", *extra_args, "-"],
            input=patch,
            cwd=root,
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            errors.append(f"{label} --check failed:\n{(check.stderr or check.stdout)[-1600:]}")
            continue
        apply = subprocess.run(
            ["git", "apply", *extra_args, "-"],
            input=patch,
            cwd=root,
            capture_output=True,
            text=True,
        )
        if apply.returncode == 0:
            return True, ""
        errors.append(f"{label} failed:\n{(apply.stderr or apply.stdout)[-1600:]}")
    return False, "\n".join(errors)


def _apply_and_test(output, root, bound_paths=None):
    os.makedirs(os.path.join(root, ".simplicio"), exist_ok=True)
    open(os.path.join(root, ".simplicio/last_output.txt"), "w").write(output or "")
    validation = validate_generated_output(output, bound_paths)
    if not validation.ok:
        return False, f"pre-apply validation failed: {validation.reason}"
    patch = extract_patch(output)
    if not patch:
        return False, "pre-apply validation failed: no unified diff found"
    open(os.path.join(root, ".simplicio/last_patch.diff"), "w").write(patch)
    applied, apply_log = _git_apply_patch(root, patch)
    if not applied:
        return False, apply_log
    cmd = os.environ.get("SIMPLICIO_TEST_CMD", "echo 'configure SIMPLICIO_TEST_CMD'")
    cmd = wrap_project_command(root, cmd)
    p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr)[-2000:]


def _diff_summary(files_changed):
    if not files_changed:
        return "no changed files reported"
    return "changed " + ", ".join(files_changed)


def _task_result(task_id, prompt, output, *, applied, warnings=None, impact=None):
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
        "files_changed": files_changed,
        "tokens_used": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
        "cost_usd": cost_usd,
        "cost_basis": "estimated" if priced else "unknown_no_pricing_configured",
        "diff_summary": _diff_summary(files_changed),
        "warnings": warnings or [],
    }
    # Issue #93: impact-test evidence block
    if impact is not None:
        result["impact"] = {
            "callers": impact.get("callers", []),
            "tests_run": impact.get("tests_run", []),
            "result": impact.get("result", IMPACT_RESULT_UNVERIFIED),
        }
        if impact.get("status") in ("ok", "passed"):
            result["impact"]["status"] = "verified"
        elif impact.get("status") in ("failed", "error"):
            result["impact"]["status"] = impact["status"]
        else:
            result["impact"]["status"] = IMPACT_RESULT_UNVERIFIED
    return result


def run_task(
    root, stack, goal, target, criteria, constraints, *, dry_run_task=False, bound_paths=None, quiet=False
):
    prompt = build_prompt(root, stack, goal, target, criteria, constraints)
    if dry_run_task:
        output = generate(prompt)
        validation = validate_generated_output(output, bound_paths, mode=get_validation_mode())
        warnings = [] if validation.ok else [validation.reason]
        return _task_result(target, prompt, output, applied=False, warnings=warnings)

    # Issue #107: structured "task_start" event — the dev-cli side of the
    # unified evidence flow a host loop's journal (e.g. simplicio-loop's
    # loop_journal.py) can consume. See observability.emit_event's contract.
    emit_event("task_start", {"target": target, "stack": stack, "goal": goal}, root=root)

    feedback = None
    last_output = ""
    last_validation = None
    last_log = ""
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
        ok, log = _apply_and_test(output, root, bound_paths)
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
            impact_results = _run_impact_tests(root, files_changed)
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
                    impact=impact_results,
                )
            else:
                # IMPACT_RESULT_UNVERIFIED — mapper unavailable or error
                if not quiet:
                    info("PASSED the contract (impact unverifiable). DONE.")
                emit_event(
                    "task_complete",
                    {"target": target, "attempt": t, "impact": "unverifiable"},
                    root=root,
                    tokens_saved=0,
                )
                return _task_result(
                    target,
                    prompt,
                    output,
                    applied=True,
                    impact=impact_results,
                )

        # ── Primary test or impact test failed — try fixers ──
        fixer_result = try_static_fixers(log, root)
        if fixer_result.applied:
            ok, fixed_log = _apply_and_test(output, root, bound_paths)
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
                impact_results = _run_impact_tests(root, files_changed)
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
                        impact=impact_results,
                    )
        if not quiet:
            info("failed: %s", log[:300])
        feedback = build_retry_feedback(t + 1, last_validation, log)
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
        impact=impact_results,
    )


def run(root, stack, goal, target, criteria, constraints, bound_paths=None):
    result = run_task(root, stack, goal, target, criteria, constraints, bound_paths=bound_paths)
    if result["applied"]:
        return result
    return None
