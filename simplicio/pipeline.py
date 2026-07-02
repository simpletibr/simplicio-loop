"""pipeline.py — build -> generate -> validate -> test -> fix (loop)."""
from dataclasses import dataclass
import fnmatch
import os, re, subprocess
from .adaptive import get_validation_mode
from .observability import estimate_tokens, log_run
from .pipeline_fixers import try_static_fixers
from .prompt import build_prompt
from .providers import generate, _provider_id, _cfg
from .runtime_env import wrap_project_command

MAX_ATTEMPTS = 5

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
    patch = text[match.start():]
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
    # In "strict" mode (Claude-class), require a TEST block or external
    # test command.  In "diff" mode (strong non-Claude, weak/local),
    # accept diff-only output — these models reliably produce diffs but
    # may not follow the multi-part DIFF+TEST+EVIDENCE output format.
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
        return FailureClassification("syntax", "Fix syntax first; keep the patch minimal and rerun the same test.")
    if "assertionerror" in text or "expected" in text and "actual" in text:
        return FailureClassification("assertion", "The test ran but behavior is wrong; inspect the asserted contract and adjust logic.")
    if "modulenotfound" in text or "no module named" in text or "cannot find module" in text:
        return FailureClassification("dependency", "Use existing project dependencies or correct imports; do not invent packages.")
    if "timeout" in text or "timed out" in text:
        return FailureClassification("timeout", "Reduce scope, avoid long-running work, and make the verification deterministic.")
    if "traceback" in text or "exception" in text or "typeerror" in text or "referenceerror" in text:
        return FailureClassification("runtime", "Fix the runtime exception at the reported callsite.")
    return FailureClassification("unknown", "Re-read the mapper context and produce a smaller, directly testable diff.")

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

def _task_result(task_id, prompt, output, *, applied, warnings=None):
    files_changed = extract_changed_files(output)
    return {
        "task_id": task_id,
        "applied": bool(applied),
        "files_changed": files_changed,
        "tokens_used": {
            "prompt": estimate_tokens(prompt),
            "completion": estimate_tokens(output or ""),
        },
        "cost_usd": 0.0,
        "diff_summary": _diff_summary(files_changed),
        "warnings": warnings or [],
    }

def run_task(root, stack, goal, target, criteria, constraints, *,
             dry_run_task=False, bound_paths=None, quiet=False):
    prompt = build_prompt(root, stack, goal, target, criteria, constraints)
    if dry_run_task:
        output = generate(prompt)
        validation = validate_generated_output(output, bound_paths, mode=get_validation_mode())
        warnings = [] if validation.ok else [validation.reason]
        return _task_result(target, prompt, output, applied=False, warnings=warnings)

    feedback = None
    last_output = ""
    last_validation = None
    last_log = ""
    for t in range(1, MAX_ATTEMPTS + 1):
        if not quiet:
            _model = os.environ.get("SIMPLICIO_MODEL", "")
            _base = os.environ.get("SIMPLICIO_BASE_URL", "")
            _prov = _provider_id(_model, _base) if (_model or _base) else os.environ.get("SIMPLICIO_PROVIDER", "unknown")
            print(f"--- attempt {t} (provider={_prov}, validation={get_validation_mode()}) ---")
        output = generate(prompt, feedback)
        last_output = output or ""
        last_validation = validate_generated_output(output, bound_paths)
        ok, log = _apply_and_test(output, root, bound_paths)
        last_log = log
        log_run(root, {
            "mode": "pipeline",
            "attempt": t,
            "ok": ok,
            "failure_class": "none" if ok else classify_failure(log).kind,
            "tokens_estimated": estimate_tokens(prompt) + estimate_tokens(output),
            "target": target,
            "stack": stack,
        })
        if ok:
            if not quiet:
                print("PASSED the contract. DONE.")
            return _task_result(target, prompt, output, applied=True)
        fixer_result = try_static_fixers(log, root)
        if fixer_result.applied:
            ok, fixed_log = _apply_and_test(output, root, bound_paths)
            log_run(root, {
                "mode": "fixer",
                "attempt": t,
                "ok": ok,
                "fixer": fixer_result.fixer,
                "details": fixer_result.details,
                "failure_class": "none" if ok else classify_failure(fixed_log).kind,
                "target": target,
                "stack": stack,
            })
            last_log = fixed_log
            log = fixed_log if ok else f"{fixer_result.details}\n{fixed_log}"
            if ok:
                if not quiet:
                    print(f"PASSED after static fixer {fixer_result.fixer}. DONE.")
                return _task_result(target, prompt, output, applied=True)
        if not quiet:
            print("failed:", log[:300])
        feedback = build_retry_feedback(t + 1, last_validation, log)
    if not quiet:
        print("attempts exhausted — manual review needed.")
    warnings = []
    if last_validation and not last_validation.ok:
        warnings.append(last_validation.reason)
    elif last_log:
        warnings.append(last_log[:500])
    return _task_result(target, prompt, last_output, applied=False, warnings=warnings)

def run(root, stack, goal, target, criteria, constraints, bound_paths=None):
    result = run_task(root, stack, goal, target, criteria, constraints,
                      bound_paths=bound_paths)
    if result["applied"]:
        return result
    return None
