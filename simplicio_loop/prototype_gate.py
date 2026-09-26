"""Prototype-First contract owned by Loop (issue #568).

This module is the small semantic control-plane shared by Mapper and Dev CLI.  It
does not generate code or call a model; it freezes the plan, budget and decision
boundary so adapters cannot silently bypass the gate.

P0 foundation slice (issue #568, this repo's own piece): four versioned schemas
(`plan`, `candidate`, `decision`, `receipt`), an explainable prototype-necessity
classifier, and a promotion state machine (`P0 -> P1 -> P2 -> FULL`) with bounded
`REVISE` + stall detection + drift invalidation. Candidate fan-out execution
(`simplicio_loop/prototype_fanout.py`, a pluggable `CandidateExecutor` with a
real `LocalSubprocessExecutor` default) and independent judgment
(`simplicio_loop/prototype_judge.py`, a pluggable `Judge` protocol with a
deterministic `RuleBasedJudge` default, wired via `judge_and_decide()`/
`judge_transition()` into a real ACCEPT/REVISE/REJECT transition through
`apply_decision` below) are both now wired in. Multi-repo conformance
(`scripts/prototype_conformance_suite.py`) and the adversarial/chaos-security
suite (`tests/test_prototype_gate_adversarial.py`) validate this contract
from outside the module. See each module's own docstring for its scoring
contract, self-judging block, and LLM-backed-judge extension point.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

# Reuse the repository's stall/oscillation detector (fingerprint + K-repeat) instead of
# reinventing it -- same discipline as `feedback_recovery_agent.py`'s "READ IT, don't reinvent".
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

PLAN_SCHEMA = "simplicio.prototype-plan/v1"
CANDIDATE_SCHEMA = "simplicio.prototype-candidate/v1"
DECISION_SCHEMA = "simplicio.prototype-decision/v1"
RECEIPT_SCHEMA = "simplicio.prototype-receipt/v1"
NECESSITY_SCHEMA = "simplicio.prototype-necessity/v1"
NOT_REQUIRED_SCHEMA = "simplicio.prototype-not-required/v1"
STATE_SCHEMA = "simplicio.prototype-state/v1"

TYPES = frozenset(("wireframe", "architecture_diagram", "schema", "data_model", "failing_reproducer", "benchmark_spike", "mock_or_fake", "code_spike", "vertical_slice", "prompt_candidate", "workflow_simulation", "storyboard", "policy_or_security_model"))
LEVELS = ("P0", "P1", "P2", "FULL")
DEFAULT_BUDGET = {"P0": 0.03, "P1": 0.10, "P2": 0.20, "FULL": 1.0}
CANDIDATE_STATUSES = frozenset(("proposed", "validated", "rejected", "accepted", "abandoned"))
DECISIONS = frozenset(("ACCEPT", "REVISE", "REJECT", "BLOCKED"))
RECEIPT_STAGES = (
    "hypothesis", "candidate", "validation", "decision",
    "vertical_slice", "implementation", "tests", "delivery",
)
STATE_STATUSES = frozenset(("in_progress", "resolved", "rejected", "blocked"))
DEFAULT_MAX_REVISE = 3

# Prototype-necessity classifier (#568 P0): a task description carries risk SIGNALS; each
# signal maps to a rule; the rule with the HIGHEST required level wins and every rule that
# fired is returned, so the decision is explainable rather than a black box.
RISK_SIGNALS = (
    "architecture", "ui", "data_model", "api", "multi_repo", "external_effect",
    "new_dependency", "high_uncertainty", "over_budget_threshold", "perf_no_baseline",
    "bug_no_reproducer", "security", "high_blast_radius", "retry_history",
    "explicit_human_request",
)
_NECESSITY_RULES = (
    ("security_or_blast_radius", frozenset({"security", "high_blast_radius"}), "FULL"),
    ("explicit_human_request", frozenset({"explicit_human_request"}), "FULL"),
    ("architecture_or_multi_repo_or_api", frozenset({"architecture", "multi_repo", "api"}), "P2"),
    ("new_dependency_or_data_model_or_external_effect", frozenset({"new_dependency", "data_model", "external_effect"}), "P2"),
    ("uncertainty_or_budget_or_perf", frozenset({"high_uncertainty", "over_budget_threshold", "perf_no_baseline"}), "P1"),
    ("bug_no_reproducer_or_retry_history", frozenset({"bug_no_reproducer", "retry_history"}), "P1"),
    ("ui_only", frozenset({"ui"}), "P0"),
)


class PrototypeGateError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


# Self-hash field per schema, ordered MOST-specific first: a candidate/decision/receipt
# payload legitimately CARRIES an earlier stage's hash (e.g. a decision carries `plan_hash`)
# as reference content that must stay IN the hashed bytes -- only the payload's OWN terminal
# hash field is excluded when recomputing/verifying it.
_SELF_HASH_ORDER = ("receipt_hash", "decision_hash", "candidate_hash", "plan_hash")


def _self_hash_field(payload: Mapping[str, Any]) -> str:
    for field in _SELF_HASH_ORDER:
        if field in payload:
            return field
    return "plan_hash"


def _without_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    field = _self_hash_field(payload)
    return {key: value for key, value in payload.items() if key != field}


def build_plan(*, work_item_id: str, goal: str, prototype_type: str, source_sha: str,
               level: str = "P1", estimated_budget: int | float = 0,
               validators: list[str] | None = None, context_pack_hash: str = "",
               negative_space: list[str] | None = None) -> dict[str, Any]:
    """Build a hash-bound plan accepted by all downstream adapters."""
    if not str(work_item_id).strip() or not str(goal).strip() or not str(source_sha).strip():
        raise PrototypeGateError("work_item_id, goal and source_sha are required")
    if prototype_type not in TYPES:
        raise PrototypeGateError(f"unsupported prototype_type: {prototype_type}")
    if level not in LEVELS:
        raise PrototypeGateError(f"unsupported prototype level: {level}")
    if not isinstance(estimated_budget, (int, float)) or estimated_budget < 0:
        raise PrototypeGateError("estimated_budget must be non-negative")
    payload: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "work_item_id": str(work_item_id),
        "goal": str(goal).strip(),
        "prototype_type": prototype_type,
        "source_sha": str(source_sha),
        "level": level,
        "budget_fraction": DEFAULT_BUDGET[level],
        "estimated_budget": estimated_budget,
        "validators": list(validators or []),
        "context_pack_hash": str(context_pack_hash),
        "negative_space": sorted({str(path) for path in (negative_space or []) if str(path).strip()}),
    }
    payload["plan_hash"] = _hash(payload)
    return payload


def validate_plan(plan: Mapping[str, Any], *, current_source_sha: str | None = None) -> dict[str, Any]:
    """Validate schema, hash and optional source drift without mutating state."""
    if not isinstance(plan, Mapping) or plan.get("schema") != PLAN_SCHEMA:
        raise PrototypeGateError("unsupported prototype plan schema")
    if plan.get("plan_hash") != _hash(_without_hash(plan)):
        raise PrototypeGateError("prototype plan hash mismatch")
    if plan.get("prototype_type") not in TYPES or plan.get("level") not in LEVELS:
        raise PrototypeGateError("prototype type or level is invalid")
    drift = current_source_sha is not None and str(current_source_sha) != str(plan.get("source_sha"))
    result = dict(plan)
    result["source_drift"] = drift
    if drift:
        result["valid"] = False
        result["reason_code"] = "source_drift"
    else:
        result["valid"] = True
    return result


def build_candidate(*, plan: Mapping[str, Any], candidate_id: str, strategy: str, agent_id: str,
                    artifact_hash: str, artifact_location: str = "", model_id: str = "",
                    runtime_id: str = "", inputs_hash: str = "", context_hash: str = "",
                    assumptions: list[str] | None = None, limitations: list[str] | None = None,
                    out_of_scope: list[str] | None = None,
                    measured_costs: Mapping[str, Any] | None = None,
                    validation_results: list[Mapping[str, Any]] | None = None,
                    evidence_refs: list[str] | None = None,
                    safety_classification: str = "unclassified",
                    status: str = "proposed", terminal_reason: str = "") -> dict[str, Any]:
    """Build a hash-bound candidate bound to a plan (`simplicio.prototype-candidate/v1`)."""
    validated_plan = validate_plan(plan)
    if not str(candidate_id).strip() or not str(strategy).strip() or not str(agent_id).strip():
        raise PrototypeGateError("candidate_id, strategy and agent_id are required")
    if not str(artifact_hash).strip():
        raise PrototypeGateError("artifact_hash is required")
    if status not in CANDIDATE_STATUSES:
        raise PrototypeGateError(f"unsupported candidate status: {status}")
    payload: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "plan_hash": validated_plan["plan_hash"],
        "source_sha": validated_plan["source_sha"],
        "candidate_id": str(candidate_id),
        "strategy": str(strategy),
        "agent_id": str(agent_id),
        "model_id": str(model_id),
        "runtime_id": str(runtime_id),
        "artifact_hash": str(artifact_hash),
        "artifact_location": str(artifact_location),
        "inputs_hash": str(inputs_hash),
        "context_hash": str(context_hash),
        "assumptions": list(assumptions or []),
        "limitations": list(limitations or []),
        "out_of_scope": list(out_of_scope or []),
        "measured_costs": dict(measured_costs or {}),
        "validation_results": [dict(v) for v in (validation_results or [])],
        "evidence_refs": list(evidence_refs or []),
        "safety_classification": str(safety_classification),
        "status": status,
        "terminal_reason": str(terminal_reason),
    }
    payload["candidate_hash"] = _hash(payload)
    return payload


def validate_candidate(candidate: Mapping[str, Any], *, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate schema/hash, and optionally that the candidate is bound to `plan`."""
    if not isinstance(candidate, Mapping) or candidate.get("schema") != CANDIDATE_SCHEMA:
        raise PrototypeGateError("unsupported prototype candidate schema")
    if candidate.get("candidate_hash") != _hash(_without_hash(candidate)):
        raise PrototypeGateError("prototype candidate hash mismatch")
    if candidate.get("status") not in CANDIDATE_STATUSES:
        raise PrototypeGateError("prototype candidate status is invalid")
    result = dict(candidate)
    if plan is not None:
        validated_plan = validate_plan(plan)
        bound = candidate.get("plan_hash") == validated_plan["plan_hash"]
        result["plan_bound"] = bound
        if not bound:
            result["valid"] = False
            result["reason_code"] = "plan_mismatch"
            return result
    result["valid"] = True
    return result


