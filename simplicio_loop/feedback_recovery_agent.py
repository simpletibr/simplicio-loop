"""Concrete `feedback_recovery_agent` stage-agent role (#430, EPIC #422 "Portable Stage Agents").

Issue #430 asks for the concrete owner of the post-implementation/post-PR loop: CI
failed, a reviewer requested changes, the default branch moved, a conflict
appeared, delivery was inconclusive, a receipt expired, an external regression
occurred, a worker/stage got stuck. `contracts/stage-agents/v1/stages.json`
already registers the `feedback_recovery_agent` role (#423) -- it is
independent of every other role and forbidden from self-signing
review/security/completion-audit receipts. What this module implements is the
role's *own* invariant machinery: a failure taxonomy + fingerprint, a receipt
invalidation graph, a routing decision reducer that enforces rules 1-10 from
the issue mechanically, a retry-budget tracker per (task, failure class), a
stall/repeated-fingerprint escalation (reusing `scripts/loop_journal.py`'s
stall detector -- NOT reinvented), quarantine/dead-letter, external-effect
reconciliation, and the typed `simplicio.feedback-recovery-receipt/v1`.

This role diagnoses, classifies and hands execution back to the correct
stage. It never fixes anything directly and never declares terminality: the
receipt only ever carries a *request* for the coordinator to apply -- the
coordinator is the one that dispatches the transition (plan step 12).

This module is data-only and model-free, the same discipline as
`implementation_agent.py`/`intake_planner.py`: it assembles and gates
artifacts (CI/check/review/source observations) that already exist; it never
invents a passing check, never edits ACs/scope itself (it only *requests* a
route to the planner when scope drifted), and never writes a review/safety/
delivery/completion receipt.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

# Reuse the repository's stall detector (fingerprint + K-repeat) instead of
# reinventing it -- same discipline as AGENTS.md "READ IT, don't reinvent".
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
try:
    from scripts.loop_journal import fingerprint as _journal_fingerprint  # type: ignore
    from scripts.loop_journal import analyze as _journal_analyze  # type: ignore
    from scripts.loop_journal import DEFAULT_K as _JOURNAL_DEFAULT_K  # type: ignore
except ImportError:  # pragma: no cover - keeps this module importable standalone
    try:
        from loop_journal import fingerprint as _journal_fingerprint  # type: ignore
        from loop_journal import analyze as _journal_analyze  # type: ignore
        from loop_journal import DEFAULT_K as _JOURNAL_DEFAULT_K  # type: ignore
    except ImportError:  # pragma: no cover
        _journal_fingerprint = None
        _journal_analyze = None
        _JOURNAL_DEFAULT_K = 3

FEEDBACK_RECOVERY_RECEIPT_SCHEMA = "simplicio.feedback-recovery-receipt/v1"
FEEDBACK_RECOVERY_ROLE_ID = "feedback_recovery_agent"

# Verdicts for the #430 typed receipt.
VERDICT_ROUTED = "routed"
VERDICT_QUARANTINED = "quarantined"
VERDICT_ESCALATED = "escalated"
VERDICT_RECONCILE_PENDING = "reconcile_pending"

# Minimum failure taxonomy (issue body, verbatim).
FAILURE_CLASSES = frozenset((
    "code_failure", "test_failure", "ci_infra_failure", "review_change_requested",
    "base_drift", "merge_conflict", "delivery_unknown", "source_regression",
    "stale_receipt", "lease_or_fence_loss", "agent_timeout", "capability_missing",
    "security_block", "repeated_fingerprint_stall",
))

# Receipts this role is categorically forbidden from ever writing (this role
# is independent of every other -- `forbidden_to_self_sign` in stages.json:
# review, security, completion_audit).
FORBIDDEN_RECEIPT_SCHEMAS = frozenset((
    "simplicio.review-receipt/v1",
    "simplicio.safety-receipt/v1",
    "simplicio.safety-stage-receipt/v1",
    "simplicio.delivery-receipt/v1",
    "simplicio.completion-receipt/v1",
))

# Stage graph targets a routing decision may name (contracts/stage-agents/v1/stages.json).
STAGE_TARGETS = frozenset((
    "intake", "planning", "executing", "validating", "watching", "delivering", "done",
))
# Non-stage-graph routes: safety is cross-cutting (no dedicated stage_id in the
# graph, same as feedback_recovery_agent itself) and human/blocker handoff.
ROUTE_TARGETS = STAGE_TARGETS | frozenset(("safety_gate", "human"))


class FeedbackRecoveryAgentError(ValueError):
    """Base error for the feedback_recovery_agent role. Fail-closed, never silent."""

    def __init__(self, message: str, *, reason_code: str = "feedback_recovery_error"):
        super().__init__(message)
        self.reason_code = reason_code


class ForbiddenReceiptError(FeedbackRecoveryAgentError):
    """Raised when this role is asked to write a review/safety/delivery/completion
    receipt (the role is structurally independent of every other role)."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="capability_missing")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def signal_fingerprint(text: str) -> str:
    """Stable fingerprint of a failure signal, delegating to the loop's own
    stall-detector fingerprint (deterministic, no LLM). Falls back to a plain
    sha1 of the stripped text if `scripts/loop_journal.py` is unavailable."""
    if _journal_fingerprint is not None:
        return _journal_fingerprint(text)
    text = (text or "").strip()
    if not text:
        return ""
    return hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# 1. Failure classification (issue "Taxonomia minima").
