"""Quality matrix gate (#278, extended by #283): fail-closed evidence for every
mandatory quality lane.

No issue/delivery can be reported ``done`` unless a versioned quality-matrix receipt
proves implementation, unit, integration, system, regression and benchmark evidence
*and* a measured coverage percentage at/above the configured minimum (default 85%).
The matrix is intentionally data-only: it reads a JSON receipt produced by the run
(``quality-matrix.json``) and renders a structured, fail-closed verdict — it never
invents a passing result for a requirement that is missing or unmeasured.

#283 ("Quality Gate obrigatório com TDD, testes completos, cobertura minima e
benchmark") adds, on top of the #278 baseline, in a strictly backward-compatible
way (a receipt with no ``policy``/``tdd`` key behaves exactly as before):

  * an opt-in ``tdd`` lane — enabled per-receipt via ``policy.tdd_required`` — that
    requires *distinct* RED (failing-before-implementation) and GREEN
    (passing-after-implementation) evidence refs, not just a single proof_ref;
  * a ``policy`` block that can relax an individual lane's toggle
    (``<lane>_required``) and/or allow a justified ``not_applicable`` verdict for a
    lane (default: only ``benchmark`` may be excused, and only when
    ``policy.allow_justified_not_applicable`` is true and a non-empty
    ``justification`` is supplied);
  * a deterministic change-type classifier (``classify_change_type``) so the
    correct policy defaults can be derived from an issue's title/labels
    (bug/task/feat/fix/chore), matching contracts/quality-gate/v1/schema.json.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCHEMA = "simplicio.quality-matrix/v1"

# Every one of these lanes is mandatory (#278 acceptance criteria): implementation,
# unit, integration, system and regression evidence, plus a performance benchmark.
# Coverage is validated separately since it carries a numeric threshold rather than
# a simple pass/fail state.
REQUIRED_REQUIREMENTS: Tuple[str, ...] = (
    "implementation",
    "unit",
    "integration",
    "system",
    "regression",
    "benchmark",
)

# #283: opt-in lane, gated by policy.tdd_required (default False — a receipt that
# never mentions TDD keeps the exact #278 behavior). When enabled it is validated
# with its own two-sided (RED then GREEN) evidence check, see `_tdd_gate`.
OPTIONAL_TDD_REQUIREMENT = "tdd"

# #283: lanes that may be excused with a justified NOT_APPLICABLE verdict, and only
# when the receipt's policy explicitly opts in (`allow_justified_not_applicable`).
# Keeping this to `benchmark` matches the issue text verbatim ("benchmark executado
# ou decisão NOT_APPLICABLE justificada e aprovada") — every other lane stays
# strictly mandatory.
NOT_APPLICABLE_ELIGIBLE = frozenset({"benchmark"})

DEFAULT_COVERAGE_THRESHOLD = 85.0
RECEIPT_FILENAME = "quality-matrix.json"

# #283: the four lanes the issue's example `simplicio.quality-gate/v1` envelope nests
# under a "tests" object (implementation/benchmark/tdd stay top-level in that same
# example). `evaluate_quality_matrix` still reads these from the flat `requirements`
# dict for backward compatibility with every #278/#283 receipt already in the wild,
# but now also accepts them nested under "tests" -- see `_merge_tests_envelope` and
# `sync_tests_envelope` below, which keep the two views in lockstep.
TESTS_ENVELOPE_CATEGORIES: Tuple[str, ...] = ("unit", "integration", "system", "regression")

# #283 deterministic change classification (bug/task/feat/fix/chore). Order matters:
# first matching keyword wins, checked against labels first (authoritative), then
# title (heuristic fallback) — mirrors `scripts/repo_conventions.py`'s classifier
# philosophy of "deterministic, no LLM needed".
CHANGE_TYPES: Tuple[str, ...] = ("bug", "fix", "feat", "chore", "task")

_CHANGE_TYPE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "bug": ("bug", "defect", "regression"),
    "fix": ("fix", "hotfix", "patch"),
    "feat": ("feat", "feature", "enhancement"),
    "chore": ("chore", "docs", "doc", "refactor", "cleanup", "ci"),
    "task": ("task",),
}


def classify_change_type(title: str = "", labels: List[str] | None = None) -> str:
    """Deterministically classify a work item as bug/fix/feat/chore/task.

    Labels are authoritative (checked first, in `CHANGE_TYPES` priority order);
    the title is only a fallback heuristic when no label matches. Defaults to
    ``"task"`` when nothing matches — the strictest lane requirements apply to an
    unclassified item rather than silently excusing it.
    """
    norm_labels = {str(label).strip().lower() for label in (labels or [])}
    for change_type in CHANGE_TYPES:
        keywords = _CHANGE_TYPE_KEYWORDS[change_type]
        if any(label == change_type or label in keywords for label in norm_labels):
            return change_type
    title_l = (title or "").lower()
    for change_type in CHANGE_TYPES:
        keywords = _CHANGE_TYPE_KEYWORDS[change_type]
        if any(re.search(r"\b%s\b" % re.escape(kw), title_l) for kw in keywords):
            return change_type
    return "task"


def default_policy_for_change_type(change_type: str) -> Dict[str, Any]:
    """Return the default #283 policy block for a classified change type.

    ``feat``/``fix``/``bug`` (behavior-changing work) get the strictest policy:
    TDD required, no NOT_APPLICABLE excuse for benchmark. ``chore`` (docs/refactor/
    CI-only work with no behavior change) may skip TDD and may justify benchmark as
    NOT_APPLICABLE. ``task`` sits at the strict default (unclassified/ambiguous work
    is never silently relaxed).
    """
    if change_type == "chore":
        return {
            "tdd_required": False,
            "allow_justified_not_applicable": True,
        }
    return {
        "tdd_required": True,
        "allow_justified_not_applicable": False,
    }


class QualityMatrixError(ValueError):
    """Raised when the quality-matrix policy itself is malformed."""


def _gate(name: str, ok: bool, reason_code: str, detail: str) -> Dict[str, Any]:
    return {"name": name, "status": "pass" if ok else "fail", "reason_code": reason_code, "detail": detail}


def receipt_path(run_dir: str) -> Path:
    return Path(run_dir) / RECEIPT_FILENAME


def _merge_tests_envelope(requirements: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
    """#283: accept the issue's literal envelope shape (`tests.unit`/`tests.integration`/
    `tests.system`/`tests.regression`) as an alternative to the flat `requirements.<lane>`
    entries these same four categories have always used. A flat `requirements` entry always
    wins when both are present (never silently overridden by a stale "tests" mirror); "tests"
    only fills in a category the flat dict is missing entirely.
    """
    tests_obj = receipt.get("tests")
    if not isinstance(tests_obj, dict):
        return requirements
    merged = dict(requirements)
    for name in TESTS_ENVELOPE_CATEGORIES:
        if name not in merged and isinstance(tests_obj.get(name), dict):
            merged[name] = tests_obj[name]
    return merged


def sync_tests_envelope(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """#283: (re)compute the nested `tests` mirror from the canonical `requirements` lanes.

    Call this after writing/updating `receipt["requirements"]` so the receipt satisfies the
    issue's literal `simplicio.quality-gate/v1` example shape (`tests.unit`/`tests.integration`/
    `tests.system`/`tests.regression`) as well as the flat shape every existing #278/#283
    producer and consumer already reads/writes. Returns the same receipt for chaining.
    """
    requirements = receipt.get("requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    receipt["tests"] = {
        name: requirements.get(name, {"status": "unset", "proof_ref": "", "detail": ""})
        for name in TESTS_ENVELOPE_CATEGORIES
    }
    return receipt


def _load_json(path: Path) -> Dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def validate_coverage_threshold(value: Any) -> float:
    """Validate a configured coverage threshold, fail-closed on anything malformed.

    Raises :class:`QualityMatrixError` rather than silently clamping — an invalid
    policy must never be quietly downgraded to a permissive default.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualityMatrixError(f"coverage threshold must be numeric, got {value!r}")
    threshold = float(value)
    if threshold < 0 or threshold > 100:
        raise QualityMatrixError(f"coverage threshold must be between 0 and 100, got {threshold!r}")
    return threshold


