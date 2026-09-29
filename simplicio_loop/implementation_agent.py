"""Concrete `implementation_agent` stage-agent role (#426, EPIC #422 "Portable Stage Agents").

Issue #426 asks for the ONLY role authorized to execute plan-approved changes,
bounded by AC/path/capability, inside an isolated workspace -- and structurally
unable to self-approve review, safety or delivery. `contracts/stage-agents/v1/
stages.json` already registers the `implementation_agent` role and its
`executing` stage (#423); `stage_agent_coordinator.py` (#424) already drives
generic instances/adapters through it. What #426 actually adds, and what this
module implements, is the role's *own* invariant machinery: an AC+path scoped
assignment, mutation-capability enforcement at every write boundary, base/plan/
fence drift detection, failure classification, a retry budget
that never relaxes AC/tests, and a typed
`simplicio.implementation-stage-receipt/v1` that can never itself claim
delivery/completion.

This module is data-only and model-free, the same discipline as
`intake_planner.py`: it assembles and gates artifacts that already exist (an
operator's reported diff/tests/exit-codes); it never invents a passing test,
never edits the plan/ACs, and never writes a reviewer/safety/delivery receipt.
Invoking the real bound operator (`simplicio-dev-cli task`, per AGENTS.md) is
the caller's job -- this module defines the assignment, the boundary, and the
receipt/gate the caller's invocation must satisfy.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

IMPLEMENTATION_STAGE_RECEIPT_SCHEMA = "simplicio.implementation-stage-receipt/v1"
IMPLEMENTATION_AGENT_ROLE_ID = "implementation_agent"

# Verdicts for the #426 typed receipt.
VERDICT_PASS = "pass"
VERDICT_BLOCKED = "blocked"
VERDICT_FAILED = "failed"

# Failure classification (issue plan step 9): "Classificar falhas: code, test,
# toolchain, dependency, capability, lease, scope."
FAILURE_CLASSES = frozenset((
    "code", "test", "toolchain", "dependency", "capability", "lease", "scope",
))

# Receipts this role is categorically forbidden from ever writing (invariant 6:
# "Implementador não escreve receipts de reviewer/safety/delivery.").
FORBIDDEN_RECEIPT_SCHEMAS = frozenset((
    "simplicio.review-receipt/v1",
    "simplicio.safety-receipt/v1",
    "simplicio.delivery-receipt/v1",
    "simplicio.completion-receipt/v1",
))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


class ImplementationAgentError(ValueError):
    """Base error for the implementation_agent role. Fail-closed, never silent."""

    def __init__(self, message: str, *, reason_code: str = "implementation_agent_error"):
        super().__init__(message)
        self.reason_code = reason_code


class MutationCapabilityError(ImplementationAgentError):
    """Raised when a write is attempted without a currently-valid mutation capability
    (invariant 2)."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="capability")


class PathBoundaryError(ImplementationAgentError):
    """Raised when a touched path falls outside the AC-scoped allowlist (invariant 3)."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="scope")


class DriftError(ImplementationAgentError):
    """Raised when base/plan/fence drift is detected before commit (invariant 4)."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="lease")


