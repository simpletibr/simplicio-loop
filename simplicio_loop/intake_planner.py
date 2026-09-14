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
from simplicio_loop.mapper_receipt import normalize_mapper_index_receipt
from simplicio_loop.fast_integration import FAST_INGEST_SCHEMA, FAST_PLAN_SCHEMA

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
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


SINGLE_TASK_FAST_SCHEMA = "simplicio.single-task-fast-receipt/v1"
SINGLE_TASK_FAST_ROUTE = "single-task-fast"
FULL_PIPELINE_ROUTE = "full-pipeline"
ORDERED_TWO_TASK_ROUTE = "single-task-fast-ordered-provider"
_SINGLE_TASK_REQUIRED_TOOLS = ("mapper", "fast", "dev_cli")
_ESCALATION_ORDER = ("target_expansion", "sensitive_surface", "new_files", "diff_overshoot", "verification_failure", "source_drift")
_PROVIDER_SECRET_ENV = ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def freeze_single_task_contract(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Freeze the complete bounded-task contract before any mapping call."""
    required = ("goal", "acceptance_criteria", "target_hints", "verification_commands", "budgets", "issue", "source_revision")
    if any(key not in task for key in required):
        raise ValueError("single-task-fast requires goal, ACs, target hints, verification commands, and budgets")
    if not isinstance(task["acceptance_criteria"], list) or not task["acceptance_criteria"]:
        raise ValueError("acceptance criteria must be a non-empty list")
    if any(not isinstance(value, str) or not value.strip() for value in task["acceptance_criteria"]):
        raise ValueError("acceptance criteria must contain non-empty strings")
    if not isinstance(task["target_hints"], list) or not task["target_hints"]:
        raise ValueError("target hints must be a non-empty list")
    if any(not isinstance(value, str) or not value.strip() for value in task["target_hints"]):
        raise ValueError("target hints must contain non-empty strings")
    if not isinstance(task["goal"], str) or not task["goal"].strip():
        raise ValueError("goal must be a non-empty string")
    if not isinstance(task["issue"], str) or not task["issue"].strip() or not isinstance(task["source_revision"], str) or not task["source_revision"].strip():
        raise ValueError("issue and source_revision must be non-empty strings")
    commands = task["verification_commands"]
    if (
        not isinstance(commands, list)
        or not commands
        or any(
            not isinstance(command, (list, tuple))
            or not command
            or any(not isinstance(part, str) or not part.strip() for part in command)
            for command in commands
        )
    ):
        raise ValueError("verification commands must be non-empty argv arrays")
    budgets = dict(task["budgets"])
    for key in ("max_context_bytes", "max_context_tokens", "max_diff_lines", "max_iterations"):
        if not isinstance(budgets.get(key), int) or budgets[key] <= 0:
            raise ValueError(f"budgets.{key} must be a positive integer")
    delivery = task.get("delivery_contract")
    stop = task.get("stop")
    recovery = task.get("recovery")
    if not isinstance(delivery, Mapping) or not delivery or not all(
            isinstance(delivery.get(key), bool) for key in ("watcher", "dod")):
        raise ValueError("delivery_contract requires boolean watcher and dod gates")
    if not isinstance(stop, Mapping) or not isinstance(stop.get("preserve"), bool):
        raise ValueError("stop requires boolean preserve")
    if not isinstance(recovery, Mapping) or not isinstance(recovery.get("preserve"), bool):
        raise ValueError("recovery requires boolean preserve")
    contract = {
        "goal": task["goal"].strip(), "issue": task["issue"].strip(),
        "source_revision": task["source_revision"].strip(),
        "acceptance_criteria": list(task["acceptance_criteria"]),
        "delivery_contract": dict(delivery),
        "target_hints": list(task["target_hints"]),
        "verification_commands": [list(command) for command in commands],
        "budgets": budgets,
        "stop": dict(stop),
        "recovery": dict(recovery),
    }
    frozen = json.loads(json.dumps(contract, sort_keys=True))
    frozen["contract_hash"] = content_hash(frozen)
    return frozen


def select_single_task_route(tasks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if len(tasks) != 1:
        return {"route": FULL_PIPELINE_ROUTE, "reason_code": "task_count_not_one"}
    task = tasks[0]
    triggers = []
    if not task.get("bounded", True):
        triggers.append("target_expansion")
    if task.get("sensitive_surface") or task.get("hub_surface"):
        triggers.append("sensitive_surface")
    if task.get("new_files"):
        triggers.append("new_files")
    if triggers:
        return {"route": FULL_PIPELINE_ROUTE, "reason_code": triggers[0], "triggers": triggers}
    return {"route": SINGLE_TASK_FAST_ROUTE, "reason_code": "one_bounded_task", "triggers": []}


def _measured_escalations(contract, mutation, verification, source_drift):
    reasons = set()
    if mutation.get("target_expanded"):
        reasons.add("target_expansion")
    if mutation.get("sensitive_surface"):
        reasons.add("sensitive_surface")
    if mutation.get("new_files"):
        reasons.add("new_files")
    if int(mutation.get("diff_lines", 0)) > contract["budgets"]["max_diff_lines"]:
        reasons.add("diff_overshoot")
    if not verification.get("focused_ok", False):
        reasons.add("verification_failure")
    if source_drift:
        reasons.add("source_drift")
    return [reason for reason in _ESCALATION_ORDER if reason in reasons]


def _call(operations, name, *args):
    operation = operations.get(name)
    if not callable(operation):
        raise ValueError(f"missing single-task-fast operation: {name}")
    return operation(*args)


def _verified_gate(value: Any, schema: str, authority: Mapping[str, Any]) -> bool:
    unsigned = dict(value) if isinstance(value, Mapping) else {}
    supplied = unsigned.pop("receipt_hash", "")
    return (isinstance(value, Mapping) and value.get("schema") == schema
            and value.get("ok") is True and isinstance(value.get("evidence"), list)
            and bool(value["evidence"])
            and value.get("authority_lease") == authority.get("lease")
            and value.get("authority_fence") == authority.get("fence")
            and bool(supplied) and supplied == content_hash(unsigned))


def _verified_hash_receipt(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value.get("provenance"):
        return False
    unsigned = dict(value)
    supplied = unsigned.pop("receipt_hash", "")
    return bool(supplied) and supplied == content_hash(unsigned)


def _fast_generation(value: Any) -> str:
    if isinstance(value, Mapping):
        metrics = value.get("metrics")
        candidates = (value.get("generation"), value.get("generation_id"),
                      metrics.get("generation") if isinstance(metrics, Mapping) else None)
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            generation = _fast_generation(child)
            if generation:
                return generation
    elif isinstance(value, list):
        for child in value:
            generation = _fast_generation(child)
            if generation:
                return generation
    return ""


def _loop_fast_receipt(raw: Mapping[str, Any], *, schema: str, stage: str,
                       repo: str, generation: str) -> dict[str, Any]:
    unsigned = {
        "schema": schema,
        "status": "MEASURED",
        "repo": str(repo),
        "generation": generation,
        "operator": "simplicio-fast",
        "provenance": {"stage": stage, "source_schema": raw.get("schema")},
        "fast_receipt": dict(raw),
    }
    return {**unsigned, "receipt_hash": content_hash(unsigned)}


def _normalize_fast_ingest_receipt(raw: Any, *, repo: str) -> dict[str, Any]:
    if (isinstance(raw, Mapping) and raw.get("schema") == "simplicio.fast-ingest-receipt/v1"
            and raw.get("repo") == str(repo) and _verified_hash_receipt(raw)):
        return dict(raw)
    if isinstance(raw, Mapping) and raw.get("schema") == FAST_INGEST_SCHEMA:
        generation = _fast_generation(raw)
        snapshot = raw.get("snapshot")
        metrics = raw.get("metrics")
        if not isinstance(snapshot, str) and isinstance(metrics, Mapping):
            snapshot = metrics.get("snapshot")
        if generation and isinstance(snapshot, str) and snapshot:
            return _loop_fast_receipt(raw, schema="simplicio.fast-ingest-receipt/v1",
                                      stage="ingest", repo=repo, generation=generation)
    raise RuntimeError("Fast does not support a verifiable ingest receipt")


def _normalize_fast_plan_receipt(raw: Any, *, repo: str, generation: str) -> dict[str, Any]:
    if (isinstance(raw, Mapping) and raw.get("schema") == "simplicio.fast-plan-receipt/v1"
            and isinstance(raw.get("nodes"), list) and _verified_hash_receipt(raw)):
        return dict(raw)
    if isinstance(raw, Mapping) and raw.get("schema") == FAST_PLAN_SCHEMA:
        fast_generation = _fast_generation(raw)
        if isinstance(raw.get("nodes"), list) and fast_generation:
            return _loop_fast_receipt(raw, schema="simplicio.fast-plan-receipt/v1",
                                      stage="plan", repo=repo, generation=fast_generation)
    raise RuntimeError("Fast does not support a verifiable plan receipt")


def _run_single_task_fast(task: Mapping[str, Any], operations: Mapping[str, Any], *, strict: bool = True, clock=time.perf_counter) -> Dict[str, Any]:
    """Execute one pinned local-first attempt through one Dev CLI mutation."""
    started = clock()
    selection = select_single_task_route([task])
    if selection["route"] != SINGLE_TASK_FAST_ROUTE:
        return {"schema": SINGLE_TASK_FAST_SCHEMA, **selection, "status": "ESCALATED"}
    available = dict(operations.get("available_tools") or {})
    missing = [tool for tool in _SINGLE_TASK_REQUIRED_TOOLS if not available.get(tool)]
    fast_engine = str(operations.get("fast_engine") or "python")
    if missing or (strict and fast_engine not in {"rust", "python"}):
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": "BLOCKED", "reason_code": "required_local_tool_unavailable", "missing_tools": missing, "fast_engine": fast_engine}
    try:
        contract = freeze_single_task_contract(task)
    except (TypeError, ValueError) as exc:
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE,
                "status": "BLOCKED", "reason_code": "invalid_semantic_contract",
                "error": f"{type(exc).__name__}: {exc}", "metrics": {"phase_timings_ms": {}, "total_ms": (clock() - started) * 1000}}
    timings = {}
    try:
        phase = clock()
        foreground = _call(operations, "mapper_foreground", contract)
    except Exception as exc:
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE,
                "status": "BLOCKED", "reason_code": "mapper_operation_failed",
                "error": f"{type(exc).__name__}: {exc}", "contract_hash": contract["contract_hash"],
                "metrics": {"phase_timings_ms": timings, "total_ms": (clock() - started) * 1000}}
    timings["foreground_mapper_ms"] = (clock() - phase) * 1000
    if not foreground.get("verified") or not foreground.get("generation"):
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": "BLOCKED", "reason_code": "foreground_context_unverified"}
    mapper_generation = foreground["generation"]
    background = _call(operations, "mapper_enqueue_deep", contract, mapper_generation)
    phase = clock()
    context = _call(operations, "fast_context", contract, foreground, fast_engine)
    if int(context.get("bytes", 0)) > contract["budgets"]["max_context_bytes"] or int(context.get("tokens", 0)) > contract["budgets"]["max_context_tokens"]:
        escalation = _call(operations, "full_pipeline", contract, ["target_expansion"])
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": "ESCALATED", "reason_code": "context_budget_exceeded", "triggers": ["target_expansion"], "escalation": escalation}
    fast_generation = context.get("generation")
    plan = _call(operations, "fast_plan", contract, context, fast_generation)
    timings["fast_context_plan_ms"] = (clock() - phase) * 1000
    if not fast_generation or plan.get("generation") != fast_generation:
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": "BLOCKED", "reason_code": "fast_generation_mismatch"}
    pins = {"mapper": _call(operations, "pin_generation", "mapper", mapper_generation), "fast": _call(operations, "pin_generation", "fast", fast_generation)}
    if any(not _verified_hash_receipt(pin) or pin.get("component") != component
           or pin.get("generation") != (mapper_generation if component == "mapper" else fast_generation)
           for component, pin in pins.items()):
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": "BLOCKED", "reason_code": "generation_pin_invalid"}
    authority = _call(operations, "issue_authority", contract, plan, pins)
    if (not _verified_hash_receipt(authority) or not authority.get("valid") or authority.get("contract_hash") != contract["contract_hash"] or authority.get("pins") != pins or not authority.get("lease") or authority.get("fence") is None
            or authority.get("issue") != contract["issue"] or authority.get("source_revision") != contract["source_revision"] or authority.get("targets") != contract["target_hints"]):
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": "BLOCKED", "reason_code": "mutation_authority_invalid"}
    before = _call(operations, "source_digest")
    phase = clock()
    def mark_first_edit(_receipt=None):
        # Compatibility callback only; timing authority belongs to the
        # post-apply Dev CLI receipt and is never sampled before mutation.
        return None
    try:
        mutation = _call(operations, "dev_cli_transaction", authority, plan, mark_first_edit)
    except Exception as exc:
        timings["total_ms"] = (clock() - started) * 1000
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE,
                "status": "BLOCKED", "reason_code": "dev_cli_operation_failed",
                "error": f"{type(exc).__name__}: {exc}", "contract_hash": contract["contract_hash"],
                "metrics": {"phase_timings_ms": timings}}
    receipt_first_edit = mutation.get("first_edit_ms")
    if isinstance(receipt_first_edit, (int, float)) and receipt_first_edit >= 0:
        timings["time_to_first_edit_ms"] = float(receipt_first_edit)
    else:
        return {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE,
                "status": "BLOCKED", "reason_code": "first_edit_receipt_missing",
                "contract_hash": contract["contract_hash"], "metrics": {"phase_timings_ms": timings}}
    timings["mutation_ms"] = (clock() - phase) * 1000
    after = _call(operations, "source_digest")
    verification = _call(operations, "focused_verify", contract["verification_commands"], mutation)
    expected_after = mutation.get("source_after")
    source_drift = (
        before != mutation.get("source_before", before)
        or not isinstance(expected_after, str)
        or not expected_after
        or after != expected_after
    )
    triggers = _measured_escalations(contract, mutation, verification, source_drift)
    deep = _call(operations, "background_status", background)
    active_generations = {"mapper": mapper_generation, "fast": fast_generation}
    if triggers:
        escalation = _call(operations, "full_pipeline", contract, triggers)
        status = "ESCALATED"
    else:
        try:
            watcher = _call(operations, "watcher_verify", contract, mutation, verification)
            regression = _call(operations, "regression_gates", contract, mutation)
        except Exception as exc:
            watcher, regression = {}, {}
            gate_error = f"{type(exc).__name__}: {exc}"
        else:
            gate_error = ""
        escalation = None
        gates_ok = (_verified_gate(watcher, "simplicio.watcher-receipt/v1", authority)
                    and _verified_gate(regression, "simplicio.dod-receipt/v1", authority)
                    and regression.get("dod") is True)
        status = "COMPLETED" if verification.get("focused_ok") and gates_ok else "BLOCKED"
    timings["total_ms"] = (clock() - started) * 1000
    return {
        "schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE, "status": status,
        "reason_code": triggers[0] if triggers else ("verified_completion" if status == "COMPLETED" else "evidence_gate_failed"),
        "contract_hash": contract["contract_hash"], "active_generations": active_generations, "pins": pins,
        "background": {"enqueued": True, "available": bool(deep.get("available")), "generation": deep.get("generation"), "promoted_mid_attempt": False},
        "mutation": {"transactions": 1, "receipt": mutation.get("receipt"), "source_after": after},
        "verification": verification, "watcher": watcher if not triggers else None,
        "dod": regression if not triggers else None, "gate_error": gate_error if not triggers else "",
        "triggers": triggers, "escalation": escalation,
        "metrics": {"phase_timings_ms": timings, "context_bytes": int(context.get("bytes", 0)), "context_tokens": int(context.get("tokens", 0)), "cache_decision": context.get("cache_decision", "miss")},
        "stop": contract["stop"], "recovery": contract["recovery"], "max_iterations": contract["budgets"]["max_iterations"],
    }


def run_single_task_fast(task: Mapping[str, Any], operations: Mapping[str, Any], *, strict: bool = True, clock=time.perf_counter) -> Dict[str, Any]:
    """Fail-closed public boundary: operational exceptions always become receipts."""
    started = clock()
    try:
        result = _run_single_task_fast(task, operations, strict=strict, clock=clock)
    except Exception as exc:
        result = {"schema": SINGLE_TASK_FAST_SCHEMA, "route": SINGLE_TASK_FAST_ROUTE,
                "status": "BLOCKED", "reason_code": "local_operation_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "metrics": {"phase_timings_ms": {}, "total_ms": (clock() - started) * 1000}}
    if result.get("status") == "BLOCKED":
        result["stop"] = dict(task.get("stop") or {})
        result["recovery"] = dict(task.get("recovery") or {})
        handler = operations.get("stop_recovery")
        if callable(handler):
            try:
                result["stop_recovery_receipt"] = handler(result)
            except Exception as exc:
                result["stop_recovery_receipt"] = {"applied": False, "error": f"{type(exc).__name__}: {exc}"}
        else:
            result["stop_recovery_receipt"] = {"applied": False, "reason": "stop_recovery_operator_unavailable"}
    return result


def benchmark_single_task_fast(factory, *, repetitions: int = 10, threshold_ms: float = 1000.0):
    if repetitions < 10:
        raise ValueError("benchmark requires at least ten repetitions")
    samples = []
    for _ in range(repetitions):
        task, operations = factory()
        receipt = run_single_task_fast(task, operations)
        samples.append(float(receipt["metrics"]["phase_timings_ms"]["time_to_first_edit_ms"]))
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {"schema": "simplicio.single-task-fast-benchmark/v1", "repetitions": repetitions, "cold_ms": samples[0], "warm_ms": sum(samples[1:]) / (len(samples) - 1), "p95_time_to_first_edit_ms": p95, "threshold_ms": threshold_ms, "passed": p95 <= threshold_ms}


def build_local_single_task_operations(task: Mapping[str, Any], *, root: str = ".") -> Dict[str, Any]:
    """Bind the route to installed local operators; never invokes Runtime or an LLM."""
    repo = Path(root).resolve()
    mapper = shutil.which("simplicio-mapper")
    fast = shutil.which("simplicio-fast")
    dev_cli = shutil.which("simplicio-dev-cli")
    changeset = task.get("changeset")

    allowed_env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT") if key in os.environ}
    allowed_env["SIMPLICIO_EXECUTION_PROFILE"] = "standalone"

    def valid_receipt(value, schema):
        if not isinstance(value, Mapping) or value.get("schema") != schema:
            return False
        unsigned = dict(value)
        supplied = unsigned.pop("receipt_hash", "")
        return bool(supplied) and supplied == content_hash(unsigned)

    def run_json(argv, *, input_value=None):
        result = subprocess.run(argv, cwd=str(repo), input=json.dumps(input_value) if input_value is not None else None,
                                capture_output=True, text=True, timeout=180, check=False,
                                env=allowed_env)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "operator failed").strip())
        output = result.stdout.strip()
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, Mapping):
            return dict(value)
        lines = [line for line in output.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                return dict(value)
        raise RuntimeError("operator did not emit a JSON receipt")

    def source_digest():
        value = {}
        for hint in sorted(task.get("target_hints") or []):
            path = (repo / hint).resolve()
            if repo != path and repo not in path.parents:
                raise ValueError("target escapes repository")
            value[hint] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return content_hash(value)

    def mapper_foreground(contract):
        receipt = run_json([mapper, "index", str(repo), "--json"])
        return normalize_mapper_index_receipt(
            receipt, repo=str(repo), content_hash=content_hash, valid_receipt=valid_receipt
        )

    def fast_context(contract, foreground, engine):
        ingest = run_json([fast, "--fast-engine", engine, "ingest", str(repo), "--json"])
        ingest_receipt = _normalize_fast_ingest_receipt(ingest, repo=str(repo))
        understanding = run_json([fast, "--fast-engine", engine, "understand", "--root", str(repo),
                                  "--max-bytes", str(contract["budgets"]["max_context_bytes"]), contract["goal"]])
        generation = _fast_generation(understanding) or str(ingest_receipt.get("generation"))
        raw = json.dumps(understanding, sort_keys=True).encode("utf-8")
        return {"generation": generation, "bytes": len(raw), "tokens": (len(raw) + 3) // 4,
                "cache_decision": str(understanding.get("cache_decision") or "local"),
                "receipt": understanding, "ingest_receipt": ingest_receipt}

    def fast_plan(contract, context, generation):
        receipt = run_json([fast, "--fast-engine", "python", "plan", "--root", str(repo),
                            "--max-bytes", str(contract["budgets"]["max_context_bytes"]), contract["goal"]])
        plan_receipt = _normalize_fast_plan_receipt(receipt, repo=str(repo), generation=generation)
        return {"generation": str(plan_receipt.get("generation") or generation), "receipt": plan_receipt,
                "changeset": changeset}

    def dev_transaction(authority, plan, first_edit):
        if not isinstance(changeset, Mapping):
            raise ValueError("local execution requires a deterministic changeset")
        before = source_digest()
        binding = {"changeset": changeset, "plan": plan, "authority": authority,
                   "source_revision": task.get("source_revision"), "issue": task.get("issue"),
                   "targets": task.get("target_hints")}
        receipt = run_json([dev_cli, "changeset", "--root", str(repo), "--plan", "-", "--apply", "--json"], input_value=binding)
        if not valid_receipt(receipt, "simplicio.dev-cli-changeset-receipt/v1"):
            raise RuntimeError("Dev CLI does not support a verifiable changeset receipt")
        if any(receipt.get(key) != value for key, value in {
                "authority_lease": authority.get("lease"), "authority_fence": authority.get("fence"),
                "source_revision": task.get("source_revision"), "issue": task.get("issue"),
                "targets": task.get("target_hints"), "changeset_hash": content_hash(changeset),
                "plan_hash": content_hash(plan)}.items()):
            raise RuntimeError("Dev CLI receipt binding mismatch")
        touched = receipt.get("touched_paths")
        if not isinstance(touched, list) or not touched or not set(touched).issubset(set(task.get("target_hints") or [])):
            raise RuntimeError("Dev CLI diff escaped the authorized target corridor")
        if not isinstance(receipt.get("first_edit_ms"), (int, float)) or receipt["first_edit_ms"] < 0:
            raise RuntimeError("Dev CLI first-edit receipt missing")
        if receipt.get("status") not in {"applied", "completed", "success"} or receipt.get("applied") is not True:
            raise RuntimeError(f"Dev CLI refused changeset: {receipt.get('errors') or receipt.get('status')}")
        after = source_digest()
        if after == before:
            raise RuntimeError("Dev CLI reported apply without a source change")
        return {"diff_lines": int(receipt.get("diff_lines") or 0), "receipt": receipt,
                "source_before": before, "source_after": after,
                "first_edit_ms": receipt["first_edit_ms"],
                "new_files": bool(receipt.get("new_files")), "target_expanded": bool(receipt.get("target_expanded"))}

    def verify(commands, mutation):
        evidence = []
        for command in commands:
            result = subprocess.run(command, cwd=str(repo), capture_output=True, text=True, timeout=180, check=False, env=allowed_env)
            evidence.append({"argv": command, "returncode": result.returncode})
            if result.returncode != 0:
                return {"focused_ok": False, "evidence": evidence}
        return {"focused_ok": True, "evidence": evidence}

    available = {"mapper": bool(mapper), "fast": bool(fast), "dev_cli": bool(dev_cli)}
    return {
        "available_tools": available, "fast_engine": "python",
        "mapper_foreground": mapper_foreground,
        "mapper_enqueue_deep": lambda contract, generation: {"generation": generation, "available": True},
        "fast_context": fast_context,
        "fast_plan": fast_plan,
        "pin_generation": lambda component, generation: ((task.get("generation_pins") or {}).get(component) or {}),
        "issue_authority": lambda contract, plan, pins: dict(task.get("authority_receipt") or {}),
        "source_digest": source_digest, "dev_cli_transaction": dev_transaction,
        "focused_verify": verify,
        "background_status": lambda background: background,
        "watcher_verify": lambda contract, mutation, verification: dict(task.get("watcher_receipt") or {}),
        "regression_gates": lambda contract, mutation: dict(task.get("dod_receipt") or {}),
        "stop_recovery": lambda blocked: {"applied": False, "preserved": False,
                                            "reason": "verifiable_stop_recovery_operator_unavailable"},
        "full_pipeline": lambda contract, triggers: {"status": "BLOCKED", "reason_code": "full_pipeline_handoff_required", "triggers": triggers},
        "local_operator_binding": True,
    }


def _collection_task_id(task: Mapping[str, Any], index: int) -> str:
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    return str(task.get("id") or identity.get("id") or task.get("issue") or f"task-{index}").strip()


def _collection_dependencies(task: Mapping[str, Any]) -> list[str]:
    raw: Any = task.get("depends_on")
    if raw is None:
        raw = task.get("dependencies")
    if isinstance(raw, Mapping):
        raw = raw.get("items") or raw.get("depends_on") or raw.get("dependencies") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.replace(",", " ").split() if item.strip()]
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _ordered_two_task_collection(
    tasks: Sequence[Mapping[str, Any]],
) -> list[tuple[int, Mapping[str, Any]]]:
    """Validate the narrow collection contract and reuse Loop's DAG ordering boundary."""
    if len(tasks) != 2:
        raise ValueError("single-task-fast ordered provider route requires exactly two tasks")
    rows = []
    aliases: dict[str, str] = {}
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, Mapping):
            raise ValueError(f"task {index} must be an object")
        task_id = _collection_task_id(task, index)
        if not task_id or task_id in aliases:
            raise ValueError("ordered collection task ids must be unique and non-empty")
        aliases[task_id] = task_id
        identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
        for alias in (identity.get("id"), str(index), f"task-{index}"):
            if str(alias or "").strip():
                aliases[str(alias).strip()] = task_id
        rows.append({
            "task_id": task_id,
            "task_index": index,
            "task_spec": {"depends_on": _collection_dependencies(task)},
        })
    edges = sum(len(row["task_spec"]["depends_on"]) for row in rows)
    if edges != 1:
        raise ValueError("ordered collection requires one dependency from creation to edit")
    for row in rows:
        resolved = []
        for dependency in row["task_spec"]["depends_on"]:
            target = aliases.get(dependency)
            if target is None:
                raise ValueError(
                    f"ordered collection dependency is not part of the collection: "
                    f"{row['task_id']}->{dependency}"
                )
            resolved.append(target)
        row["task_spec"]["depends_on"] = resolved
    try:
        # Keep the authoritative topological ordering in the Loop runner.  This
        # preflight only narrows the public contract before that boundary runs.
        from .runner import _ordered_dispatch_items
        ordered_rows = _ordered_dispatch_items(rows)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    return [(int(row["task_index"]), tasks[int(row["task_index"]) - 1]) for row in ordered_rows]