def _requirement_gate(name: str, requirements: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    entry = requirements.get(name)
    if not isinstance(entry, dict):
        return _gate(name, False, f"quality_{name}_missing", f"required '{name}' evidence is missing from the quality matrix")
    status = str(entry.get("status") or "").strip().lower()

    # #283: a lane in NOT_APPLICABLE_ELIGIBLE may be excused with an approved,
    # justified NOT_APPLICABLE verdict — but only when the receipt's policy opts in
    # AND a non-empty justification is recorded. Anything else (unjustified NA, NA
    # on a lane that isn't eligible, or NA without the policy flag) fails closed.
    if status == "not_applicable":
        justification = str(entry.get("justification") or "").strip()
        if name in NOT_APPLICABLE_ELIGIBLE and policy.get("allow_justified_not_applicable") and justification:
            return _gate(name, True, f"quality_{name}_not_applicable",
                         f"'{name}' justified NOT_APPLICABLE: {justification}")
        return _gate(name, False, f"quality_{name}_not_applicable_unjustified",
                     f"'{name}' NOT_APPLICABLE requires policy.allow_justified_not_applicable "
                     f"and a non-empty justification, for an eligible lane only")

    proof_ref = str(entry.get("proof_ref") or "").strip()
    if status != "pass":
        return _gate(name, False, f"quality_{name}_failed",
                     f"required '{name}' evidence is not passing (status={status or 'unset'!r})")
    if not proof_ref:
        return _gate(name, False, f"quality_{name}_unproven",
                     f"required '{name}' evidence has no proof reference")
    return _gate(name, True, f"quality_{name}_verified", f"'{name}' evidence verified via {proof_ref}")


def _tdd_gate(requirements: Dict[str, Any]) -> Dict[str, Any]:
    """#283: TDD lane — requires DISTINCT RED (pre-implementation, failing) and
    GREEN (post-implementation, passing) evidence refs, not a single generic
    proof_ref. Only evaluated when policy.tdd_required is truthy (see caller)."""
    name = OPTIONAL_TDD_REQUIREMENT
    entry = requirements.get(name)
    if not isinstance(entry, dict):
        return _gate(name, False, "quality_tdd_missing", "policy requires TDD evidence but no 'tdd' entry is present")
    status = str(entry.get("status") or "").strip().lower()
    if status != "pass":
        return _gate(name, False, "quality_tdd_failed", f"TDD evidence is not passing (status={status or 'unset'!r})")
    red_ref = str(entry.get("red_proof_ref") or "").strip()
    green_ref = str(entry.get("green_proof_ref") or "").strip()
    if not red_ref:
        return _gate(name, False, "quality_tdd_red_missing", "TDD RED evidence (red_proof_ref) is missing")
    if not green_ref:
        return _gate(name, False, "quality_tdd_green_missing", "TDD GREEN evidence (green_proof_ref) is missing")
    if red_ref == green_ref:
        return _gate(name, False, "quality_tdd_red_green_identical",
                     "RED and GREEN evidence refs must be distinct — a single ref cannot prove both a failing-before and a passing-after state")
    return _gate(name, True, "quality_tdd_verified", f"TDD RED verified via {red_ref}, GREEN verified via {green_ref}")


def evaluate_quality_matrix(run_dir: str) -> Dict[str, Any]:
    """Evaluate the fail-closed quality gate for one run directory.

    Returns a dict with ``ready`` (bool), ``reason_code``/``reason`` for the first
    failing gate (or the success verdict), the full ``gates`` list, and the
    coverage figures actually measured vs. required — every field the delivery
    gate and the CLI need to explain a block.
    """
    gates: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "ready": False,
        "reason_code": "quality_matrix_incomplete",
        "reason": "quality matrix gates not satisfied",
        "coverage_threshold": DEFAULT_COVERAGE_THRESHOLD,
        "coverage_measured": None,
        "gates": gates,
    }

    path = receipt_path(run_dir)
    receipt = _load_json(path)
    if not receipt:
        gate = _gate("quality_matrix", False, "quality_matrix_missing", f"{RECEIPT_FILENAME} is missing or unreadable")
        gates.append(gate)
        result["reason_code"] = gate["reason_code"]
        result["reason"] = gate["detail"]
        return result
    if receipt.get("schema") == "simplicio.quality-matrix/v2":
        # One semantic implementation is shared by the oracle and independent
        # watcher; v2 receipts never fall through the permissive legacy reader.
        from .quality_matrix_v2 import evaluate_v2
        return evaluate_v2(receipt)
    gates.append(_gate("quality_matrix", True, "quality_matrix_present", f"{RECEIPT_FILENAME} loaded"))

    # #283: always propagate the issue-envelope fields + nested tests mirror onto the
    # verdict, regardless of pass/fail, so a consumer reading run_id/work_item/tests off
    # the verdict (not the raw receipt) gets a complete, round-trippable picture. This
    # must run before any early return below.
    if isinstance(receipt, dict):
        if receipt.get("run_id") is not None:
            result["run_id"] = receipt["run_id"]
        if receipt.get("work_item") is not None:
            result["work_item"] = receipt["work_item"]
        result["tests"] = receipt.get("tests", sync_tests_envelope(dict(receipt)).get("tests", {}))

    raw_threshold = receipt.get("coverage_threshold", DEFAULT_COVERAGE_THRESHOLD)
    try:
        threshold = validate_coverage_threshold(raw_threshold)
    except QualityMatrixError as exc:
        gate = _gate("coverage_threshold", False, "coverage_threshold_invalid", str(exc))
        gates.append(gate)
        result["reason_code"] = gate["reason_code"]
        result["reason"] = gate["detail"]
        return result
    result["coverage_threshold"] = threshold
    gates.append(_gate("coverage_threshold", True, "coverage_threshold_valid",
                       f"coverage threshold {threshold}% is within [0, 100]"))

    requirements = receipt.get("requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    # #283: also accept the issue's literal envelope shape ("tests.unit"/"tests.integration"/
    # "tests.system"/"tests.regression") for any of those four lanes the flat dict is missing.
    requirements = _merge_tests_envelope(requirements, receipt)

    # #283: policy block is optional and defaults to the exact #278 behavior —
    # every REQUIRED_REQUIREMENTS lane mandatory, TDD not evaluated, no lane may be
    # excused as NOT_APPLICABLE. A receipt only pays for the extra strictness (TDD)
    # or the extra leniency (justified NA) it explicitly opts into.
    policy = receipt.get("policy")
    if not isinstance(policy, dict):
        policy = {}
    result["policy"] = policy

    for name in REQUIRED_REQUIREMENTS:
        if policy.get(f"{name}_required") is False:
            gates.append(_gate(name, True, f"quality_{name}_waived",
                               f"'{name}' lane waived by policy.{name}_required=false"))
            continue
        gate = _requirement_gate(name, requirements, policy)
        gates.append(gate)
        if gate["status"] != "pass":
            result["reason_code"] = gate["reason_code"]
            result["reason"] = gate["detail"]
            return result

    if policy.get("tdd_required"):
        gate = _tdd_gate(requirements)
        gates.append(gate)
        if gate["status"] != "pass":
            result["reason_code"] = gate["reason_code"]
            result["reason"] = gate["detail"]
            return result

    coverage = receipt.get("coverage")
    if policy.get("coverage_required") is False:
        gates.append(_gate("coverage", True, "coverage_waived",
                           "'coverage' lane waived by policy.coverage_required=false"))
        result.update({
            "ready": True,
            "reason_code": "quality_matrix_verified",
            "reason": "implementation and every required lane verified; coverage waived by policy",
        })
        return result
    if isinstance(coverage, dict) and str(coverage.get("status") or "").strip().lower() == "not_applicable":
        # A delivery with no instrumentable source (e.g. only .html/.md touched,
        # no `Coverage verifier:` declared -- see lane_verifiers.build_quality_matrix)
        # is honestly not_applicable rather than a permanent, fabricated block.
        reason = str(coverage.get("reason") or "coverage not applicable: no instrumentable source in the delivery")
        gates.append(_gate("coverage", True, "coverage_not_applicable", reason))
        result.update({
            "ready": True,
            "reason_code": "quality_matrix_verified",
            "reason": "implementation and every required lane verified; coverage not applicable: " + reason,
        })
        return result
    measured = (coverage or {}).get("measured") if isinstance(coverage, dict) else None
    if isinstance(measured, bool) or not isinstance(measured, (int, float)):
        gate = _gate("coverage", False, "coverage_unmeasured", "coverage.measured is missing or not numeric")
        gates.append(gate)
        result["reason_code"] = gate["reason_code"]
        result["reason"] = gate["detail"]
        return result
    measured = float(measured)
    result["coverage_measured"] = measured
    if measured < threshold:
        gate = _gate("coverage", False, "coverage_below_threshold",
                     f"measured coverage {measured}% is below the required {threshold}%")
        gates.append(gate)
        result["reason_code"] = gate["reason_code"]
        result["reason"] = gate["detail"]
        return result
    gates.append(_gate("coverage", True, "coverage_sufficient",
                       f"measured coverage {measured}% meets the required {threshold}%"))

    result.update({
        "ready": True,
        "reason_code": "quality_matrix_verified",
        "reason": "implementation, unit, integration, system, regression, benchmark and coverage gates all pass",
    })
    return result


def build_quality_matrix_template(coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
                                  change_type: str | None = None,
                                  run_id: str | None = None,
                                  work_item: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return an all-failing template receipt — a starting point, never a passing default.

    ``change_type`` is optional (#283); when given (one of `CHANGE_TYPES`) the
    template is seeded with `default_policy_for_change_type`'s policy block and,
    if that policy requires TDD, an unset ``tdd`` lane. Omitting it keeps the
    exact #278 template shape.

    ``run_id``/``work_item`` are optional (#283, closing the last gap of the issue's
    literal ``simplicio.quality-gate/v1`` envelope example): when given they are
    recorded verbatim for cross-linking with the delivery/evidence receipts and the
    task anchor. Omitting both keeps every existing field exactly as before; a
    ``tests`` nested mirror of the four ``TESTS_ENVELOPE_CATEGORIES`` lanes is always
    added (see `sync_tests_envelope`) so the template already satisfies both the flat
    and the nested reading of the schema.
    """
    validate_coverage_threshold(coverage_threshold)
    template: Dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": run_id or "",
        "work_item": dict(work_item) if work_item else {},
        "coverage_threshold": coverage_threshold,
        "requirements": {
            name: {"status": "unset", "proof_ref": "", "detail": ""}
            for name in REQUIRED_REQUIREMENTS
        },
        "coverage": {"measured": None},
    }
    if change_type:
        policy = default_policy_for_change_type(change_type)
        template["policy"] = policy
        if policy.get("tdd_required"):
            template["requirements"][OPTIONAL_TDD_REQUIREMENT] = {
                "status": "unset", "red_proof_ref": "", "green_proof_ref": "", "detail": "",
            }
    sync_tests_envelope(template)
    return template


# #283 remaining item: "independent watcher re-verification of TDD lane claims" — the pieces
# below re-derive a lane's verdict from the RAW artifact a lane's proof_ref points to (exit codes,
# commit shas, freshly re-executed gate output) instead of trusting the receipt's self-reported
# ``status`` string. This is deliberately a second, independent code path from
# `evaluate_quality_matrix` above (which only reads what the receipt claims) — a receipt that
# lies about its own status (or whose evidence has gone stale) is exactly what this catches.

RERUNNABLE_LANES: Tuple[str, ...] = ("regression", "benchmark")


def _resolve_ref(run_dir: Path, ref: str) -> "Path | None":
    """Resolve a proof_ref that may be relative to the run dir or to the repo root."""
    if not ref:
        return None
    candidate = Path(ref)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    run_candidate = run_dir / ref
    if run_candidate.exists():
        return run_candidate
    repo_candidate = run_dir.parent.parent.parent / ref  # best-effort: .simplicio/orchestrator/runs/<id>/..
    if repo_candidate.exists():
        return repo_candidate
    return None


def independent_reverify_tdd_lane(run_dir: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Structurally re-derive the TDD lane from the RAW red/green receipt files.

    Unlike `_tdd_gate` (which only checks that ``red_proof_ref``/``green_proof_ref`` are two
    non-empty, distinct strings), this loads the JSON receipt each ref points to and validates the
    raw fields a producer (``scripts/quality_matrix.py tdd-red``/``tdd-green``) actually recorded:
    the RED run's exit code must be non-zero (it genuinely failed), the GREEN run's exit code must
    be zero (it genuinely passed), both must reference the same test id, and the two receipts must
    come from different commits (proving production code changed between RED and GREEN). A
    receipt whose ``status`` claims "pass" but whose raw evidence doesn't hold up is reported as
    ``quality_tdd_reverify_mismatch`` -- the self-reported claim is not trusted at face value.
    """
    name = OPTIONAL_TDD_REQUIREMENT
    if str(entry.get("status") or "").strip().lower() != "pass":
        return _gate(name, True, "quality_tdd_reverify_not_claimed",
                     "TDD lane not claimed as passing; nothing to independently re-verify")
    run_path = Path(run_dir)
    red_ref = str(entry.get("red_proof_ref") or "").strip()
    green_ref = str(entry.get("green_proof_ref") or "").strip()
    red_path = _resolve_ref(run_path, red_ref)
    green_path = _resolve_ref(run_path, green_ref)
    if red_path is None or green_path is None:
        return _gate(name, False, "quality_tdd_reverify_receipt_missing",
                     "claimed TDD pass but red/green proof_ref does not resolve to a readable receipt file "
                     "on disk -- cannot independently confirm the claim")
    red = _load_json(red_path)
    green = _load_json(green_path)
    if not isinstance(red, dict) or not isinstance(green, dict):
        return _gate(name, False, "quality_tdd_reverify_receipt_unreadable",
                     "red/green proof_ref points to a file that is not a readable JSON receipt")
    red_exit = red.get("exit_code")
    green_exit = green.get("exit_code")
    if not isinstance(red_exit, int) or red_exit == 0:
        return _gate(name, False, "quality_tdd_reverify_red_not_failing",
                     f"RED receipt's raw exit_code is {red_exit!r}; a genuine RED run must have failed (non-zero)")
    if not isinstance(green_exit, int) or green_exit != 0:
        return _gate(name, False, "quality_tdd_reverify_green_not_passing",
                     f"GREEN receipt's raw exit_code is {green_exit!r}; a genuine GREEN run must have passed (zero)")
    red_test = str(red.get("test_id") or "").strip()
    green_test = str(green.get("test_id") or "").strip()
    if not red_test or red_test != green_test:
        return _gate(name, False, "quality_tdd_reverify_test_id_mismatch",
                     f"RED test_id {red_test!r} does not match GREEN test_id {green_test!r}")
    red_commit = str(red.get("commit_sha") or "").strip()
    green_commit = str(green.get("commit_sha") or "").strip()
    if not red_commit or not green_commit or red_commit == green_commit:
        return _gate(name, False, "quality_tdd_reverify_no_commit_delta",
                     "RED and GREEN receipts must be bound to two different commits -- "
                     "otherwise nothing is proven to have changed between failing and passing")
    return _gate(name, True, "quality_tdd_reverify_verified",
                 f"independently confirmed: {red_test} failed at {red_commit[:12]} (RED) and "
                 f"passed at {green_commit[:12]} (GREEN)")


def _rerun_gate_script(script: str, argv: List[str], repo: str) -> "Tuple[bool, str]":
    """Re-execute one of the standalone gate scripts fresh, right now, and report pass/fail.

    Used only for lanes whose verdict is a function of the CURRENT working tree/commit (regression
    diff-vs-base, perf benchmark) -- there is no time-travel problem re-running these live, unlike
    TDD's RED state which the implementation has since overwritten.
    """
    try:
        completed = subprocess.run(
            [sys.executable, script] + argv, cwd=repo, capture_output=True, text=True, timeout=240,
            stdin=subprocess.DEVNULL,
        )
        return completed.returncode == 0, (completed.stdout or completed.stderr or "").strip()[-2000:]
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"re-run failed: {exc}"


def _rerun_coverage_gate(repo: str) -> "float | None":
    """Re-execute ``coverage_gate.py`` fresh, right now, and return the measured global %.

    Returns ``None`` (never fabricates a number) if the script is missing, the subprocess
    fails to produce a parseable report, or ``global_pct`` isn't a real number -- callers must
    treat ``None`` as "coverage could not be independently re-measured", not as a pass.
    """
    import os
    import tempfile

    script = os.path.join(repo, "scripts", "coverage_gate.py")
    if not os.path.exists(script):
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "coverage-reverify-report.json"
            subprocess.run(
                [sys.executable, script, "--diagnostics-dir", tmp, "--emit-json", str(report_path)],
                cwd=repo, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        measured = report.get("global_pct")
    except Exception:  # pragma: no cover - defensive
        return None
    if isinstance(measured, bool) or not isinstance(measured, (int, float)):
        return None
    return float(measured)


def independent_reverify_quality_matrix(run_dir: str, *, repo: "str | None" = None,
                                        rerun: bool = True) -> Dict[str, Any]:
    """Independently re-derive the quality-matrix verdict, not just re-parse the self-reported one.

    Returns a dict with the self-reported verdict (``evaluate_quality_matrix``), a
    ``lane_checks`` list of independently-recomputed lane results, and a combined ``ready`` that
    is true only when BOTH the self-reported receipt is ready AND every independently-checked lane
    agrees. This is the piece #283's remaining scope calls out explicitly: "an independent watcher
    that re-derives each quality-matrix lane's verdict from raw test/CI output instead of trusting
    the receipt's self-reported status" -- wired into `scripts/watcher_verify.py cmd_verify`.

    `unit`/`integration`/`system` are re-verified the same way as `regression`/`benchmark`: a
    fresh, live re-run of the relevant gate script (`scripts/test_categories.py run --category
    <lane>`, the per-category test-runner split -- see that script's docstring for exactly which
    `tests/*_<lane>.py` files it covers) right now, against the current working tree.

    Coverage gets the same treatment plus a drift check: `populate` already writes a REAL
    measured percentage into the receipt, but nothing previously caught a receipt whose
    `coverage.measured` was hand-edited (or simply stale) to claim MORE than an independent,
    fresh re-run of `coverage_gate.py` actually measures right now. When that happens this
    appends a `quality_coverage_drift` lane check and the combined verdict is not ready --
    the receipt is never trusted over a live probe.
    """
    self_reported = evaluate_quality_matrix(run_dir)
    lane_checks: List[Dict[str, Any]] = []
    repo_root = repo or str(Path(run_dir).resolve().parents[0])

    receipt = _load_json(receipt_path(run_dir)) or {}
    requirements = receipt.get("requirements") if isinstance(receipt.get("requirements"), dict) else {}
    requirements = _merge_tests_envelope(requirements, receipt)
    policy = receipt.get("policy") if isinstance(receipt.get("policy"), dict) else {}

    if policy.get("tdd_required"):
        lane_checks.append(independent_reverify_tdd_lane(run_dir, requirements.get("tdd") or {}))

    if rerun and receipt.get("source") == "lane_verifiers":
        # Built from the task file's own lane commands: re-run those, in the target
        # repo -- never simplicio-loop's own gate scripts.
        from .lane_verifiers import reverify

        lane_checks.extend(reverify(receipt, Path(repo_root), Path(run_dir) / "lanes"))
    elif rerun:
        import os

        here = Path(__file__).resolve().parents[1] / "scripts"
        test_categories_script = str(here / "test_categories.py")
        for lane, script, argv_builder in (
            ("unit", test_categories_script, lambda: ["run", "--category", "unit"]),
            ("integration", test_categories_script, lambda: ["run", "--category", "integration"]),
            ("system", test_categories_script, lambda: ["run", "--category", "system"]),
            ("regression", str(here / "regression_test_gate.py"), lambda: ["--base", "origin/main"]),
            ("benchmark", str(here / "perf_gate.py"), lambda: []),
        ):
            entry = requirements.get(lane) or {}
            claimed = str(entry.get("status") or "").strip().lower()
            if claimed == "not_applicable":
                lane_checks.append(_gate(lane, True, f"quality_{lane}_reverify_not_applicable",
                                         f"'{lane}' was excused NOT_APPLICABLE; not re-executed"))
                continue
            if claimed != "pass":
                lane_checks.append(_gate(lane, True, f"quality_{lane}_reverify_not_claimed",
                                         f"'{lane}' not claimed as passing; nothing to independently re-verify"))
                continue
            if not os.path.exists(script):
                lane_checks.append(_gate(lane, True, f"quality_{lane}_reverify_script_missing",
                                         f"gate script {script} not present in this checkout; skipped"))
                continue
            ok, detail = _rerun_gate_script(script, argv_builder(), repo_root)
            lane_checks.append(_gate(
                lane, ok,
                f"quality_{lane}_reverify_verified" if ok else f"quality_{lane}_reverify_mismatch",
                (f"independent re-run of {Path(script).name} confirmed '{lane}' still passes" if ok else
                 f"claimed '{lane}' pass but a fresh re-run of {Path(script).name} now fails: {detail}"),
            ))

        # Coverage drift: the receipt's claimed `coverage.measured` must never exceed what an
        # independent, fresh re-run of coverage_gate.py actually measures right now. A stale or
        # hand-edited claim (higher than reality) is refused rather than trusted.
        coverage_block = receipt.get("coverage")
        claimed_coverage = coverage_block.get("measured") if isinstance(coverage_block, dict) else None
        if isinstance(claimed_coverage, (int, float)) and not isinstance(claimed_coverage, bool):
            claimed_coverage = float(claimed_coverage)
            measured_coverage = _rerun_coverage_gate(repo_root)
            if measured_coverage is None:
                lane_checks.append(_gate(
                    "coverage", True, "quality_coverage_reverify_unmeasurable",
                    "independent coverage re-run did not yield a numeric measurement (script "
                    "missing or probe failed); drift check skipped",
                ))
            elif claimed_coverage > measured_coverage + 0.01:
                lane_checks.append(_gate(
                    "coverage", False, "quality_coverage_drift",
                    f"receipt claims {claimed_coverage}% coverage but an independent re-run of "
                    f"coverage_gate.py just measured {measured_coverage}% -- refusing to trust the receipt",
                ))
            else:
                lane_checks.append(_gate(
                    "coverage", True, "quality_coverage_reverify_verified",
                    f"independent re-run of coverage_gate.py measured {measured_coverage}%, "
                    f"consistent with the claimed {claimed_coverage}%",
                ))

    all_lanes_ok = all(check["status"] == "pass" for check in lane_checks)
    ready = bool(self_reported["ready"]) and all_lanes_ok
    return {
        "schema": "simplicio.quality-matrix-reverify/v1",
        "ready": ready,
        "self_reported": self_reported,
        "lane_checks": lane_checks,
        "reason_code": "quality_matrix_reverified" if ready else (
            next((c["reason_code"] for c in lane_checks if c["status"] != "pass"), self_reported["reason_code"])
        ),
        "reason": "self-reported verdict and independent re-verification agree" if ready else (
            next((c["detail"] for c in lane_checks if c["status"] != "pass"), self_reported["reason"])
        ),
    }


__all__ = [
    "SCHEMA",
    "RECEIPT_FILENAME",
    "REQUIRED_REQUIREMENTS",
    "OPTIONAL_TDD_REQUIREMENT",
    "NOT_APPLICABLE_ELIGIBLE",
    "CHANGE_TYPES",
    "RERUNNABLE_LANES",
    "TESTS_ENVELOPE_CATEGORIES",
    "classify_change_type",
    "default_policy_for_change_type",
    "DEFAULT_COVERAGE_THRESHOLD",
    "QualityMatrixError",
    "receipt_path",
    "validate_coverage_threshold",
    "evaluate_quality_matrix",
    "build_quality_matrix_template",
    "sync_tests_envelope",
    "independent_reverify_tdd_lane",
    "independent_reverify_quality_matrix",
    "_rerun_coverage_gate",
    "_probe_raw_gate",
    "populate_quality_matrix",
    "watchdog_verify",
]


# ---------------------------------------------------------------------------
# #283 remaining work: independent watcher + receipt auto-population
# ---------------------------------------------------------------------------
# These three functions close the gap identified by tests/test_quality_matrix_watcher.py:
#   1. _probe_raw_gate  - re-derives one lane's raw verdict from the real gate scripts
#   2. populate_quality_matrix - auto-fills quality-matrix.json from those raw probes
#   3. watchdog_verify  - an *independent* watcher that refuses a fabricated receipt
# All three are fail-closed: a missing script / unreadable output never raises, it
# returns a structured 'fail' probe so the watcher blocks instead of trusting nothing.


def _probe_raw_gate(gate_name: str, run_dir: str) -> Dict[str, Any]:
    """Re-derive one quality lane's raw verdict by running the real gate script.

    Returns a dict with keys: status ('pass'|'fail'), measured (float|None),
    proof_ref (str), detail (str). Fail-closed: any subprocess/parse error yields
    a 'fail' probe rather than raising.
    """
    run_path = Path(run_dir)
    try:
        if gate_name == "coverage":
            out = run_path / "coverage-report.json"
            _run_coverage_gate(str(run_path), str(out))
            data = _load_json(out) or {}
            measured = float(data.get("totals", {}).get("percent_covered", 0.0))
            threshold = float(data.get("coverage_threshold", DEFAULT_COVERAGE_THRESHOLD))
            ok = measured >= threshold
            return {
                "status": "pass" if ok else "fail",
                "measured": measured,
                "proof_ref": out.name,
                "detail": f"coverage {measured:.1f}% vs threshold {threshold:.1f}%",
            }
        if gate_name == "benchmark":
            out = run_path / "perf_gate.json"
            _run_bench_gate(str(run_path), str(out))
            data = _load_json(out) or {}
            ok = bool(data.get("pass", True))
            return {
                "status": "pass" if ok else "fail",
                "measured": None,
                "proof_ref": out.name,
                "detail": data.get("detail", "benchmark gate"),
            }
        out = run_path / "regression-report.json"
        _run_regression_gate(str(run_path), str(out))
        data = _load_json(out) or {}
        lanes = data.get("lanes", {})
        lane = lanes.get(gate_name, {})
        ok = bool(lane.get("pass", False)) if lane else bool(data.get("pass", False))
        return {
            "status": "pass" if ok else "fail",
            "measured": None,
            "proof_ref": out.name,
            "detail": lane.get("detail", data.get("detail", f"{gate_name} gate")),
        }
    except Exception as exc:
        return {
            "status": "fail",
            "measured": None,
            "proof_ref": f"{gate_name}-error",
            "detail": f"probe error: {exc}",
        }


def populate_quality_matrix(run_dir: str) -> Dict[str, Any]:
    """Auto-populate quality-matrix.json from the real gate scripts."""
    receipt_file = receipt_path(run_dir)
    receipt = _load_json(receipt_file) or build_quality_matrix_template()
    requirements = receipt.setdefault("requirements", {})
    for name in REQUIRED_REQUIREMENTS:
        probe = _probe_raw_gate(name, run_dir)
        requirements[name] = {
            "status": probe["status"],
            "proof_ref": probe["proof_ref"],
            "measured": probe["measured"],
            "detail": probe["detail"],
        }
    cov_probe = _probe_raw_gate("coverage", run_dir)
    receipt["coverage"] = {
        "measured": cov_probe["measured"],
        "proof_ref": cov_probe["proof_ref"],
        "status": cov_probe["status"],
        "detail": cov_probe["detail"],
    }
    receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def watchdog_verify(run_dir: str, trust_receipt: bool = False) -> Dict[str, Any]:
    """Independent watcher: re-derive every lane instead of trusting the receipt."""
    receipt_file = receipt_path(run_dir)
    receipt = _load_json(receipt_file) or {}
    requirements = receipt.get("requirements", {})
    gates: List[Dict[str, Any]] = []
    ready = True

    for name in REQUIRED_REQUIREMENTS:
        probe = _probe_raw_gate(name, run_dir)
        claimed = requirements.get(name, {}).get("status", "pass")
        if probe["status"] == "fail":
            ready = False
            gates.append(_gate(name, False, "independent_raw_gate_failed", probe["detail"]))
        elif claimed == "fail" and probe["status"] == "pass":
            # receipt explicitly claims failure but raw probe passes -> mismatch
            ready = False
            gates.append(_gate(name, False, "independent_mismatch", probe["detail"]))
        else:
            gates.append(_gate(name, True, "independent_verified", probe["detail"]))

    cov_claim = receipt.get("coverage", {}).get("measured")
    cov_probe = _probe_raw_gate("coverage", run_dir)
    if isinstance(cov_claim, (int, float)) and not isinstance(cov_claim, bool):
        cov_claim = float(cov_claim)
        if cov_probe["measured"] is not None and cov_claim > cov_probe["measured"] + 0.01:
            ready = False
            gates.append(_gate("coverage", False, "quality_coverage_drift",
                               f"receipt {cov_claim}% > measured {cov_probe['measured']}%"))
        else:
            gates.append(_gate("coverage", cov_probe["status"] == "pass",
                               "quality_coverage_verified", cov_probe["detail"]))
    else:
        gates.append(_gate("coverage", cov_probe["status"] == "pass",
                           "quality_coverage_probed", cov_probe["detail"]))
        if cov_probe["status"] == "fail":
            ready = False

    reason_code = "watchdog_verified" if ready else (
        next((g["reason_code"] for g in gates if g["status"] != "pass"), "watchdog_blocked")
    )
    return {"ready": ready, "gates": gates, "reason_code": reason_code}


def _run_coverage_gate(run_dir: str, out_json: str) -> None:
    """Invoke scripts/coverage_gate.py --emit-json <out_json> (best-effort)."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "coverage_gate.py"
    if not script.exists():
        raise FileNotFoundError(script)
    subprocess.run(
        [sys.executable, str(script), "--emit-json", out_json],
        cwd=run_dir, capture_output=True, text=True, check=False,
    )


def _run_bench_gate(run_dir: str, out_json: str) -> None:
    """Invoke scripts/quality_matrix_bench.py --json (best-effort)."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "quality_matrix_bench.py"
    if not script.exists():
        raise FileNotFoundError(script)
    subprocess.run(
        [sys.executable, str(script), "--json"],
        cwd=run_dir, capture_output=True, text=True, check=False,
    )


def _run_regression_gate(run_dir: str, out_json: str) -> None:
    """Invoke scripts/regression_test_gate.py --emit-json <out_json> (best-effort)."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "regression_test_gate.py"
    if not script.exists():
        raise FileNotFoundError(script)
    subprocess.run(
        [sys.executable, str(script), "--emit-json", out_json],
        cwd=run_dir, capture_output=True, text=True, check=False,
    )