def build_decision(*, plan: Mapping[str, Any], candidate_hash: str, decision: str, reason: str = "",
                   judge_id: str = "", judge_independent: bool = True,
                   ranked_candidates: list[Mapping[str, Any]] | None = None,
                   ac_coverage: Mapping[str, Any] | None = None,
                   rejected_candidates: list[Mapping[str, Any]] | None = None,
                   required_changes: list[str] | None = None,
                   allowed_next_stage: str | None = None,
                   expiry: str = "") -> dict[str, Any]:
    """Create an auditable ACCEPT/REVISE/REJECT/BLOCKED decision receipt.

    Optional fields (judge identity/independence, ranked+rejected candidates, AC coverage,
    required changes, the next stage it unlocks, and an expiry/revalidation condition) default
    to empty so existing minimal callers keep working; a judge is fabricated as "not
    independent" by name, never silently assumed independent when unspecified as such.
    """
    validated = validate_plan(plan)
    if decision not in DECISIONS:
        raise PrototypeGateError("invalid prototype decision")
    if allowed_next_stage is not None and allowed_next_stage not in LEVELS:
        raise PrototypeGateError(f"unsupported allowed_next_stage: {allowed_next_stage}")
    payload: dict[str, Any] = {
        "schema": DECISION_SCHEMA,
        "plan_hash": validated["plan_hash"],
        "source_sha": validated["source_sha"],
        "candidate_hash": str(candidate_hash),
        "decision": decision,
        "reason": str(reason),
        "judge_id": str(judge_id),
        "judge_independent": bool(judge_independent),
        "ranked_candidates": [dict(c) for c in (ranked_candidates or [])],
        "ac_coverage": dict(ac_coverage or {}),
        "rejected_candidates": [dict(c) for c in (rejected_candidates or [])],
        "required_changes": list(required_changes or []),
        "allowed_next_stage": allowed_next_stage,
        "expiry": str(expiry),
    }
    payload["decision_hash"] = _hash(payload)
    return payload