class ForbiddenReceiptError(ImplementationAgentError):
    """Raised when this role is asked to write a reviewer/safety/delivery receipt
    (invariant 6)."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="capability")


# --------------------------------------------------------------------------- #
# 1. Assignment schema -- keyed by AC + path (plan step 2).
# --------------------------------------------------------------------------- #
def build_assignment(
    *,
    task_id: str,
    plan_revision: int,
    acs: Sequence[str],
    allowed_paths: Sequence[str],
    expected_tests: Sequence[str],
    base_sha: str,
    lease_id: str,
    fence: str,
    timeout_seconds: int = 1800,
    retry_budget: int = 3,
) -> Dict[str, Any]:
    """Build a normalized assignment: exactly what this attempt is authorized to touch.

    Every field here is later re-checked at the write boundary and again at
    commit time -- the assignment is not merely descriptive, it is the
    contract the whole receipt is gated against.
    """
    acs_n = [str(a).strip() for a in (acs or ()) if str(a).strip()]
    if not acs_n:
        raise ImplementationAgentError("assignment requires at least one AC", reason_code="scope")
    paths_n = sorted({str(p).replace("\\", "/").strip() for p in (allowed_paths or ()) if str(p).strip()})
    if not paths_n:
        raise ImplementationAgentError("assignment requires at least one allowed path", reason_code="scope")
    assignment = {
        "schema": "simplicio.implementation-assignment/v1",
        "task_id": str(task_id).strip(),
        "plan_revision": int(plan_revision or 0),
        "acs": acs_n,
        "allowed_paths": paths_n,
        "expected_tests": sorted({str(t).strip() for t in (expected_tests or ()) if str(t).strip()}),
        "base_sha": str(base_sha or "").strip(),
        "lease_id": str(lease_id or "").strip(),
        "fence": str(fence or "").strip(),
        "timeout_seconds": int(timeout_seconds),
        "retry_budget": int(retry_budget),
    }
    if not assignment["task_id"]:
        raise ImplementationAgentError("assignment requires task_id", reason_code="scope")
    if not assignment["base_sha"]:
        raise ImplementationAgentError("assignment requires base_sha", reason_code="lease")
    if not assignment["lease_id"] or not assignment["fence"]:
        raise ImplementationAgentError("assignment requires lease_id and fence", reason_code="lease")
    assignment["assignment_hash"] = content_hash({k: v for k, v in assignment.items() if k != "assignment_hash"})
    return assignment


# --------------------------------------------------------------------------- #
# 2. Path allowlist -- fail-closed (invariant 3, plan step 6).
# --------------------------------------------------------------------------- #
def is_path_allowed(path: str, *, allowed_paths: Sequence[str]) -> bool:
    norm = str(path or "").replace("\\", "/").lstrip("./")
    for prefix in allowed_paths:
        p = str(prefix).replace("\\", "/").lstrip("./")
        if norm == p or norm.startswith(p.rstrip("/") + "/") or (p.endswith("*") and norm.startswith(p[:-1])):
            return True
    return False


def check_path_allowlist(touched_paths: Sequence[str], *, allowed_paths: Sequence[str]) -> List[str]:
    """Return the list of out-of-allowlist paths (empty == all in scope). Never raises."""
    return [p for p in (touched_paths or ()) if not is_path_allowed(p, allowed_paths=allowed_paths)]


def assert_path_allowlist_ok(touched_paths: Sequence[str], *, allowed_paths: Sequence[str]) -> None:
    """Fail-closed: raise `PathBoundaryError` if any touched path is out of the allowlist.

    Per invariant 3, an out-of-allowlist path blocks AND invalidates the whole
    attempt -- callers must treat any raise here as the attempt being void,
    not merely that one file being skipped.
    """
    violations = check_path_allowlist(touched_paths, allowed_paths=allowed_paths)
    if violations:
        raise PathBoundaryError(
            "path(s) outside allowlist, attempt invalidated: " + ", ".join(sorted(violations))
        )


# --------------------------------------------------------------------------- #
# 3. Mutation capability -- every write requires a currently-valid capability
#    (invariant 2, plan step 6).
# --------------------------------------------------------------------------- #
def is_capability_valid(capability: Optional[Mapping[str, Any]], *, now: Optional[float] = None) -> bool:
    """A mutation capability is valid iff present, not revoked, and unexpired.

    `capability` shape: `{"token": ..., "expires_at": <epoch seconds>,
    "revoked": bool, "lease_id": ..., "fence": ...}`. A missing/None
    capability is never valid -- there is no implicit grant.
    """
    if not capability:
        return False
    if bool(capability.get("revoked")):
        return False
    if not str(capability.get("token") or "").strip():
        return False
    expires_at = capability.get("expires_at")
    if expires_at is None:
        return False
    now = time.time() if now is None else now
    return float(expires_at) > now


def assert_mutation_capability(capability: Optional[Mapping[str, Any]], *, now: Optional[float] = None) -> None:
    if not is_capability_valid(capability, now=now):
        raise MutationCapabilityError(
            "no currently-valid mutation capability for this write "
            f"(token={(capability or {}).get('token', 'MISSING')!r}, "
            f"revoked={(capability or {}).get('revoked')!r}, "
            f"expires_at={(capability or {}).get('expires_at')!r})"
        )


# --------------------------------------------------------------------------- #
# 4. Base/plan/fence drift -- halts before commit (invariant 4, plan step 6).
# --------------------------------------------------------------------------- #
def detect_drift(
    assignment: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_plan_revision: int,
    current_fence: str,
) -> List[str]:
    """Return a list of drift reasons (empty == no drift). Never raises."""
    reasons: List[str] = []
    if str(current_base_sha or "") != str(assignment.get("base_sha") or ""):
        reasons.append(
            f"base_sha drift: assigned={assignment.get('base_sha')!r} current={current_base_sha!r}"
        )
    if int(current_plan_revision or -1) != int(assignment.get("plan_revision") or 0):
        reasons.append(
            f"plan_revision drift: assigned={assignment.get('plan_revision')!r} current={current_plan_revision!r}"
        )
    if str(current_fence or "") != str(assignment.get("fence") or ""):
        reasons.append(f"fence drift: assigned={assignment.get('fence')!r} current={current_fence!r}")
    return reasons


def assert_no_drift(
    assignment: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_plan_revision: int,
    current_fence: str,
) -> None:
    reasons = detect_drift(
        assignment, current_base_sha=current_base_sha,
        current_plan_revision=current_plan_revision, current_fence=current_fence,
    )
    if reasons:
        raise DriftError("drift detected before commit, halting: " + "; ".join(reasons))


# --------------------------------------------------------------------------- #
# 5. Test evidence -- a self-reported green test with no log/exit-code is
#    rejected (invariant 5).
# --------------------------------------------------------------------------- #
def validate_test_run(test_run: Mapping[str, Any]) -> List[str]:
    """Return validation errors for one reported test-run entry (empty == ok).

    Required: `command`, `exit_code` (an int), and either `log_ref` (a
    content-addressed pointer to captured output) or inline `log_hash`. A
    run missing both is exactly the "self-reported green with no log/exit
    code" case invariant 5 forbids.
    """
    errors: List[str] = []
    if not str(test_run.get("command") or "").strip():
        errors.append("test_run.command is required")
    exit_code = test_run.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        errors.append("test_run.exit_code must be an int")
    if not str(test_run.get("log_ref") or "").strip() and not str(test_run.get("log_hash") or "").strip():
        errors.append("test_run missing both log_ref and log_hash: unverifiable green test rejected")
    return errors


def all_tests_verified(test_runs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate every reported test run. Returns `{"ok": bool, "errors": [...], "passing": bool}`.

    `passing` is only meaningful when `ok` is True: an unverifiable run is
    never treated as passing, regardless of its claimed exit code.
    """
    all_errors: List[str] = []
    for idx, run in enumerate(test_runs or ()):
        for err in validate_test_run(run):
            all_errors.append(f"test_run[{idx}]: {err}")
    ok = not all_errors
    passing = ok and bool(test_runs) and all(int(r.get("exit_code", 1)) == 0 for r in test_runs)
    return {"ok": ok, "errors": all_errors, "passing": passing}