def _receipt_present(value: Any) -> bool:
    if isinstance(value, Mapping):
        status = str(value.get("status") or value.get("execution_state") or "").strip().lower()
        return bool(value) and status in {
            "measured", "ready", "verified", "applied", "completed", "success",
            "succeeded", "no_change", "pass", "passed",
        }
    if isinstance(value, str):
        return bool(value.strip()) and Path(value).is_file()
    return False


def _finalize_two_task_receipt(
    tasks: Sequence[Mapping[str, Any]],
    ordered: Sequence[tuple[int, Mapping[str, Any]]],
    raw: Any,
) -> Dict[str, Any]:
    """Project a runner result only after both task evidence chains are complete."""
    base = dict(raw) if isinstance(raw, Mapping) else {}
    receipt = {
        "schema": SINGLE_TASK_FAST_SCHEMA,
        "route": ORDERED_TWO_TASK_ROUTE,
        "task_count": 2,
        "execution_order": [_collection_task_id(task, index) for index, task in ordered],
        **base,
    }
    receipt["schema"] = SINGLE_TASK_FAST_SCHEMA
    receipt["route"] = ORDERED_TWO_TASK_ROUTE
    receipt["task_count"] = 2
    receipt["execution_order"] = [_collection_task_id(task, index) for index, task in ordered]
    task_receipts = receipt.get("tasks") or receipt.get("per_task_evidence") or []
    if not isinstance(task_receipts, list) or len(task_receipts) != 2:
        receipt.update({
            "status": "BLOCKED",
            "reason_code": (
                str(base.get("reason_code") or "per_task_evidence_missing")
                if str(base.get("status") or "").upper() != "COMPLETED"
                else "per_task_evidence_missing"
            ),
        })
        return receipt
    by_id = {_collection_task_id(task, index): (index, task) for index, task in ordered}
    normalized = []
    for item in task_receipts:
        if not isinstance(item, Mapping):
            receipt.update({"status": "BLOCKED", "reason_code": "per_task_evidence_missing"})
            return receipt
        task_id = str(item.get("task_id") or "").strip()
        if by_id.get(task_id) is None or str(item.get("status") or "").lower() not in {
            "succeeded", "applied", "completed", "no_change",
        }:
            receipt.update({"status": "BLOCKED", "reason_code": "per_task_execution_failed"})
            return receipt
        required = ("mapper_receipt", "fast_receipt", "provider_receipt", "dev_cli_receipt", "evidence")
        if any(not _receipt_present(item.get(field)) for field in required):
            receipt.update({"status": "BLOCKED", "reason_code": "per_task_evidence_missing"})
            return receipt
        normalized.append(dict(item))
    if [str(item.get("task_id")) for item in normalized] != receipt["execution_order"]:
        receipt.update({"status": "BLOCKED", "reason_code": "dependency_order_not_preserved"})
        return receipt
    receipt["tasks"] = normalized
    if str(receipt.get("status") or "").upper() != "COMPLETED":
        receipt["status"] = "BLOCKED"
        receipt.setdefault("reason_code", "provider_loop_not_completed")
    return receipt