def validate_decision(decision: Mapping[str, Any], *, plan: Mapping[str, Any], candidate_hash: str,
                      current_source_sha: str | None = None) -> dict[str, Any]:
    """Fail closed on forged, stale, drifted or non-ACCEPT receipts."""
    plan_result = validate_plan(plan, current_source_sha=current_source_sha)
    if not plan_result["valid"]:
        raise PrototypeGateError("prototype decision source drift")
    if decision.get("schema") != DECISION_SCHEMA or decision.get("decision_hash") != _hash(_without_hash(decision)):
        raise PrototypeGateError("prototype decision schema/hash mismatch")
    if decision.get("plan_hash") != plan.get("plan_hash") or decision.get("candidate_hash") != candidate_hash:
        raise PrototypeGateError("prototype decision is stale or not bound to candidate")
    if current_source_sha is not None and decision.get("source_sha") != current_source_sha:
        raise PrototypeGateError("prototype decision source drift")
    if decision.get("decision") != "ACCEPT":
        raise PrototypeGateError(f"prototype decision is {decision.get('decision')!r}, not ACCEPT")
    return dict(decision)


def build_receipt(*, plan: Mapping[str, Any], candidate: Mapping[str, Any], decision: Mapping[str, Any],
                  stage_hashes: Mapping[str, str] | None = None, attempt: int = 1,
                  fence: str = "") -> dict[str, Any]:
    """Chain hypothesis->candidate->validation->decision->vertical_slice->implementation->
    tests->delivery by hash, plus attempt/fence/plan+source revisions (`.../receipt/v1`)."""
    validated_plan = validate_plan(plan)
    validated_candidate = validate_candidate(candidate, plan=plan)
    if not validated_candidate.get("valid", True):
        raise PrototypeGateError("prototype receipt: candidate is not bound to plan")
    validated_decision = validate_decision(decision, plan=plan, candidate_hash=candidate.get("candidate_hash", ""))
    stages = dict(stage_hashes or {})
    unknown = sorted(set(stages) - set(RECEIPT_STAGES))
    if unknown:
        raise PrototypeGateError(f"unknown receipt stage(s): {unknown}")
    if not isinstance(attempt, int) or attempt < 1:
        raise PrototypeGateError("attempt must be a positive integer")
    payload: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "plan_hash": validated_plan["plan_hash"],
        "source_sha": validated_plan["source_sha"],
        "candidate_hash": candidate.get("candidate_hash"),
        "decision_hash": validated_decision.get("decision_hash"),
        "stage_hashes": {stage: str(stages[stage]) for stage in RECEIPT_STAGES if stage in stages},
        "attempt": int(attempt),
        "fence": str(fence),
        "plan_revision": validated_plan["plan_hash"],
        "source_revision": validated_plan["source_sha"],
    }
    payload["receipt_hash"] = _hash(payload)
    return payload


