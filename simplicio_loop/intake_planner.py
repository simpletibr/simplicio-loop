"""Concrete `intake_planner` stage-agent role (#425, EPIC #422 "Portable Stage Agents").

Issue #425 asks for a materialized role that turns a real work item (issue /
board card) into an executable contract + plan *before any mutation*: read the
full source, freeze its revision, orient in the repo, make risks/dependencies
explicit, and produce bidirectional coverage between acceptance criteria,
steps, files, commands and evidence.

This module does not reinvent any of that machinery -- #284 already built it:

  * ``source_snapshot.py``       -- full-pagination GitHub issue capture + revision hash.
  * ``intake_contract.py``       -- the frozen ``simplicio.task-intake/v1`` envelope.
  * ``traceability_matrix.py``   -- the AC<->step<->test<->evidence matrix.
  * ``planning_gate.py``         -- plan/contract/lease-bound mutation authority.
  * ``stage_agents.py``          -- the portable AgentInstance/StageReceipt contract,
    where the manifesto (``contracts/stage-agents/v1/stages.json``) already
    registers the ``intake_planner`` role and its ``intake`` stage.

What #425 actually adds, and what this module implements:

  1. A typed ``simplicio.intake-planner-receipt/v1`` that composes all of the
     above into ONE verdict (``PASSED``/``BLOCKED``) gated on the exact
     checklist from the issue: source read + revision frozen, every AC has a
     step + proof, every step maps to an AC, blocked dependencies explicit, no
     impact gap above threshold, conventions consulted, delivery target
     defined, risks mitigated-or-blocked, and no mutation before
     ``mutation-capability``.
  2. Boundary enforcement (``assert_boundary_ok``): this role may only ever
     write receipts/plan/anchor/intake-status artifacts -- never product code,
     never a commit/PR. A path outside the allowlist raises
     ``IntakePlannerBoundaryError`` fail-closed.
  3. A single clarifying question path (``needs_clarification`` /
     ``clarification_question``): a material ambiguity yields
     ``BLOCKED(needs_clarification)`` instead of a silently-invented
     assumption -- never a second question, never a guess.
  4. A risk register gate (``build_risk_register``): every risk must carry a
     mitigation OR be marked a blocker; a risk with neither fails the gate.
  5. A dependency DAG projection (``build_dependency_dag``) that makes any
     blocked dependency explicit rather than merely implied by the plan.

This module is data-only and model-free, the same discipline as
``planning_gate.py``/``intake_contract.py``: it assembles and gates artifacts
that already exist; it never invents an acceptance criterion, never relaxes
one, and never marks delivery as done (that is `delivery_agent`'s job, a
distinct role in the manifesto with a disjoint ``independent_of_roles`` set).
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

INTAKE_PLANNER_RECEIPT_SCHEMA = "simplicio.intake-planner-receipt/v1"
INTAKE_PLANNER_ROLE_ID = "intake_planner"

# Verdicts for the #425 typed receipt (deliberately distinct from, and layered
# on top of, planning_gate.py's COMPLETE/BLOCKED/STALE_SOURCE/... verdicts --
# this receipt gates the INTAKE role's own boundary + checklist, not just
# mutation authority).
VERDICT_PASSED = "PASSED"
VERDICT_BLOCKED = "BLOCKED"

# Default impact-gap severities that block the plan outright (issue: "impact
# audit não possui gap acima do threshold"). A caller may override via
# `impact_gap_threshold`.
DEFAULT_BLOCKING_IMPACT_SEVERITIES = frozenset(("high",))

# Path prefixes this role is allowed to create/update. Anything else is
# product code, a commit, or a PR -- strictly out of boundary for this role
# (see issue #425 "Não pode": "alterar código do produto", "criar commit/PR/merge").
ALLOWED_MUTATION_PATH_PREFIXES: tuple[str, ...] = (
    ".simplicio/orchestrator/",
    ".simplicio/",
    "task-intake.json",
    "planning-receipt.json",
    "ac-matrix.json",
    "impact-map.json",
    "flow-audit.json",
    "intake-planner-receipt.json",
)


class IntakePlannerBoundaryError(ValueError):
    """Raised when the intake_planner role is asked to touch something outside its boundary."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Boundary enforcement -- "Não pode alterar código do produto / criar commit/PR/merge"