# --------------------------------------------------------------------------- #
_ALIAS_MAP = {
    # code / test
    "test_failed": "test_failure", "assertion_failed": "test_failure",
    "compile_error": "code_failure", "build_failed": "code_failure", "lint_failed": "code_failure",
    # CI infra vs. flaky
    "runner_timeout": "ci_infra_failure", "infra_flake": "ci_infra_failure",
    "network_error": "ci_infra_failure", "oom": "ci_infra_failure",
    # review
    "changes_requested": "review_change_requested", "review_rejected": "review_change_requested",
    # base / conflict
    "base_moved": "base_drift", "rebase_required": "base_drift",
    "conflict": "merge_conflict", "merge_failed": "merge_conflict",
    # delivery
    "delivery_pending": "delivery_unknown", "delivery_timeout": "delivery_unknown",
    "unknown_effect": "delivery_unknown",
    # regression
    "regression": "source_regression", "post_complete_break": "source_regression",
    # receipts / leases
    "receipt_expired": "stale_receipt", "expired": "stale_receipt",
    "lease_lost": "lease_or_fence_loss", "fence_lost": "lease_or_fence_loss",
    "stale_lease": "lease_or_fence_loss",
    # timeouts / capability / security
    "timeout": "agent_timeout", "worker_stuck": "agent_timeout", "stall": "agent_timeout",
    "missing_capability": "capability_missing", "unsupported": "capability_missing",
    "secret_detected": "security_block", "risk_gate_failed": "security_block",
    "unauthorized": "security_block",
}


def classify_failure(*, reason_code: str, detail: str = "") -> str:
    """Map a raw signal to one of `FAILURE_CLASSES`.

    Defaults to `code_failure` (the most conservative bucket, forcing a
    return-to-implementation-and-invalidate-reviews response) rather than
    ever silently returning an "unclassified" value.
    """
    code = str(reason_code or "").strip().lower()
    if code in FAILURE_CLASSES:
        return code
    return _ALIAS_MAP.get(code, "code_failure")