# --------------------------------------------------------------------------- #
# 6. No-change proof -- "No-change só passa com proof-of-satisfying-state"
#    (invariant 8).
# --------------------------------------------------------------------------- #
def validate_no_change_proof(proof: Optional[Mapping[str, Any]]) -> List[str]:
    """A `no_changes_needed` attempt requires objective proof the state already
    satisfies every assigned AC -- never a bare assertion.

    Required shape: `{"ac_id": "already satisfied because ...", ...}` for
    every assigned AC, each entry non-empty, PLUS at least one `test_runs`-
    shaped entry (verified via `all_tests_verified`) or `evidence_refs`
    demonstrating the satisfying state was actually observed, not assumed.
    """
    errors: List[str] = []
    if not proof:
        return ["no_change_proof is required when claiming no changes needed"]
    per_ac = proof.get("ac_satisfied_because") or {}
    if not isinstance(per_ac, Mapping) or not per_ac:
        errors.append("no_change_proof.ac_satisfied_because must be a non-empty mapping of ac_id -> reason")
    else:
        for ac_id, reason in per_ac.items():
            if not str(reason or "").strip():
                errors.append(f"no_change_proof.ac_satisfied_because[{ac_id}] must be non-empty")
    evidence_refs = proof.get("evidence_refs") or []
    test_runs = proof.get("test_runs") or []
    has_evidence = bool(evidence_refs) or (bool(test_runs) and all_tests_verified(test_runs)["passing"])
    if not has_evidence:
        errors.append("no_change_proof requires evidence_refs or verified passing test_runs")
    return errors