# --------------------------------------------------------------------------- #
def is_path_in_boundary(path: str, *, allowed_prefixes: Sequence[str] = ALLOWED_MUTATION_PATH_PREFIXES) -> bool:
    """True when `path` is an artifact this role is allowed to write (never product code)."""
    norm = str(path or "").replace("\\", "/").lstrip("./")
    for prefix in allowed_prefixes:
        p = prefix.replace("\\", "/").lstrip("./")
        if norm == p or norm.startswith(p):
            return True
    return False


def assert_boundary_ok(
    touched_paths: Sequence[str],
    *,
    allowed_prefixes: Sequence[str] = ALLOWED_MUTATION_PATH_PREFIXES,
) -> None:
    """Fail-closed: raise `IntakePlannerBoundaryError` if any touched path is out of boundary.

    Also rejects the sentinel actions `commit`/`pr`/`merge` when passed as a
    "path" -- a caller wiring this role to an operator/git layer should pass
    those verbs through here before invoking anything so an accidental
    commit/PR/merge attempt is refused the same way an out-of-tree file write
    would be.
    """
    forbidden_verbs = {"commit", "pr", "push", "merge"}
    violations: List[str] = []
    for raw in touched_paths or ():
        candidate = str(raw or "")
        if candidate.strip().lower() in forbidden_verbs:
            violations.append(f"forbidden action: {candidate}")
            continue
        if not is_path_in_boundary(candidate, allowed_prefixes=allowed_prefixes):
            violations.append(f"out-of-boundary path: {candidate}")
    if violations:
        raise IntakePlannerBoundaryError(
            "intake_planner boundary violation(s): " + "; ".join(violations)
        )


# --------------------------------------------------------------------------- #
# Risk register -- "riscos têm mitigação ou blocker"
# --------------------------------------------------------------------------- #
def build_risk_register(
    risks: Optional[Sequence[Mapping[str, Any]]],
    *,
    no_risks_identified: bool = False,
) -> Dict[str, Any]:
    """Normalize a risk register and gate it: every risk needs `mitigation` OR `is_blocker`.

    An EMPTY risk list is NOT vacuously OK: an intake_planner run that never
    actually assessed risk (the common bug -- silently passing because
    `risks` was never supplied) must not pass this gate. The caller must
    explicitly assert `no_risks_identified=True` to record "risk assessment
    was performed and found nothing" as a distinct, auditable fact from
    "risk assessment never happened". A non-empty `risks` list is itself
    that assertion and does not also need the flag.

    Returns `{"risks": [...], "errors": [...], "ok": bool}` -- never raises,
    same discipline as `intake_contract.lint_task_intake`.
    """
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    risk_list = list(risks or ())
    if not risk_list and not no_risks_identified:
        errors.append("risk_assessment_missing")
    for idx, risk in enumerate(risk_list):
        rid = str((risk or {}).get("id") or f"R{idx + 1}")
        text = str((risk or {}).get("text") or "").strip()
        mitigation = str((risk or {}).get("mitigation") or "").strip()
        is_blocker = bool((risk or {}).get("is_blocker"))
        severity = str((risk or {}).get("severity") or "medium")
        if not text:
            errors.append(f"risk_missing_text:{rid}")
        if not mitigation and not is_blocker:
            errors.append(f"risk_missing_mitigation_or_blocker:{rid}")
        rows.append({
            "id": rid,
            "text": text,
            "severity": severity,
            "mitigation": mitigation,
            "is_blocker": is_blocker,
        })
    return {
        "risks": rows,
        "errors": errors,
        "ok": not errors,
        "no_risks_identified": bool(no_risks_identified and not risk_list),
    }