# --------------------------------------------------------------------------- #
# 2. Receipt invalidation graph (issue "Outputs: invalidated receipts";
#    plan step 4).
# --------------------------------------------------------------------------- #
# Every dimension of change and which downstream receipt *kinds* it makes
# stale. This is transitive: e.g. a code change invalidates review AND
# (because review feeds delivery) delivery.
INVALIDATION_EDGES: Dict[str, tuple] = {
    "code_change": ("review", "safety", "delivery"),
    "scope_change": ("planning", "review", "safety", "delivery"),
    "risk_action_change": ("safety", "review", "delivery"),
    "new_head": ("evidence", "review", "checks", "delivery"),
    "base_change": ("review", "checks", "delivery"),
}
# Direct downstream closure used to compute transitivity: delivery depends on
# review+safety+checks+evidence, review depends on evidence.
_DOWNSTREAM_OF: Dict[str, tuple] = {
    "evidence": ("review", "delivery"),
    "checks": ("review", "delivery"),
    "review": ("delivery",),
    "safety": ("review", "delivery"),
    "planning": ("review", "safety", "delivery"),
    "delivery": (),
}


def invalidation_closure(dimensions: Sequence[str]) -> List[str]:
    """Return the transitive closure of receipt kinds invalidated by the given
    changed dimensions (e.g. `["code_change", "new_head"]`). Deterministic,
    order-independent, deduped."""
    seed: set = set()
    for dim in dimensions or ():
        seed.update(INVALIDATION_EDGES.get(str(dim), ()))
    closure = set(seed)
    changed = True
    while changed:
        changed = False
        for kind in list(closure):
            for downstream in _DOWNSTREAM_OF.get(kind, ()):
                if downstream not in closure:
                    closure.add(downstream)
                    changed = True
    return sorted(closure)


def invalidate_receipts(receipts: Sequence[Mapping[str, Any]], *, dimensions: Sequence[str]) -> List[Dict[str, Any]]:
    """Given a set of prior receipts (each carrying a `kind` field: evidence,
    checks, review, safety, planning, delivery) and the changed dimensions,
    return the receipts that become stale, each annotated `invalidated: True`
    and `invalidated_reason`. Never mutates the input receipts."""
    stale_kinds = set(invalidation_closure(dimensions))
    out: List[Dict[str, Any]] = []
    for rec in receipts or ():
        kind = str(rec.get("kind") or "")
        if kind in stale_kinds:
            annotated = dict(rec)
            annotated["invalidated"] = True
            annotated["invalidated_reason"] = "stale after " + ",".join(sorted(dimensions))
            out.append(annotated)
    return out


# --------------------------------------------------------------------------- #
# 3. Routing decision reducer -- rules 1-10 from the issue, enforced
#    mechanically (plan step 5).
# --------------------------------------------------------------------------- #
# Baseline route per failure class. `dimensions` seeds the invalidation graph;
# `retryable` marks classes rule 6 allows a limited, code-untouched retry for;
# `requires_reconcile` marks rule 7 (uncertain external effect).
_CLASS_ROUTE: Dict[str, Dict[str, Any]] = {
    "code_failure":              {"target": "executing",  "dimensions": ("code_change",), "retryable": False, "requires_reconcile": False},
    "test_failure":               {"target": "executing",  "dimensions": ("code_change",), "retryable": False, "requires_reconcile": False},
    "ci_infra_failure":           {"target": "validating",  "dimensions": (),               "retryable": True,  "requires_reconcile": False},
    "review_change_requested":    {"target": "executing",  "dimensions": ("code_change",), "retryable": False, "requires_reconcile": False},
    "base_drift":                 {"target": "executing",  "dimensions": ("new_head", "base_change"), "retryable": True, "requires_reconcile": False},
    "merge_conflict":              {"target": "executing",  "dimensions": ("new_head", "base_change"), "retryable": True, "requires_reconcile": False},
    "delivery_unknown":            {"target": "delivering", "dimensions": (),               "retryable": True,  "requires_reconcile": True},
    "source_regression":           {"target": "planning",   "dimensions": ("scope_change",), "retryable": False, "requires_reconcile": False},
    "stale_receipt":                {"target": "validating", "dimensions": ("new_head",),    "retryable": True,  "requires_reconcile": False},
    "lease_or_fence_loss":          {"target": "executing",  "dimensions": (),               "retryable": True,  "requires_reconcile": False},
    "agent_timeout":                {"target": "executing",  "dimensions": (),               "retryable": True,  "requires_reconcile": False},
    "capability_missing":           {"target": "human",       "dimensions": (),               "retryable": False, "requires_reconcile": False},
    "security_block":               {"target": "safety_gate", "dimensions": ("risk_action_change",), "retryable": False, "requires_reconcile": False},
    "repeated_fingerprint_stall":    {"target": "human",       "dimensions": (),               "retryable": False, "requires_reconcile": False},
}