def no_change_ok(*, acs: Sequence[str], proof: Optional[Mapping[str, Any]]) -> bool:
    errs = validate_no_change_proof(proof)
    if errs:
        return False
    covered = set((proof or {}).get("ac_satisfied_because") or {})
    return covered.issuperset({str(a) for a in acs})


# --------------------------------------------------------------------------- #
# 7. Surface expansion -- forces a return to planner/impact-gate (invariant 9,
#    plan step 8: re-run impact audit when the changed surface diverges).
# --------------------------------------------------------------------------- #
def surface_expanded(*, allowed_paths: Sequence[str], changed_paths: Sequence[str]) -> List[str]:
    """Return the subset of `changed_paths` outside `allowed_paths` (empty == no expansion)."""
    return check_path_allowlist(changed_paths, allowed_paths=allowed_paths)


def requires_impact_reaudit(*, allowed_paths: Sequence[str], changed_paths: Sequence[str],
                             dependency_delta: Optional[Mapping[str, Any]] = None) -> bool:
    """True when the changed surface diverges from the plan and must return to
    planner/impact-gate instead of proceeding to commit."""
    if surface_expanded(allowed_paths=allowed_paths, changed_paths=changed_paths):
        return True
    if dependency_delta and dependency_delta.get("issues"):
        return True
    return False


# --------------------------------------------------------------------------- #
# 9. Failure classification (plan step 9).
# --------------------------------------------------------------------------- #
def classify_failure(*, reason_code: str, detail: str = "") -> str:
    """Map a raw reason to one of `FAILURE_CLASSES`. Defaults to 'code' (the
    most conservative bucket -- never silently 'unclassified')."""
    code = str(reason_code or "").strip().lower()
    if code in FAILURE_CLASSES:
        return code
    alias_map = {
        "timeout": "toolchain", "spawn_failed": "toolchain", "not_ready": "toolchain",
        "not_passed": "test", "test_failed": "test", "missing_dependency": "dependency",
        "import_error": "dependency", "lease_lost": "lease", "stale_lease": "lease",
        "expired": "lease", "revoked": "capability", "unauthorized": "capability",
        "out_of_scope": "scope", "path_violation": "scope", "drift": "lease",
    }
    return alias_map.get(code, "code")


# --------------------------------------------------------------------------- #
# 10. Retry budget -- applied without relaxing AC/tests (plan step 10,
#     invariant 7: retry gets a new instance/attempt).
# --------------------------------------------------------------------------- #
def next_attempt(*, assignment: Mapping[str, Any], prior_attempts: int, reason_code: str) -> Dict[str, Any]:
    """Compute whether a retry is authorized, and its (new) attempt number.

    A retry NEVER reuses the prior attempt id/worktree -- the caller must
    allocate a fresh one (invariant 7: "worktree antiga é reconciliada").
    Exhausting the retry budget returns `retry_allowed=False`; the ACs/tests
    themselves are never relaxed to force a pass.
    """
    budget = int(assignment.get("retry_budget") or 0)
    retry_allowed = prior_attempts < budget
    return {
        "retry_allowed": retry_allowed,
        "attempt_number": prior_attempts + 1 if retry_allowed else prior_attempts,
        "reason_code": classify_failure(reason_code=reason_code),
        "retry_budget": budget,
        "prior_attempts": prior_attempts,
    }


# --------------------------------------------------------------------------- #
# 11. Reconciliation stub for cancel/heartbeat/recovery (plan step 12 -- may
#     be minimal/stubbed but the surface must exist and be testable).
# --------------------------------------------------------------------------- #
def reconcile_worktree(*, prior_worktree: Mapping[str, Any], new_attempt_id: str) -> Dict[str, Any]:
    """Record the reconciliation of an old worktree/attempt when a retry starts
    a new instance (invariant 7). Minimal/stubbed: returns a receipt-shaped
    dict a coordinator can persist and later extend with real
    cancel/heartbeat wiring, without ever silently dropping the old state."""
    return {
        "schema": "simplicio.implementation-worktree-reconciliation/v1",
        "prior_worktree_id": str(prior_worktree.get("worktree_id") or ""),
        "prior_attempt_id": str(prior_worktree.get("attempt_id") or ""),
        "prior_head_sha": str(prior_worktree.get("head_sha") or ""),
        "new_attempt_id": str(new_attempt_id),
        "reconciled": True,
        "reconciled_at": _now(),
    }