# --------------------------------------------------------------------------- #
# Dependency DAG -- "dependências bloqueadas estão explícitas"
# --------------------------------------------------------------------------- #
def build_dependency_dag(dependencies: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    """Project a flat dependency list into a DAG artifact with blocked deps explicit.

    Each dependency row: `{"id": ..., "depends_on": [...], "state": "open"|"resolved"|"blocked", ...}`.
    `blocked_ids` lists every dependency explicitly marked `state == "blocked"`
    (or whose `depends_on` references an unresolved id) -- issue #425 requires
    these to be *explicit*, not that none exist.
    """
    nodes = {str((d or {}).get("id") or ""): dict(d or {}) for d in (dependencies or ())}
    resolved = {nid for nid, d in nodes.items() if d.get("state") == "resolved"}
    blocked_ids: List[str] = []
    for nid, d in nodes.items():
        if not nid:
            continue
        state = str(d.get("state") or "open")
        deps_on = list(d.get("depends_on") or [])
        unresolved = [dep for dep in deps_on if dep not in resolved]
        if state == "blocked" or unresolved:
            blocked_ids.append(nid)
    dag = {
        "nodes": [dict(v, id=k) for k, v in nodes.items() if k],
        "blocked_ids": sorted(set(blocked_ids)),
        "has_blocked": bool(blocked_ids),
    }
    dag["dag_hash"] = content_hash(dag)
    return dag


# --------------------------------------------------------------------------- #
# Impact-gap threshold -- "impact audit não possui gap acima do threshold"
# --------------------------------------------------------------------------- #
def impact_gap_severities(impact_map: Optional[Mapping[str, Any]]) -> List[str]:
    """Extract the severities of any gap-shaped issues from an impact_audit.py `audit()` result."""
    if not impact_map:
        return []
    severities: List[str] = []
    for issue in impact_map.get("issues") or impact_map.get("gaps") or ():
        if isinstance(issue, Mapping):
            severities.append(str(issue.get("severity") or "medium"))
        else:
            severities.append("medium")
    return severities


def impact_gap_ok(
    impact_map: Optional[Mapping[str, Any]],
    *,
    blocking_severities: Sequence[str] = DEFAULT_BLOCKING_IMPACT_SEVERITIES,
) -> bool:
    if impact_map is None:
        return True  # no impact audit supplied -- caller didn't opt in, unaffected
    blocking = set(blocking_severities)
    return not any(sev in blocking for sev in impact_gap_severities(impact_map))


# --------------------------------------------------------------------------- #
# The composed #425 receipt
# --------------------------------------------------------------------------- #
def build_intake_planner_receipt(
    *,
    run_id: str,
    attempt: int,
    contract: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_validation: Mapping[str, Any],
    intake: Mapping[str, Any],
    traceability_matrix: Mapping[str, Any],
    source_snapshot: Optional[Mapping[str, Any]] = None,
    impact_map: Optional[Mapping[str, Any]] = None,
    flow_audit_result: Optional[Mapping[str, Any]] = None,
    risks: Optional[Sequence[Mapping[str, Any]]] = None,
    no_risks_identified: bool = False,
    dependencies: Optional[Sequence[Mapping[str, Any]]] = None,
    conventions_consulted: bool = False,
    precedents_consulted: bool = False,
    touched_paths: Optional[Sequence[str]] = None,
    needs_clarification: bool = False,
    clarification_question: str = "",
    lease_id: str = "",
    fencing_token: str = "",
    plan_revision: int = 0,
    source_revision: str = "",
    impact_gap_threshold: Sequence[str] = DEFAULT_BLOCKING_IMPACT_SEVERITIES,
) -> Dict[str, Any]:
    """Build the typed `simplicio.intake-planner-receipt/v1` for the #425 intake_planner role.

    Delegates the mutation-authority machinery to `planning_gate.build_planning_receipt()`
    (unchanged) and layers the #425-specific checklist on top: boundary
    enforcement, risk-register gate, dependency DAG explicitness, impact-gap
    threshold, and the single-clarifying-question path. Never mutates
    anything; this is a pure data assembly + gate, exactly like its siblings.

    `touched_paths` MUST be supplied (an explicit list, possibly empty when
    nothing was touched) for the boundary check to actually run: omitting it
    is treated as "the boundary was never checked" and fails the
    `no_mutation_before_mutation_capability` gate closed, rather than silently
    passing. `risks`/`no_risks_identified` follow the same discipline (see
    `build_risk_register`): an omitted/empty risk list without the explicit
    `no_risks_identified=True` assertion fails `risks_mitigated_or_blocked`.
    """
    from . import planning_gate as _pg

    # Boundary: this role may only ever touch its own allowlisted artifacts.
    # Fail-closed -- raises rather than silently downgrading to BLOCKED, since
    # an out-of-boundary write is a contract violation, not an ordinary gap.
    # A caller that omits `touched_paths` entirely gets `boundary_checked=False`
    # below (the gate then blocks) instead of a check that silently never ran.
    boundary_checked = touched_paths is not None
    if boundary_checked:
        assert_boundary_ok(touched_paths)

    risk_register = build_risk_register(risks, no_risks_identified=no_risks_identified)
    dependency_dag = build_dependency_dag(dependencies)
    intake_lint = _intake_lint(intake)
    matrix_ok = bool(traceability_matrix.get("coverage_ok"))
    impact_ok = impact_gap_ok(impact_map, blocking_severities=impact_gap_threshold)
    delivery_target = str((intake.get("understanding") or {}).get("delivery_target") or "")
    delivery_target_ok = bool(delivery_target)
    source_ok = bool(source_snapshot) and bool(
        ((source_snapshot or {}).get("source") or {}).get("snapshot_hash")
    )

    planning_receipt = _pg.build_planning_receipt(
        run_id=run_id, attempt=attempt, contract=contract, plan=plan,
        plan_validation=plan_validation, lease_id=lease_id, fencing_token=fencing_token,
        source_snapshot=source_snapshot, intake=intake, impact_map=impact_map,
        traceability_matrix=traceability_matrix, plan_revision=plan_revision,
        source_revision=source_revision,
        awaiting_decision=needs_clarification, awaiting_reason=clarification_question,
    )

    checklist = {
        "source_read_and_revision_frozen": source_ok,
        "every_ac_has_step_and_proof": matrix_ok,
        "every_step_maps_to_ac": matrix_ok,
        # explicit dependency DAG must show no *unresolved* blocked dependency
        # left implicit -- a real blocked dependency fails this gate for real,
        # it is not automatically "explicit enough" just by existing.
        "blocked_dependencies_explicit": not dependency_dag["has_blocked"],
        "impact_audit_below_threshold": impact_ok,
        "architecture_conventions_consulted": bool(conventions_consulted),
        "delivery_target_defined": delivery_target_ok,
        "risks_mitigated_or_blocked": bool(risk_register["ok"]),
        # only True when the boundary check actually ran (touched_paths was
        # supplied) AND it passed (assert_boundary_ok above did not raise).
        "no_mutation_before_mutation_capability": boundary_checked,
        "intake_lint_ok": bool(intake_lint["valid"]),
        "no_clarification_pending": not needs_clarification,
    }
    failing = [k for k, v in checklist.items() if not v]
    verdict = VERDICT_PASSED if not failing else VERDICT_BLOCKED

    receipt: Dict[str, Any] = {
        "schema": INTAKE_PLANNER_RECEIPT_SCHEMA,
        "role_id": INTAKE_PLANNER_ROLE_ID,
        "run_id": str(run_id or ""),
        "attempt": int(attempt or 0),
        "plan_revision": int(plan_revision or 0),
        "verdict": verdict,
        "checklist": checklist,
        "failing_checks": failing,
        "needs_clarification": bool(needs_clarification),
        "clarification_question": str(clarification_question or ""),
        "boundary_checked": boundary_checked,
        "touched_paths": list(touched_paths) if touched_paths is not None else None,
        "risk_register": risk_register,
        "dependency_dag": dependency_dag,
        "delivery_target": delivery_target,
        "conventions_consulted": bool(conventions_consulted),
        "precedents_consulted": bool(precedents_consulted),
        "intake_lint": intake_lint,
        "planning_receipt": planning_receipt,
    }
    if impact_map:
        receipt["impact_map_hash"] = content_hash(impact_map)
        receipt["impact_gap_severities"] = impact_gap_severities(impact_map)
    if flow_audit_result:
        receipt["flow_audit_hash"] = content_hash(flow_audit_result)
    receipt["receipt_hash"] = content_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return receipt


def _intake_lint(intake: Mapping[str, Any]) -> Dict[str, Any]:
    from . import intake_contract as _ic
    return _ic.lint_task_intake(intake)


def receipt_is_passed(receipt: Mapping[str, Any]) -> bool:
    return receipt.get("verdict") == VERDICT_PASSED


# --------------------------------------------------------------------------- #
# Stage-agent binding -- projects the #425 receipt into a portable StageReceipt
# (contracts/stage-agents/v1/stages.json already registers this role/stage).
# --------------------------------------------------------------------------- #
def to_stage_receipt(
    intake_planner_receipt: Mapping[str, Any],
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
    """Project the #425 receipt into a `simplicio.stage-receipt/v1`-shaped dict
    (see `simplicio_loop/stage_agents.py::validate_receipt`) for the `intake`
    stage owned by the `intake_planner` role.

    ``context_hash``/``manifest_hash`` default to an all-zero placeholder when
    the caller doesn't have the coordinator's real values on hand -- a real
    coordinator-driven caller MUST pass the actual `AgentInstance` values, or
    `stage_agents.validate_receipt()` will (correctly) reject the mismatch.
    """
    verdict = "pass" if receipt_is_passed(intake_planner_receipt) else "blocked"
    accepted = verdict == "pass"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    receipt: Dict[str, Any] = {
        "schema": "simplicio.stage-receipt/v1",
        "receipt_id": str(receipt_id),
        "agent_instance_id": str(agent_instance_id),
        "role_id": INTAKE_PLANNER_ROLE_ID,
        "stage_id": "intake",
        "run_id": str(intake_planner_receipt.get("run_id") or ""),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "attempt_ordinal": int(attempt_ordinal),
        "fence": str(fence),
        "plan_revision": int(intake_planner_receipt.get("plan_revision") or 0),
        "created_at": ts,
        "observed_at": ts,
        "ttl_seconds": 3600,
        "context_hash": str(context_hash),
        "manifest_hash": str(manifest_hash),
        "verdict": verdict,
        "evidence_refs": ["n/a"],
        "accepted": accepted,
        "reason_code": "ok" if accepted else "intake_planner_gate_not_passed",
        "input_hash": content_hash(intake_planner_receipt.get("source_revision") or ""),
        "output_hash": str(intake_planner_receipt.get("receipt_hash") or content_hash(None)),
        "previous_receipt_hashes": [],
        "covered_acceptance_criteria": ["n/a"],
        "commands": ["n/a"],
        "exit_codes": {},
        "artifact_refs": [],
        "next_stage_recommendation": "planning" if accepted else "unknown",
    }
    if not accepted:
        receipt["rejection_reason"] = "intake_planner_gate_not_passed"
    payload = dict(receipt)
    receipt["integrity_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return receipt


__all__ = [
    "INTAKE_PLANNER_RECEIPT_SCHEMA",
    "INTAKE_PLANNER_ROLE_ID",
    "VERDICT_PASSED",
    "VERDICT_BLOCKED",
    "DEFAULT_BLOCKING_IMPACT_SEVERITIES",
    "ALLOWED_MUTATION_PATH_PREFIXES",
    "IntakePlannerBoundaryError",
    "content_hash",
    "is_path_in_boundary",
    "assert_boundary_ok",
    "build_risk_register",
    "build_dependency_dag",
    "impact_gap_severities",
    "impact_gap_ok",
    "build_intake_planner_receipt",
    "receipt_is_passed",
    "to_stage_receipt",
]