def route_decision(
    *,
    failure_class: str,
    scope_changed: bool = False,
    risk_action_changed: bool = False,
    new_head: bool = False,
    is_flaky_infra: bool = False,
    post_complete: bool = False,
) -> Dict[str, Any]:
    """Pure reducer: failure class + observed change dimensions -> routing
    decision. Enforces rules 1-10 mechanically:

    * rule 2 (code change -> implementation, invalidate reviews) and rule 3
      (scope change -> planner) and rule 4 (risk/action change -> safety)
      OVERRIDE the class's baseline target whenever the corresponding
      dimension is independently observed true, regardless of class.
    * rule 5: `new_head` always adds the `new_head` invalidation dimension.
    * rule 6: infra-flaky failures may retry without an implicit code-change
      dimension (never routes to executing purely because it's flaky).
    * rule 7: an `requires_reconcile` class blocks retry until reconciled.
    * rule 10: `post_complete=True` always reopens the stage graph (target
      forced to the class's stage, `reopen_stage_graph=True`), regardless of
      any COMPLETE terminality claimed upstream.
    """
    base = _CLASS_ROUTE.get(failure_class)
    if base is None:
        raise FeedbackRecoveryAgentError(
            f"unknown failure_class {failure_class!r}, must be one of {sorted(FAILURE_CLASSES)}",
            reason_code="capability_missing",
        )

    dimensions = set(base["dimensions"])
    target = base["target"]
    retryable = bool(base["retryable"]) and not (scope_changed or risk_action_changed)
    requires_reconcile = bool(base["requires_reconcile"])

    # Rule 4 takes priority: any risk/action change routes to safety.
    if risk_action_changed:
        target = "safety_gate"
        dimensions.add("risk_action_change")
        retryable = False
    # Rule 3: any scope change routes to the planner (overrides rule 4 only if
    # BOTH fire is not expected in practice; scope is checked after risk so a
    # simultaneous scope+risk change still lands on safety per rule 4, but is
    # additionally flagged so the planner is informed via invalidation).
    if scope_changed:
        dimensions.add("scope_change")
        if not risk_action_changed:
            target = "planning"
        retryable = False
    # Rule 2: any code change (independent of class) routes back to
    # implementation and invalidates reviews -- but never demotes an
    # already-stronger safety/planning route above.
    if "code_change" in base["dimensions"] and not scope_changed and not risk_action_changed:
        target = "executing"

    # Rule 5: a new head always invalidates dependent evidence/reviews/checks.
    if new_head:
        dimensions.add("new_head")

    # Rule 6: flaky infra retries without editing code -- it never gains a
    # code_change dimension purely from the flake flag.
    if is_flaky_infra and failure_class == "ci_infra_failure":
        retryable = True

    # Rule 10: a regression discovered after COMPLETE reopens the stage graph.
    reopen_stage_graph = bool(post_complete)
    if post_complete:
        target = base["target"] if failure_class == "source_regression" else target

    return {
        "target_stage": target,
        "invalidation_dimensions": sorted(dimensions),
        # NOTE: `retryable` here is the class-level baseline (e.g. delivery_unknown
        # is still "retryable" once reconciled) -- `requires_reconcile` is a
        # SEPARATE gate the caller must also satisfy before actually retrying
        # (rule 7). Folding reconcile into this flag would make a successful
        # reconciliation unable to ever unblock a retry.
        "retryable": bool(retryable),
        "requires_reconcile": requires_reconcile,
        "reopen_stage_graph": reopen_stage_graph,
    }