def heartbeat(*, capability: Optional[Mapping[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    """Minimal heartbeat surface (plan step 12): re-checks the mutation
    capability and returns whether the attempt may keep running."""
    alive = is_capability_valid(capability, now=now)
    return {"alive": alive, "checked_at": _now()}


def cancel(*, reason: str) -> Dict[str, Any]:
    """Minimal cancel surface (plan step 12): a stub result a coordinator can
    persist; real process-kill wiring is the coordinator/adapter's job
    (`stage_agent_coordinator.py` already implements kill-tree cancellation)."""
    return {"cancelled": True, "reason": str(reason or ""), "cancelled_at": _now()}


# --------------------------------------------------------------------------- #
# 12. Boundary: this role never writes reviewer/safety/delivery receipts, and
#     never alters the plan/ACs (invariants 1 and 6).
# --------------------------------------------------------------------------- #
def assert_receipt_schema_allowed(schema: str) -> None:
    if str(schema) in FORBIDDEN_RECEIPT_SCHEMAS:
        raise ForbiddenReceiptError(
            f"implementation_agent may never write a {schema!r} receipt "
            "(reviewer/safety/delivery are independent roles)"
        )


def assert_acs_unchanged(*, assigned_acs: Sequence[str], reported_acs: Sequence[str]) -> None:
    """Fail-closed: the implementer may report AC coverage, but the SET of ACs
    itself must never be a superset/different set than what was assigned
    (invariant 1: implementer never alters the plan or ACs)."""
    assigned = {str(a) for a in assigned_acs}
    reported = {str(a) for a in reported_acs}
    extra = reported - assigned
    if extra:
        raise ImplementationAgentError(
            f"implementer may not introduce ACs outside the assigned set: {sorted(extra)}",
            reason_code="scope",
        )


# --------------------------------------------------------------------------- #
# 13. The composed #426 receipt.
# --------------------------------------------------------------------------- #
def build_implementation_stage_receipt(
    *,
    run_id: str,
    attempt: int,
    assignment: Mapping[str, Any],
    current_base_sha: str,
    current_plan_revision: int,
    current_fence: str,
    capability: Optional[Mapping[str, Any]],
    touched_paths: Sequence[str],
    changed_paths: Sequence[str],
    ac_coverage: Mapping[str, str],
    test_runs: Sequence[Mapping[str, Any]] = (),
    diff_ref: str = "",
    head_sha: str = "",
    operator_receipt: Optional[Mapping[str, Any]] = None,
    routing_receipt: Optional[Mapping[str, Any]] = None,
    dependency_delta: Optional[Mapping[str, Any]] = None,
    artifacts: Optional[Sequence[str]] = None,
    no_changes_needed: bool = False,
    no_change_proof: Optional[Mapping[str, Any]] = None,
    failure_reason_code: str = "",
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the typed `simplicio.implementation-stage-receipt/v1`.

    Fail-closed by construction: `PathBoundaryError`/`MutationCapabilityError`/
    `DriftError` are raised (not silently downgraded to a checklist entry)
    the same way `intake_planner.assert_boundary_ok` raises -- an invalid
    attempt must never produce a receipt that looks like an ordinary
    BLOCKED verdict, because per invariant 3 the whole attempt is void.

    `ac_coverage`: `{ac_id: "satisfied" | "pending"}` for every assigned AC.
    An AC missing from this mapping is treated as pending, never silently
    dropped. Per invariant 10, a `pass` verdict here NEVER by itself means
    the task is complete -- see `next_stage_hint` below, always
    `"review"`/`"safety"` never `"delivered"`/`"complete"`.
    """
    # Invariant 6, wired at the real entrypoint (not just unit-tested in
    # isolation): this role's receipt schema must never collide with a
    # forbidden reviewer/safety/delivery schema.
    assert_receipt_schema_allowed(IMPLEMENTATION_STAGE_RECEIPT_SCHEMA)

    assigned_acs = assignment.get("acs") or []
    allowed_paths = assignment.get("allowed_paths") or []

    assert_acs_unchanged(assigned_acs=assigned_acs, reported_acs=list(ac_coverage.keys()))

    # Fail-closed checks -- any of these raises and voids the whole attempt.
    assert_mutation_capability(capability, now=now)
    assert_path_allowlist_ok(touched_paths, allowed_paths=allowed_paths)
    assert_no_drift(
        assignment, current_base_sha=current_base_sha,
        current_plan_revision=current_plan_revision, current_fence=current_fence,
    )

    test_validation = all_tests_verified(test_runs)
    expansion_paths = surface_expanded(allowed_paths=allowed_paths, changed_paths=changed_paths)
    needs_reaudit = requires_impact_reaudit(
        allowed_paths=allowed_paths, changed_paths=changed_paths, dependency_delta=dependency_delta,
    )

    no_change_errors: List[str] = []
    no_change_verified = True
    if no_changes_needed:
        no_change_errors = validate_no_change_proof(no_change_proof)
        no_change_verified = not no_change_errors and no_change_ok(acs=assigned_acs, proof=no_change_proof)

    pending_acs = [ac for ac in assigned_acs if ac_coverage.get(ac) != "satisfied"]
    if no_changes_needed and no_change_verified:
        pending_acs = []

    checklist = {
        "mutation_capability_valid": True,  # would have raised above otherwise
        "paths_in_allowlist": True,  # would have raised above otherwise
        "no_base_plan_fence_drift": True,  # would have raised above otherwise
        "acs_unchanged": True,  # would have raised above otherwise
        "test_evidence_verifiable": test_validation["ok"],
        "no_surface_expansion": not expansion_paths,
        "no_change_proof_ok": no_change_verified if no_changes_needed else True,
        "all_acs_covered_or_pending_explicit": True,  # pending_acs always explicit below
        "operator_receipt_present": bool(operator_receipt),
    }
    failing = [k for k, v in checklist.items() if not v]

    if failure_reason_code:
        verdict = VERDICT_FAILED
    elif needs_reaudit or failing:
        verdict = VERDICT_BLOCKED
    elif pending_acs:
        verdict = VERDICT_BLOCKED
    else:
        verdict = VERDICT_PASS

    receipt: Dict[str, Any] = {
        "schema": IMPLEMENTATION_STAGE_RECEIPT_SCHEMA,
        "role_id": IMPLEMENTATION_AGENT_ROLE_ID,
        "run_id": str(run_id or ""),
        "attempt": int(attempt or 0),
        "task_id": str(assignment.get("task_id") or ""),
        "plan_revision": int(assignment.get("plan_revision") or 0),
        "assignment_hash": str(assignment.get("assignment_hash") or ""),
        "verdict": verdict,
        "checklist": checklist,
        "failing_checks": failing,
        "diff_ref": str(diff_ref or ""),
        "head_sha": str(head_sha or ""),
        "base_sha": str(current_base_sha or ""),
        "changed_paths": sorted({str(p) for p in changed_paths}),
        "surface_expansion_paths": sorted(expansion_paths),
        "requires_impact_reaudit": bool(needs_reaudit),
        "ac_coverage": dict(ac_coverage),
        "acs_satisfied": sorted(ac for ac in assigned_acs if ac_coverage.get(ac) == "satisfied"),
        "acs_pending": sorted(pending_acs),
        "test_runs": [dict(t) for t in test_runs],
        "test_validation": test_validation,
        "no_changes_needed": bool(no_changes_needed),
        "no_change_proof_errors": no_change_errors,
        "dependency_delta": dict(dependency_delta) if dependency_delta else None,
        "artifacts": sorted({str(a) for a in (artifacts or ())}),
        "failure_reason_code": failure_reason_code or None,
        "failure_class": classify_failure(reason_code=failure_reason_code) if failure_reason_code else None,
        "operator_receipt_hash": content_hash(operator_receipt) if operator_receipt else "",
        "routing_receipt_hash": content_hash(routing_receipt) if routing_receipt else "",
        # invariant 10 -- "operator applied" alone never means the task is
        # complete: the only allowed downstream targets from here are the
        # independent safety/review stages, NEVER delivery/completion.
        "next_stage_hint": "safety_gate" if verdict == VERDICT_PASS else "planning",
        "complete": False,
    }
    receipt["receipt_hash"] = content_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return receipt


def receipt_is_passed(receipt: Mapping[str, Any]) -> bool:
    return receipt.get("verdict") == VERDICT_PASS


# --------------------------------------------------------------------------- #
# Stage-agent binding -- projects the #426 receipt into a portable StageReceipt
# (contracts/stage-agents/v1/stages.json already registers this role/stage).
# --------------------------------------------------------------------------- #
def to_stage_receipt(
    implementation_receipt: Mapping[str, Any],
    *,
    receipt_id: str,
    agent_instance_id: str,
    task_id: str,
    attempt_id: str,
    fence: str,
    attempt_ordinal: int = 1,
    context_hash: str = "0" * 64,
    manifest_hash: str = "0" * 64,
) -> Dict[str, Any]:
    """Project the #426 receipt into a `simplicio.stage-receipt/v1`-shaped dict
    (see `simplicio_loop/stage_agents.py::validate_receipt`) for the
    `executing` stage owned by the `implementation_agent` role.

    ``context_hash``/``manifest_hash`` default to a placeholder all-zero hash
    when the caller doesn't have the coordinator's real values on hand (e.g.
    unit tests exercising this projection in isolation) -- a real coordinator-
    driven caller MUST pass the actual values from its `AgentInstance`, or
    `stage_agents.validate_receipt()` will (correctly) reject the mismatch
    against the owning instance.
    """
    verdict_map = {VERDICT_PASS: "pass", VERDICT_BLOCKED: "blocked", VERDICT_FAILED: "fail"}
    verdict = verdict_map.get(implementation_receipt.get("verdict"), "blocked")
    accepted = verdict == "pass"
    ts = _now()
    receipt: Dict[str, Any] = {
        "schema": "simplicio.stage-receipt/v1",
        "receipt_id": str(receipt_id),
        "agent_instance_id": str(agent_instance_id),
        "role_id": IMPLEMENTATION_AGENT_ROLE_ID,
        "stage_id": "executing",
        "run_id": str(implementation_receipt.get("run_id") or ""),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "attempt_ordinal": int(attempt_ordinal),
        "fence": str(fence),
        "plan_revision": int(implementation_receipt.get("plan_revision") or 0),
        "created_at": ts,
        "observed_at": ts,
        "ttl_seconds": 3600,
        "context_hash": str(context_hash),
        "manifest_hash": str(manifest_hash),
        "verdict": verdict,
        "evidence_refs": [str(a) for a in implementation_receipt.get("artifacts") or ()] or ["n/a"],
        "accepted": accepted,
        "reason_code": str(implementation_receipt.get("failure_reason_code") or "ok"),
        "input_hash": content_hash(implementation_receipt.get("assignment_hash") or ""),
        "output_hash": str(implementation_receipt.get("receipt_hash") or content_hash(None)),
        "previous_receipt_hashes": [],
        "covered_acceptance_criteria": [str(a) for a in implementation_receipt.get("acs_satisfied") or ()] or ["n/a"],
        "commands": [str(c) for c in implementation_receipt.get("test_runs") and
                     [t.get("command", "n/a") for t in implementation_receipt.get("test_runs", [])] or ["n/a"]],
        "exit_codes": {},
        "artifact_refs": [str(a) for a in implementation_receipt.get("artifacts") or ()],
        "next_stage_recommendation": str(implementation_receipt.get("next_stage_hint") or "unknown"),
    }
    if not accepted:
        receipt["rejection_reason"] = str(implementation_receipt.get("failure_reason_code") or "not_accepted")
    payload = dict(receipt)
    receipt["integrity_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return receipt


__all__ = [
    "IMPLEMENTATION_STAGE_RECEIPT_SCHEMA",
    "IMPLEMENTATION_AGENT_ROLE_ID",
    "VERDICT_PASS",
    "VERDICT_BLOCKED",
    "VERDICT_FAILED",
    "FAILURE_CLASSES",
    "FORBIDDEN_RECEIPT_SCHEMAS",
    "ImplementationAgentError",
    "MutationCapabilityError",
    "PathBoundaryError",
    "DriftError",
    "ForbiddenReceiptError",
    "content_hash",
    "build_assignment",
    "is_path_allowed",
    "check_path_allowlist",
    "assert_path_allowlist_ok",
    "is_capability_valid",
    "assert_mutation_capability",
    "detect_drift",
    "assert_no_drift",
    "validate_test_run",
    "all_tests_verified",
    "validate_no_change_proof",
    "no_change_ok",
    "surface_expanded",
    "requires_impact_reaudit",
    "classify_failure",
    "next_attempt",
    "reconcile_worktree",
    "heartbeat",
    "cancel",
    "assert_receipt_schema_allowed",
    "assert_acs_unchanged",
    "build_implementation_stage_receipt",
    "receipt_is_passed",
    "to_stage_receipt",
]