def validate_receipt(receipt: Mapping[str, Any], *, plan: Mapping[str, Any] | None = None,
                     candidate: Mapping[str, Any] | None = None,
                     decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate schema/hash and, when given, that the receipt is bound to plan/candidate/decision."""
    if not isinstance(receipt, Mapping) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise PrototypeGateError("unsupported prototype receipt schema")
    if receipt.get("receipt_hash") != _hash(_without_hash(receipt)):
        raise PrototypeGateError("prototype receipt hash mismatch")
    result = dict(receipt)
    if plan is not None and receipt.get("plan_hash") != validate_plan(plan)["plan_hash"]:
        result["valid"] = False
        result["reason_code"] = "plan_mismatch"
        return result
    if candidate is not None and receipt.get("candidate_hash") != candidate.get("candidate_hash"):
        result["valid"] = False
        result["reason_code"] = "candidate_mismatch"
        return result
    if decision is not None and receipt.get("decision_hash") != decision.get("decision_hash"):
        result["valid"] = False
        result["reason_code"] = "decision_mismatch"
        return result
    result["valid"] = True
    return result


def classify_necessity(*, task_description: str, signals: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """Explainable prototype-necessity classifier (#568 P0).

    Given a task description + boolean risk signals, decides whether a prototype is required
    and at which level (P0/P1/P2/FULL), OR that none is required. Always returns WHICH rule(s)
    fired -- never a bare verdict -- so the decision can be audited, not trusted blindly.
    """
    signals = {k: bool(v) for k, v in (signals or {}).items()}
    unknown = sorted(set(signals) - set(RISK_SIGNALS))
    if unknown:
        raise PrototypeGateError(f"unknown risk signal(s): {unknown}")
    active = {name for name, value in signals.items() if value}
    fired: list[dict[str, Any]] = []
    required_level: str | None = None
    for rule_id, trigger_signals, level in _NECESSITY_RULES:
        hit = trigger_signals & active
        if not hit:
            continue
        fired.append({"rule": rule_id, "signals": sorted(hit), "level": level})
        if required_level is None or LEVELS.index(level) > LEVELS.index(required_level):
            required_level = level
    description = str(task_description).strip()
    if required_level is None:
        return {
            "schema": NECESSITY_SCHEMA,
            "task_description": description,
            "required": False,
            "level": None,
            "rules_fired": [],
            "reason": "no risk signal matched -- trivial/low-risk work, prototype not required",
        }
    return {
        "schema": NECESSITY_SCHEMA,
        "task_description": description,
        "required": True,
        "level": required_level,
        "rules_fired": fired,
        "reason": "matched %d rule(s); highest required level is %s" % (len(fired), required_level),
    }


def build_not_required_receipt(*, work_item_id: str, task_description: str,
                               signals: Mapping[str, bool] | None = None,
                               estimate: Mapping[str, Any] | None = None,
                               policy: str = "") -> dict[str, Any]:
    """Emit a `prototype_not_required` receipt for trivial/low-risk work.

    Refuses (fails closed) to emit one when the classifier actually says a prototype IS
    required -- this is a receipt, not an override.
    """
    classification = classify_necessity(task_description=task_description, signals=signals)
    if classification["required"]:
        raise PrototypeGateError(
            "cannot emit prototype_not_required: classifier requires level %s" % classification["level"]
        )
    payload: dict[str, Any] = {
        "schema": NOT_REQUIRED_SCHEMA,
        "work_item_id": str(work_item_id),
        "task_description": classification["task_description"],
        "reason": classification["reason"],
        "estimate": dict(estimate or {}),
        "policy": str(policy),
    }
    payload["not_required_hash"] = _hash(payload)
    return payload


# --- Promotion state machine (P0 -> P1 -> P2 -> FULL), bounded REVISE, stall + drift ---------

def init_state(*, work_item_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    """Initialize promotion state at the plan's own starting level. Pure; no I/O."""
    validated = validate_plan(plan)
    return {
        "schema": STATE_SCHEMA,
        "work_item_id": str(work_item_id),
        "plan_hash": validated["plan_hash"],
        "source_sha": validated["source_sha"],
        "current_level": validated["level"],
        "revise_count": 0,
        "history": [],
        "status": "in_progress",
        "blocked_reason": None,
    }


def apply_decision(state: Mapping[str, Any], *, plan: Mapping[str, Any], decision: Mapping[str, Any],
                   candidate_hash: str, current_source_sha: str | None = None,
                   max_revise: int = DEFAULT_MAX_REVISE) -> dict[str, Any]:
    """Pure state transition: (state, decision) -> NEW state. Never mutates the input.

    Enforces: P0->P1->P2->FULL promotion order (ACCEPT only ever unlocks the NEXT stage, and
    only reaches `resolved` once FULL itself is ACCEPTed -- ACCEPT never marks the task done by
    itself before that); REVISE is bounded by `max_revise` (exceeding it -> `blocked`); a
    plan/source drift invalidates the whole flow (schema drift raises, since that is a
    programmer error, not a runtime condition to route around).
    """
    if not isinstance(state, Mapping) or state.get("schema") != STATE_SCHEMA:
        raise PrototypeGateError("unsupported prototype state schema")
    new_state = dict(state)
    validated_plan = validate_plan(plan, current_source_sha=current_source_sha)
    if state.get("plan_hash") != validated_plan["plan_hash"]:
        new_state["status"] = "blocked"
        new_state["blocked_reason"] = "plan_drift"
        return new_state
    if not validated_plan["valid"]:
        new_state["status"] = "blocked"
        new_state["blocked_reason"] = "source_drift"
        return new_state
    if state.get("status") != "in_progress":
        raise PrototypeGateError(f"prototype state is terminal ({state.get('status')}); cannot apply a new decision")
    outcome = decision.get("decision")
    if outcome not in DECISIONS:
        raise PrototypeGateError("invalid prototype decision")

    history = list(state.get("history", []))
    current_level = state["current_level"]

    if outcome == "ACCEPT":
        validated_decision = validate_decision(
            decision, plan=plan, candidate_hash=candidate_hash, current_source_sha=current_source_sha,
        )
        history.append({
            "level": current_level, "decision": "ACCEPT",
            "decision_hash": validated_decision["decision_hash"], "reason": decision.get("reason", ""),
        })
        idx = LEVELS.index(current_level)
        next_level = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
        new_state["history"] = history
        new_state["revise_count"] = 0
        if next_level is None:
            new_state["status"] = "resolved"
        else:
            new_state["current_level"] = next_level
            new_state["status"] = "in_progress"
        return new_state

    if decision.get("plan_hash") != state.get("plan_hash") or decision.get("candidate_hash") != candidate_hash:
        raise PrototypeGateError("prototype decision is stale or not bound to candidate")

    if outcome == "REVISE":
        revise_count = int(state.get("revise_count", 0)) + 1
        history.append({
            "level": current_level, "decision": "REVISE",
            "decision_hash": decision.get("decision_hash"), "reason": decision.get("reason", ""),
        })
        new_state["history"] = history
        new_state["revise_count"] = revise_count
        if revise_count > max_revise:
            new_state["status"] = "blocked"
            new_state["blocked_reason"] = "revise_iterations_exceeded"
        return new_state

    # REJECT / BLOCKED: terminal, but never silently -- the reason is always carried.
    history.append({
        "level": current_level, "decision": outcome,
        "decision_hash": decision.get("decision_hash"), "reason": decision.get("reason", ""),
    })
    new_state["history"] = history
    new_state["status"] = "rejected" if outcome == "REJECT" else "blocked"
    if outcome == "BLOCKED":
        new_state["blocked_reason"] = decision.get("reason") or "blocked"
    return new_state


def stall_verdict(state: Mapping[str, Any], k: int | None = None) -> dict[str, Any]:
    """Delegate oscillation/stall detection to `scripts/loop_journal.py`'s `analyze()` -- reused,
    never reinvented (same discipline as `feedback_recovery_agent.py`). A REVISE repeated with the
    SAME reason streaks toward STALLED exactly like a repeated journal failure."""
    if _journal_analyze is None or _journal_fingerprint is None:
        return {"verdict": "UNKNOWN", "stall_count": 0, "fingerprint": "", "recommend": "continue",
                "dead_ends": [], "reason": "scripts/loop_journal.py unavailable"}
    rows = []
    for entry in state.get("history", []):
        gate = "pass" if entry.get("decision") == "ACCEPT" else "fail"
        text = entry.get("reason") or entry.get("decision") or ""
        fp = "" if gate == "pass" else _journal_fingerprint(text)
        rows.append({"gate": gate, "fingerprint": fp, "action": entry.get("decision", "")})
    kwargs = {} if k is None else {"k": k}
    return _journal_analyze(rows, **kwargs)


# --- Minimal file persistence + the task-anchor integration point (#568 P0) ------------------

_ITEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _state_dir(repo: str = ".") -> str:
    # Same override discipline as `scripts/task_anchor.py`'s `SIMPLICIO_ANCHOR_FILE`: lets a
    # test (or an unusual install layout) redirect the state dir without touching the real repo.
    override = os.environ.get("SIMPLICIO_PROTOTYPE_STATE_DIR")
    if override:
        return override
    return os.path.join(repo, ".simplicio-loop/orchestrator", "loop", "prototype")


def state_path(work_item_id: str, repo: str = ".") -> str:
    safe = _ITEM_RE.sub("_", str(work_item_id)).strip("_") or "item"
    return os.path.join(_state_dir(repo), f"{safe}.json")


def load_state(work_item_id: str, repo: str = ".") -> dict[str, Any] | None:
    path = state_path(work_item_id, repo)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _current_source_sha(repo: str) -> str | None:
    """Read the repository revision without changing prototype state."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def save_state(state: Mapping[str, Any], repo: str = ".") -> str:
    path = state_path(state["work_item_id"], repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(dict(state), handle, ensure_ascii=False, indent=2)
    return path


def gate_status(work_item_id: str, repo: str = ".") -> dict[str, Any]:
    """The done-gate integration point: `scripts/task_anchor.py`'s `cmd_gate` calls this so a
    work item with a tracked, UNRESOLVED prototype flow blocks "done" (#568 P0 slice).

    An item with no tracked state is untouched -- ready=True, tracked=False -- so repos/items
    that never opted into the prototype flow are never blocked by its mere existence. Once a
    flow IS tracked, `ready` only flips to True on a terminal status (`resolved`, `rejected`, or
    `blocked`): a decided REJECT/BLOCKED is a real, recorded outcome the loop may act on, not an
    unresolved dangling state -- it is `in_progress` that blocks.
    """
    state = load_state(work_item_id, repo)
    if state is None:
        return {"tracked": False, "ready": True, "reason": "no prototype flow tracked for this item"}
    status = state.get("status")
    current_source_sha = _current_source_sha(repo)
    recorded_source_sha = str(state.get("source_sha") or "")
    source_drift = None if current_source_sha is None else current_source_sha != recorded_source_sha
    ready = status in {"resolved", "rejected", "blocked"}
    if ready:
        reason = "prototype flow %s at level %s" % (status, state.get("current_level"))
    elif source_drift is True:
        reason = "prototype flow source drift detected at level %s" % state.get("current_level")
    elif source_drift is None:
        reason = "prototype flow still in_progress; source drift unverified at level %s" % state.get("current_level")
    else:
        reason = "prototype flow still in_progress with source unchanged at level %s" % state.get("current_level")
    return {
        "tracked": True, "ready": ready, "status": status,
        "current_level": state.get("current_level"), "revise_count": state.get("revise_count", 0),
        "reason": reason, "recorded_source_sha": recorded_source_sha,
        "current_source_sha": current_source_sha, "source_drift": source_drift,
        "source_drift_evidence": "git-head" if current_source_sha is not None else "unavailable",
    }


__all__ = [
    "PLAN_SCHEMA", "CANDIDATE_SCHEMA", "DECISION_SCHEMA", "RECEIPT_SCHEMA", "NECESSITY_SCHEMA",
    "NOT_REQUIRED_SCHEMA", "STATE_SCHEMA", "TYPES", "LEVELS", "DEFAULT_BUDGET",
    "CANDIDATE_STATUSES", "DECISIONS", "RECEIPT_STAGES", "RISK_SIGNALS", "DEFAULT_MAX_REVISE",
    "PrototypeGateError",
    "build_plan", "validate_plan",
    "build_candidate", "validate_candidate",
    "build_decision", "validate_decision",
    "build_receipt", "validate_receipt",
    "classify_necessity", "build_not_required_receipt",
    "init_state", "apply_decision", "stall_verdict",
    "state_path", "load_state", "save_state", "gate_status",
]