# --------------------------------------------------------------------------- #
# 4. Retry budget -- per (task_id, failure_class), plan step 7.
# --------------------------------------------------------------------------- #
def check_retry_budget(*, prior_attempts: int, budget: int) -> Dict[str, Any]:
    """Return whether a retry is authorized for one (task, class) pair.

    Exhausting the budget returns `retry_allowed=False` -- the caller must
    escalate rather than silently keep retrying (this NEVER relaxes a gate,
    only stops offering more attempts)."""
    budget = int(budget or 0)
    prior_attempts = int(prior_attempts or 0)
    allowed = prior_attempts < budget
    return {
        "retry_allowed": allowed,
        "attempt_number": prior_attempts + 1 if allowed else prior_attempts,
        "prior_attempts": prior_attempts,
        "retry_budget": budget,
    }


# --------------------------------------------------------------------------- #
# 5. Stall / repeated-fingerprint escalation (rule 8) -- reuses
#    `scripts/loop_journal.py`'s stall detector, plan step 6.
# --------------------------------------------------------------------------- #
def stall_verdict(journal_rows: Sequence[Mapping[str, Any]], *, k: Optional[int] = None) -> Dict[str, Any]:
    """Delegate to `scripts.loop_journal.analyze` for the stall/oscillation
    verdict. Fail-open (PROGRESS) if the journal module could not be
    imported, matching that module's own fail-open discipline for missing
    inputs (never fabricates a STALLED verdict)."""
    if _journal_analyze is None:
        return {"verdict": "PROGRESS", "stall_count": 0, "fingerprint": "",
                "recommend": "continue", "dead_ends": [], "reason": "loop_journal unavailable"}
    k = int(k) if k is not None else int(_JOURNAL_DEFAULT_K)
    return _journal_analyze(list(journal_rows or ()), k=k)


def repeated_fingerprint_escalates(journal_rows: Sequence[Mapping[str, Any]], *, k: Optional[int] = None) -> bool:
    """Rule 8: a fingerprint repeated K times changes strategy/escalates."""
    verdict = stall_verdict(journal_rows, k=k)
    return verdict.get("verdict") == "STALLED" and verdict.get("recommend") == "escalate"


# --------------------------------------------------------------------------- #
# 6. Quarantine / dead-letter (rule 9, plan step 8) -- a blocked item is set
#    aside WITHOUT stopping the drain of everything else.
# --------------------------------------------------------------------------- #
def quarantine_item(*, task_id: str, failure_class: str, fingerprint: str, reason: str) -> Dict[str, Any]:
    return {
        "schema": "simplicio.feedback-recovery-quarantine/v1",
        "task_id": str(task_id or ""),
        "failure_class": str(failure_class or ""),
        "fingerprint": str(fingerprint or ""),
        "reason": str(reason or ""),
        "quarantined_at": _now(),
        # explicit signal to the coordinator: draining other items MUST continue.
        "blocks_drain": False,
    }


