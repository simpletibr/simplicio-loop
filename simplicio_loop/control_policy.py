"""Pure convergence policy: RunProjection -> LoopDecision.

The Loop is a control policy, not a second control plane. This module takes an
immutable snapshot of run state (a ``RunProjection``) and returns a
``LoopDecision`` — it never touches a file, a queue, a lease, or a subprocess.
The Runtime remains the sole owner of queue/lease/attempt-budget/effects; this
module only recommends CONTINUE_SERIAL / CONTINUE_PARALLEL / OBSERVE_WAIT /
REPLAN / ESCALATE / STOP_SUCCESS / STOP_BLOCKED / STOP_BUDGET / STOP_UNSAFE.

V(t) is an observable Lyapunov-style drift candidate, not a physical metaphor:

    V = a*acs_open + b*verifiers_failed + c*effects_unverified + d*backlog + e*retry_amplification

Weights are published and versioned (``PolicyWeights``/``WEIGHTS_VERSION``) so
they can be calibrated against a corpus without changing this module's shape.
Safety/authority/privacy/budget are hard constraints, checked before V(t) is
even considered — they are never weights that a big enough score can outrun.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

from .technical_debt import is_hard_blocker, is_non_blocking_reason
from .recovery_policy import recovery_stage

SCHEMA = "simplicio.control-policy/v1"
WEIGHTS_VERSION = "v1"

DECISIONS = (
    "CONTINUE_SERIAL", "CONTINUE_PARALLEL", "OBSERVE_WAIT", "REPLAN",
    "ESCALATE", "STOP_SUCCESS", "STOP_BLOCKED", "STOP_BUDGET", "STOP_UNSAFE",
)
DRIFT_STATES = ("PROGRESS", "STALL", "OSCILLATION")


@dataclass(frozen=True)
class PolicyWeights:
    a: float = 1.0  # acs_open
    b: float = 1.0  # verifiers_failed
    c: float = 1.0  # effects_unverified
    d: float = 0.25  # backlog
    e: float = 1.0  # retry_amplification


DEFAULT_WEIGHTS = PolicyWeights()


def _result(decision: str, reason_code: str, reason: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "tag": "MEASURED",
        "weights_version": WEIGHTS_VERSION,
    }
    out.update(extra)
    return out


def _technical_debts(projection: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = projection.get("technical_debts", projection.get("technical_debt")) or []
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [
        dict(item) for item in raw
        if isinstance(item, Mapping) and item.get("blocking") is not True
    ]


def _attach_debt(result: Dict[str, Any], debts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if debts:
        result.update({
            "degraded": True,
            "technical_debt_count": len(debts),
            "technical_debts": [dict(item) for item in debts],
        })
    return result


def compute_v(projection: Mapping[str, Any], weights: PolicyWeights = DEFAULT_WEIGHTS) -> float:
    """Compute the observable drift candidate V(t) for one projection snapshot."""
    return (
        weights.a * float(projection.get("acs_open") or 0)
        + weights.b * float(projection.get("verifiers_failed") or 0)
        + weights.c * float(projection.get("effects_unverified") or 0)
        + weights.d * float(projection.get("backlog") or 0)
        + weights.e * float(projection.get("retry_amplification") or 0)
    )


def _state_signature(entry: Mapping[str, Any], weights: PolicyWeights) -> str:
    supplied = str(entry.get("state_signature") or "").strip()
    if supplied:
        return supplied
    return f"{compute_v(entry, weights):.6f}"


def classify_drift(
    history: Sequence[Mapping[str, Any]], current: Mapping[str, Any], *,
    weights: PolicyWeights = DEFAULT_WEIGHTS, stall_threshold: int = 3,
) -> Dict[str, Any]:
    """Classify V(t) drift as PROGRESS, STALL, or OSCILLATION.

    ``history`` is ordered oldest to newest and excludes ``current``.  A
    negative delta against the immediately preceding tick is PROGRESS. A
    repeating state signature held for at least ``stall_threshold``
    consecutive ticks (including ``current``) is a flat STALL. A period-2..4
    cycle of signatures reappearing across the trailing window is OSCILLATION
    — the plain fingerprint-repeat check used elsewhere in this repo never
    catches this, only exact flat repeats.
    """
    rows = [dict(row) for row in history if isinstance(row, Mapping)]
    signatures = [_state_signature(row, weights) for row in rows]
    current_sig = _state_signature(current, weights)
    v_t = compute_v(current, weights)
    previous_v = compute_v(rows[-1], weights) if rows else None
    delta_v = (v_t - previous_v) if previous_v is not None else 0.0

    trail = signatures + [current_sig]
    for period in (2, 3, 4):
        if len(trail) < period * 2:
            continue
        window = trail[-period * 2:]
        if window[:period] == window[period:] and len(set(window[:period])) > 1:
            return {"state": "OSCILLATION", "v_t": v_t, "delta_v": delta_v,
                    "repeat_count": period, "state_signature": current_sig}

    repeat = 0
    for sig in reversed(trail):
        if sig != current_sig:
            break
        repeat += 1
    if delta_v < 0 and repeat < stall_threshold:
        return {"state": "PROGRESS", "v_t": v_t, "delta_v": delta_v,
                "repeat_count": repeat, "state_signature": current_sig}
    if repeat >= stall_threshold:
        return {"state": "STALL", "v_t": v_t, "delta_v": delta_v,
                "repeat_count": repeat, "state_signature": current_sig}
    return {"state": "PROGRESS", "v_t": v_t, "delta_v": delta_v,
            "repeat_count": repeat, "state_signature": current_sig}


def _conflicts(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    a_writes = set(a.get("writes") or ())
    b_writes = set(b.get("writes") or ())
    b_touched = set(b.get("reads") or ()) | b_writes
    a_touched = set(a.get("reads") or ()) | a_writes
    return bool(a_writes & b_touched) or bool(b_writes & a_touched)


def group_candidates(
    candidates: Sequence[Mapping[str, Any]], capacity_signal: Mapping[str, Any] | None = None,
    *, prior_group_size: int = 1,
) -> Dict[str, Any]:
    """Group conflict-free candidates and recommend a group-size cap (simple AIMD).

    Two candidates conflict when one's write set intersects the other's
    read-or-write set. Groups are built with a greedy pass over ``candidates``
    in the given order (deterministic for a fixed input order). A rising
    capacity signal caps the group size (multiplicative decrease to 1); an
    otherwise calm signal allows the cap to grow by one (additive increase),
    never to a fixed universal worker count.
    """
    items = [dict(item) for item in candidates if isinstance(item, Mapping)]
    signal = dict(capacity_signal or {})
    rising = any(bool(signal.get(key)) for key in
                 ("errors_rising", "queue_rising", "memory_rising", "io_rising"))
    max_group_size = 1 if rising else max(1, int(prior_group_size) + 1)

    groups: List[List[str]] = []
    for item in items:
        placed = False
        for group in groups:
            if len(group) >= max_group_size:
                continue
            group_items = [i for i in items if i["id"] in group]
            if any(_conflicts(item, other) for other in group_items):
                continue
            group.append(item["id"])
            placed = True
            break
        if not placed:
            groups.append([item["id"]])

    serial = all(len(group) == 1 for group in groups)
    return {
        "groups": groups,
        "recommended_concurrency": max((len(g) for g in groups), default=1),
        "serial": serial or not items,
    }


def decide(
    projection: Mapping[str, Any], *, weights: PolicyWeights = DEFAULT_WEIGHTS,
    stall_threshold: int = 3, cooldown: int = 2,
) -> Dict[str, Any]:
    """Evaluate one RunProjection tick and return a LoopDecision.

    Hard constraints are checked first and are never traded off against V(t):
    a failed safety/authority/privacy gate always yields STOP_UNSAFE, and an
    exhausted budget always yields STOP_BUDGET, regardless of drift state.
    """
    hard = dict(projection.get("hard_constraints") or {})
    if not (hard.get("safe", True) and hard.get("authorized", True) and hard.get("privacy_ok", True)):
        return _result("STOP_UNSAFE", "hard_constraint_violation",
                       "a safety, authority, or privacy constraint failed")
    if not hard.get("within_budget", True):
        return _result("STOP_BUDGET", "budget_exhausted", "the run is out of budget")

    maintenance = dict(projection.get("maintenance") or {})
    if (maintenance.get("mode") == "maintenance_deferred"
            or maintenance.get("disposition") == "backlog_only"):
        return _result(
            "STOP_BLOCKED",
            "maintenance_deferred",
            "maintenance-deferred backlog-only mode blocks operator progress",
        )

    debts = _technical_debts(projection)
    acs_open = int(projection.get("acs_open") or 0)
    verifiers_failed = int(projection.get("verifiers_failed") or 0)
    effects_unverified = int(projection.get("effects_unverified") or 0)
    if acs_open == 0 and verifiers_failed == 0 and effects_unverified == 0:
        return _attach_debt(_result("STOP_SUCCESS", "verified", "all acceptance criteria are done and verified",
                       v_t=compute_v(projection, weights), delta_v=0.0), debts)

    blocker_reason = str(projection.get("blocked_reason") or "").strip()
    if bool(projection.get("blocked")) or blocker_reason:
        blocker_type = str(projection.get("blocker_type") or "").strip().lower()
        if blocker_type:
            recovery = recovery_stage(
                blocker_type,
                attempts=int(projection.get("recovery_attempts") or 0),
                max_attempts=int(projection.get("recovery_max_attempts") or 2),
            )
            if recovery["status"] == "CONTINUE":
                return _attach_debt(_result(
                    "CONTINUE_SERIAL", "recovery_pending",
                    "a recoverable blocker requires bounded safe recovery before handoff",
                    recovery=recovery, v_t=compute_v(projection, weights), delta_v=0.0,
                ), debts)
            if recovery["status"] == "BLOCKED" and not blocker_reason:
                blocker_reason = str(recovery.get("reason_code") or "")
        if debts and (not blocker_reason or (
                is_non_blocking_reason(blocker_reason) and not is_hard_blocker(blocker_reason))):
            return _attach_debt(_result(
                "CONTINUE_SERIAL", "technical_debt_notified",
                "a non-critical degradation was recorded; continue with reduced capability",
                v_t=compute_v(projection, weights), delta_v=0.0,
            ), debts)
        return _result("STOP_BLOCKED", blocker_reason or "external_dependency_blocked",
                       "an external dependency blocks progress; no drift is possible",
                       v_t=compute_v(projection, weights), delta_v=0.0)

    history = projection.get("history") or []
    drift = classify_drift(history, projection, weights=weights, stall_threshold=stall_threshold)
    v_t, delta_v = drift["v_t"], drift["delta_v"]

    if drift["state"] in ("STALL", "OSCILLATION"):
        past_cooldown = drift["repeat_count"] >= cooldown
        if not past_cooldown:
            return _attach_debt(_result("OBSERVE_WAIT", "hysteresis_hold",
                           "drift signal is not yet past the hysteresis cooldown",
                           v_t=v_t, delta_v=delta_v, drift_state=drift["state"]), debts)
        if drift["state"] == "OSCILLATION":
            return _attach_debt(_result("ESCALATE", "oscillation_detected",
                           "V(t) is cycling instead of converging",
                           v_t=v_t, delta_v=delta_v, drift_state=drift["state"]), debts)
        return _attach_debt(_result("REPLAN", "stall_escalation",
                       "V(t) has plateaued past the stall threshold",
                       v_t=v_t, delta_v=delta_v, drift_state=drift["state"]), debts)

    grouping = group_candidates(projection.get("candidates") or (), projection.get("capacity_signal"))
    if grouping["serial"]:
        return _attach_debt(_result("CONTINUE_SERIAL", "no_conflict_free_parallelism",
                       "no conflict-free group larger than one candidate",
                       v_t=v_t, delta_v=delta_v, drift_state=drift["state"], **grouping), debts)
    return _attach_debt(_result("CONTINUE_PARALLEL", "conflict_free_groups",
                   "conflict-free candidate groups can run concurrently",
                   v_t=v_t, delta_v=delta_v, drift_state=drift["state"], **grouping), debts)


__all__ = [
    "DECISIONS", "DEFAULT_WEIGHTS", "DRIFT_STATES", "PolicyWeights", "SCHEMA",
    "WEIGHTS_VERSION", "classify_drift", "compute_v", "decide", "group_candidates",
]