def _read_receipt(path: Any) -> Any:
    if isinstance(path, Mapping):
        return dict(path)
    if isinstance(path, Path):
        path = str(path)
    if not isinstance(path, str) or not path.strip():
        return None
    candidate = Path(path)
    try:
        return json.loads(candidate.read_text(encoding="utf-8")) if candidate.is_file() else None
    except (OSError, TypeError, ValueError):
        return None


def _run_existing_two_task_loop(
    *,
    tasks: Sequence[Mapping[str, Any]],
    ordered: Sequence[tuple[int, Mapping[str, Any]]],
    task_file: str,
    repo: str,
    provider_worker: str,
) -> Dict[str, Any]:
    """Bind the new public collection contract to the existing Loop runner."""
    if not task_file or not Path(task_file).is_file():
        return {"status": "BLOCKED", "reason_code": "task_file_missing"}
    if provider_worker != "openrouter":
        return {"status": "BLOCKED", "reason_code": "provider_worker_unsupported"}
    try:
        # Fast is a required, read-only preparation stage for this provider route.
        # Mutation still belongs exclusively to conduct_run's existing Dev CLI path.
        from .fast_integration import (
            FastConfig,
            FastIntegrationError,
            FastLoopIntegration,
            _creation_intent,
            _normalize_repo_path,
        )
        fast_config = FastConfig.from_env()
        fast_config = FastConfig(
            mode="required", command=fast_config.command, snapshot=fast_config.snapshot,
            state=fast_config.state, max_bytes=fast_config.max_bytes,
            timeout_seconds=fast_config.timeout_seconds,
            require_binding=fast_config.require_binding, engine=fast_config.engine,
        )
        fast_receipts = []
        pending_creation_targets: list[str] = []
        saved_provider_env = {
            key: os.environ[key] for key in _PROVIDER_SECRET_ENV if key in os.environ
        }
        try:
            for key in _PROVIDER_SECRET_ENV:
                os.environ.pop(key, None)
            for index, task in ordered:
                text = str(task.get("original_text") or task.get("goal") or "").strip()
                try:
                    prepared = FastLoopIntegration(
                        repo, config=fast_config,
                        extra_targets=[str(path) for path in (task.get("target_hints") or [])],
                        pending_creation_targets=pending_creation_targets,
                    ).prepare(text)
                except (FastIntegrationError, OSError, TypeError, ValueError) as exc:
                    return {
                        "status": "BLOCKED", "reason_code": "fast_operation_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "fast_receipts": fast_receipts,
                    }
                if prepared.get("status") != "READY":
                    return {"status": "BLOCKED", "reason_code": "fast_operation_failed", "fast_receipts": fast_receipts}
                fast_receipts.append((index, prepared))
                if _creation_intent(text):
                    candidates = [str(path) for path in (task.get("target_hints") or [])]
                    for line in text.splitlines():
                        label, separator, value = line.partition(":")
                        if separator and label.strip().casefold() in {"target", "alvo"}:
                            candidates.append(value.strip().strip("`'\""))
                    for candidate in candidates:
                        normalized = _normalize_repo_path(candidate.replace("\\", "/"))
                        if normalized and normalized not in pending_creation_targets:
                            pending_creation_targets.append(normalized)
        finally:
            for key in _PROVIDER_SECRET_ENV:
                os.environ.pop(key, None)
            os.environ.update(saved_provider_env)
        from .runner import conduct_run
        run_result = conduct_run(repo, task_file, "verified", 12, provider_worker=provider_worker)
        run_dir = Path(str(run_result.get("run_dir") or ""))
        batch = _read_receipt(run_dir / "operator-batch.json") or {}
        workers = batch.get("workers") if isinstance(batch, Mapping) else []
        workers = workers if isinstance(workers, list) else []
        state = run_result.get("state") if isinstance(run_result.get("state"), Mapping) else {}
        mapper_path = (state.get("mapper") or {}).get("receipt") or run_dir / "mapper-context.json"
        fast_by_index = {index: receipt for index, receipt in fast_receipts}
        task_receipts = []
        for index, task in ordered:
            worker = next((item for item in workers if int(item.get("task_index") or 0) == index), {})
            operator_path = worker.get("operator_receipt") or run_dir / f"operator-receipt-{index}.json"
            operator = _read_receipt(operator_path)
            evidence_path = worker.get("evidence_receipt")
            evidence = _read_receipt(evidence_path)
            provider_path = operator.get("provider_worker_receipt") if isinstance(operator, Mapping) else ""
            task_receipts.append({
                "task_id": _collection_task_id(task, index),
                "task_index": index,
                "status": worker.get("status", "blocked"),
                "mapper_receipt": str(mapper_path) if Path(mapper_path).is_file() else None,
                "fast_receipt": fast_by_index.get(index),
                "provider_receipt": _read_receipt(provider_path),
                "dev_cli_receipt": operator,
                "evidence": evidence,
                "worker": worker,
            })
        outcome = run_result.get("outcome") if isinstance(run_result.get("outcome"), Mapping) else {}
        completed = (
            int(outcome.get("exit_code") if outcome.get("exit_code") is not None else 2) == 0
            and str((run_result.get("state") or {}).get("phase") or "") == "done"
            and all(str(item.get("status") or "") == "succeeded" for item in workers)
            and bool((batch.get("receipt_contract") or {}).get("ready"))
        )
        return {
            "status": "COMPLETED" if completed else "BLOCKED",
            "reason_code": "verified_completion" if completed else "provider_loop_not_completed",
            "run_id": run_result.get("manifest", {}).get("run_id", ""),
            "run_dir": str(run_dir),
            "fast_receipts": [receipt for _, receipt in fast_receipts],
            "tasks": task_receipts,
            "runner": run_result,
        }
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        return {"status": "BLOCKED", "reason_code": "provider_loop_failed", "error": f"{type(exc).__name__}: {exc}"}