# --------------------------------------------------------------------------- #
# 7. External-effect reconciliation (rule 7, plan step 9) -- an uncertain
#    external effect (e.g. `delivery_unknown`) must be reconciled BEFORE any
#    retry is authorized.
# --------------------------------------------------------------------------- #
def reconcile_external_effect(*, observed_state: Optional[Mapping[str, Any]], expected_intent: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare an observed external state (e.g. "was the PR actually merged?")
    against the delivery intent that was in flight when the effect became
    uncertain. Returns a reconciliation verdict a caller must honor: no
    retry is authorized until `reconciled=True`.

    `observed_state=None` means the effect could not be observed at all
    (still ambiguous) -- this NEVER defaults to "assume it worked" or
    "assume it failed"; it stays unreconciled until real observation exists.
    """
    if observed_state is None:
        return {
            "schema": "simplicio.feedback-recovery-reconciliation/v1",
            "reconciled": False,
            "outcome": "unknown",
            "detail": "no observation available yet; retry remains blocked",
        }
    intent_id = str(expected_intent.get("intent_id") or "")
    observed_id = str(observed_state.get("intent_id") or "")
    if intent_id and observed_id and intent_id != observed_id:
        return {
            "schema": "simplicio.feedback-recovery-reconciliation/v1",
            "reconciled": False,
            "outcome": "mismatch",
            "detail": f"observed intent {observed_id!r} != expected {intent_id!r}",
        }
    succeeded = bool(observed_state.get("succeeded"))
    return {
        "schema": "simplicio.feedback-recovery-reconciliation/v1",
        "reconciled": True,
        "outcome": "succeeded" if succeeded else "failed",
        "detail": "external effect observed and matched the expected intent",
    }


# --------------------------------------------------------------------------- #
# 8. Boundary: this role never writes review/safety/delivery/completion
#    receipts (structural independence, stages.json `forbidden_to_self_sign`).
# --------------------------------------------------------------------------- #
def assert_receipt_schema_allowed(schema: str) -> None:
    if str(schema) in FORBIDDEN_RECEIPT_SCHEMAS:
        raise ForbiddenReceiptError(
            f"feedback_recovery_agent may never write a {schema!r} receipt "
            "(review/safety/delivery/completion are independent roles)"
        )


def assert_route_target_valid(target: str) -> None:
    if target not in ROUTE_TARGETS:
        raise FeedbackRecoveryAgentError(
            f"routing target {target!r} is not a recognized stage/handoff "
            f"(must be one of {sorted(ROUTE_TARGETS)})",
            reason_code="capability_missing",
        )


# --------------------------------------------------------------------------- #
# 9. The composed #430 receipt -- the real decision-building entrypoint every
#    invariant above must actually be wired into (not merely unit-tested in
#    isolation -- AGENTS.md's named bug class).
# --------------------------------------------------------------------------- #
def build_feedback_recovery_receipt(
    *,
    run_id: str,
    task_id: str,
    attempt: int,
    reason_code: str,
    failure_detail: str = "",
    scope_changed: bool = False,
    risk_action_changed: bool = False,
    new_head: bool = False,
    is_flaky_infra: bool = False,
    post_complete: bool = False,
    prior_attempts: int = 0,
    retry_budget: int = 3,
    journal_rows: Sequence[Mapping[str, Any]] = (),
    prior_receipts: Sequence[Mapping[str, Any]] = (),
    external_observed_state: Optional[Mapping[str, Any]] = None,
    delivery_intent: Optional[Mapping[str, Any]] = None,
    stall_k: Optional[int] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the typed `simplicio.feedback-recovery-receipt/v1`.

    Every invariant this module defines is invoked here, on the real
    decision path:

    * `classify_failure` -- taxonomy + fingerprint.
    * `route_decision` -- rules 1-5 (root-cause routing, code/scope/risk
      overrides, new-head invalidation) and rule 10 (post-complete reopen).
    * `invalidation_closure` / `invalidate_receipts` -- transitive receipt
      invalidation (rule 5, plan step 4).
    * `stall_verdict` / `repeated_fingerprint_escalates` -- rule 8, reusing
      `scripts/loop_journal.py`'s own stall detector, never reinvented.
    * `check_retry_budget` -- rule 6/plan step 7, retry budget per class.
    * `reconcile_external_effect` -- rule 7, blocks retry on an uncertain
      external effect until reconciled.
    * `quarantine_item` -- rule 9, a blocked item never stops the drain.
    * `assert_receipt_schema_allowed` -- this role's forbidden-schema
      invariant, checked against its OWN schema constant (guards against the
      constant itself ever colliding with a forbidden one).
    """
    assert_receipt_schema_allowed(FEEDBACK_RECOVERY_RECEIPT_SCHEMA)

    failure_class = classify_failure(reason_code=reason_code, detail=failure_detail)
    fp = signal_fingerprint(failure_detail or reason_code)

    decision = route_decision(
        failure_class=failure_class,
        scope_changed=scope_changed,
        risk_action_changed=risk_action_changed,
        new_head=new_head,
        is_flaky_infra=is_flaky_infra,
        post_complete=post_complete,
    )
    assert_route_target_valid(decision["target_stage"])

    invalidated = invalidate_receipts(prior_receipts, dimensions=decision["invalidation_dimensions"])

    stall = stall_verdict(journal_rows, k=stall_k)
    escalate_for_stall = repeated_fingerprint_escalates(journal_rows, k=stall_k) or failure_class == "repeated_fingerprint_stall"

    budget_check = check_retry_budget(prior_attempts=prior_attempts, budget=retry_budget)

    reconciliation: Optional[Dict[str, Any]] = None
    retry_blocked_by_reconcile = False
    if decision["requires_reconcile"]:
        reconciliation = reconcile_external_effect(
            observed_state=external_observed_state,
            expected_intent=delivery_intent or {},
        )
        retry_blocked_by_reconcile = not reconciliation["reconciled"]

    retry_allowed = (
        decision["retryable"]
        and budget_check["retry_allowed"]
        and not retry_blocked_by_reconcile
        and not escalate_for_stall
    )

    quarantine: Optional[Dict[str, Any]] = None
    verdict: str
    if escalate_for_stall:
        verdict = VERDICT_ESCALATED
    elif retry_blocked_by_reconcile:
        verdict = VERDICT_RECONCILE_PENDING
    elif decision["retryable"] and not budget_check["retry_allowed"] and prior_attempts > 0:
        # Budget exhausted on a class that would otherwise keep retrying
        # (e.g. repeated infra flake) -- quarantine rather than loop
        # forever, without stopping the drain of other work (rule 9).
        quarantine = quarantine_item(task_id=task_id, failure_class=failure_class, fingerprint=fp,
                                      reason="retry budget exhausted")
        verdict = VERDICT_QUARANTINED
    else:
        verdict = VERDICT_ROUTED

    receipt: Dict[str, Any] = {
        "schema": FEEDBACK_RECOVERY_RECEIPT_SCHEMA,
        "role_id": FEEDBACK_RECOVERY_ROLE_ID,
        "run_id": str(run_id or ""),
        "task_id": str(task_id or ""),
        "attempt": int(attempt or 0),
        "verdict": verdict,
        "failure_class": failure_class,
        "fingerprint": fp,
        "reason_code": str(reason_code or ""),
        "target_stage": decision["target_stage"],
        "invalidation_dimensions": decision["invalidation_dimensions"],
        "invalidated_receipts": invalidated,
        "reopen_stage_graph": decision["reopen_stage_graph"],
        "retry": budget_check,
        "retry_allowed": retry_allowed,
        "requires_reconcile": decision["requires_reconcile"],
        "reconciliation": reconciliation,
        "stall": stall,
        "quarantine": quarantine,
        # invariant: this role never declares completion/terminality -- the
        # coordinator applies the transition, only ever after seeing this
        # typed receipt (plan step 12/13).
        "next_action": "quarantine" if verdict == VERDICT_QUARANTINED
                        else ("escalate_to_human" if verdict == VERDICT_ESCALATED
                              else ("await_reconciliation" if verdict == VERDICT_RECONCILE_PENDING
                                    else "transition_to_" + decision["target_stage"])),
        "complete": False,
        "created_at": _now(),
    }
    receipt["receipt_hash"] = content_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return receipt


def receipt_is_routed(receipt: Mapping[str, Any]) -> bool:
    return receipt.get("verdict") == VERDICT_ROUTED


# --------------------------------------------------------------------------- #
# Stage-agent binding -- projects the #430 receipt into a portable
# StageReceipt (`simplicio_loop/stage_agents.py::validate_receipt`). This role
# has no single owned `stage_id` in the graph (it re-enters any prior stage),
# so the projection carries the TARGET stage it is requesting, not a stage it
# occupies -- the coordinator is the one that actually claims that stage.
# --------------------------------------------------------------------------- #
def to_stage_receipt(
    feedback_recovery_receipt: Mapping[str, Any],
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
    """``context_hash``/``manifest_hash`` default to an all-zero placeholder when
    the caller doesn't have the coordinator's real values on hand -- a real
    coordinator-driven caller MUST pass the actual `AgentInstance` values, or
    `stage_agents.validate_receipt()` will (correctly) reject the mismatch.
    """
    verdict_map = {
        VERDICT_ROUTED: "pass",
        VERDICT_QUARANTINED: "blocked",
        VERDICT_ESCALATED: "blocked",
        VERDICT_RECONCILE_PENDING: "blocked",
    }
    verdict = verdict_map.get(feedback_recovery_receipt.get("verdict"), "blocked")
    accepted = verdict == "pass"
    ts = _now()
    receipt: Dict[str, Any] = {
        "schema": "simplicio.stage-receipt/v1",
        "receipt_id": str(receipt_id),
        "agent_instance_id": str(agent_instance_id),
        "role_id": FEEDBACK_RECOVERY_ROLE_ID,
        "stage_id": feedback_recovery_receipt.get("target_stage") or "executing",
        "run_id": str(feedback_recovery_receipt.get("run_id") or ""),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "attempt_ordinal": int(attempt_ordinal),
        "fence": str(fence),
        "plan_revision": 0,
        "created_at": ts,
        "observed_at": ts,
        "ttl_seconds": 3600,
        "context_hash": str(context_hash),
        "manifest_hash": str(manifest_hash),
        "verdict": verdict,
        "evidence_refs": [str(feedback_recovery_receipt.get("fingerprint") or "n/a")],
        "accepted": accepted,
        "reason_code": str(feedback_recovery_receipt.get("failure_class") or "ok"),
        "input_hash": content_hash(feedback_recovery_receipt.get("fingerprint") or ""),
        "output_hash": str(feedback_recovery_receipt.get("receipt_hash") or content_hash(None)),
        "previous_receipt_hashes": [],
        "covered_acceptance_criteria": ["n/a"],
        "commands": ["n/a"],
        "exit_codes": {},
        "artifact_refs": [],
        "next_stage_recommendation": str(feedback_recovery_receipt.get("target_stage") or "unknown"),
    }
    if not accepted:
        receipt["rejection_reason"] = str(feedback_recovery_receipt.get("failure_class") or "not_accepted")
    payload = dict(receipt)
    receipt["integrity_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return receipt


__all__ = [
    "FEEDBACK_RECOVERY_RECEIPT_SCHEMA",
    "FEEDBACK_RECOVERY_ROLE_ID",
    "VERDICT_ROUTED",
    "VERDICT_QUARANTINED",
    "VERDICT_ESCALATED",
    "VERDICT_RECONCILE_PENDING",
    "FAILURE_CLASSES",
    "FORBIDDEN_RECEIPT_SCHEMAS",
    "STAGE_TARGETS",
    "ROUTE_TARGETS",
    "FeedbackRecoveryAgentError",
    "ForbiddenReceiptError",
    "content_hash",
    "signal_fingerprint",
    "classify_failure",
    "invalidation_closure",
    "invalidate_receipts",
    "route_decision",
    "check_retry_budget",
    "stall_verdict",
    "repeated_fingerprint_escalates",
    "quarantine_item",
    "reconcile_external_effect",
    "assert_receipt_schema_allowed",
    "assert_route_target_valid",
    "build_feedback_recovery_receipt",
    "receipt_is_routed",
    "to_stage_receipt",
]