def dispatch_single_task_fast(
    tasks: Sequence[Mapping[str, Any]],
    operations: Optional[Mapping[str, Any]] = None,
    *,
    task_file: str = "",
    repo: str = ".",
    provider_worker: Optional[str] = None,
) -> Dict[str, Any]:
    """Production dispatch boundary used by the CLI and runner adapters.

    Route selection is always available. Execution fails closed until a local
    Mapper/Fast/Dev-CLI adapter supplies the operation set.
    """
    if len(tasks) == 2:
        try:
            ordered = _ordered_two_task_collection(tasks)
        except (TypeError, ValueError) as exc:
            return {
                "schema": SINGLE_TASK_FAST_SCHEMA, "route": ORDERED_TWO_TASK_ROUTE,
                "status": "BLOCKED", "reason_code": "invalid_two_task_collection",
                "error": f"{type(exc).__name__}: {exc}",
            }
        selected_provider = str(
            provider_worker or os.environ.get("SIMPLICIO_PROVIDER_WORKER") or "openrouter"
        ).strip().lower()
        collection_runner = operations.get("provider_backed_collection") if isinstance(operations, Mapping) else None
        if callable(collection_runner):
            try:
                raw = collection_runner(
                    tasks=ordered, task_file=task_file, repo=repo,
                    provider_worker=selected_provider,
                )
            except Exception as exc:
                raw = {"status": "BLOCKED", "reason_code": "provider_loop_failed",
                       "error": f"{type(exc).__name__}: {exc}"}
        else:
            raw = _run_existing_two_task_loop(
                tasks=tasks, ordered=ordered, task_file=task_file, repo=repo,
                provider_worker=selected_provider,
            )
        return _finalize_two_task_receipt(tasks, ordered, raw)

    selection = select_single_task_route(tasks)
    if selection["route"] != SINGLE_TASK_FAST_ROUTE:
        return {"schema": SINGLE_TASK_FAST_SCHEMA, **selection, "status": "ESCALATED"}
    if operations is None:
        if not isinstance(tasks[0].get("changeset"), Mapping):
            return {"schema": SINGLE_TASK_FAST_SCHEMA, **selection, "status": "BLOCKED",
                    "reason_code": "mapper_operation_failed",
                    "error": "ValueError: local execution requires a deterministic changeset"}
        try:
            operations = build_local_single_task_operations(tasks[0], root=str(tasks[0].get("repo") or "."))
        except Exception as exc:
            return {"schema": SINGLE_TASK_FAST_SCHEMA, **selection, "status": "BLOCKED",
                    "reason_code": "mapper_operation_failed",
                    "error": f"{type(exc).__name__}: {exc}"}
        available = operations.get("available_tools") if isinstance(operations, Mapping) else None
        if isinstance(available, Mapping):
            missing = sorted(str(name) for name, present in available.items() if not present)
            if missing:
                return {
                    "schema": SINGLE_TASK_FAST_SCHEMA, **selection, "status": "BLOCKED",
                    "reason_code": "optional_local_operator_unavailable",
                    "available_tools": dict(available), "missing_tools": missing,
                }
    return run_single_task_fast(tasks[0], operations)


__all__.extend(["SINGLE_TASK_FAST_SCHEMA", "SINGLE_TASK_FAST_ROUTE", "FULL_PIPELINE_ROUTE", "ORDERED_TWO_TASK_ROUTE", "freeze_single_task_contract", "select_single_task_route", "run_single_task_fast", "benchmark_single_task_fast", "build_local_single_task_operations", "dispatch_single_task_fast"])
