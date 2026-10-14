"""Convergence decision of the watcher: continue, retry, escalate or stop, from control_policy.decide.

A plain module, not a point: host_mode (the failed-verify path) and the `convergence_policy` point both use it, and
host_mode must not import `points`, whose modules may fail to import without taking the tick down.
"""
from .. import control_policy, escalation

_ACTION = {"REPLAN": "retry", "ESCALATE": "escalate", "STOP_BLOCKED": "stop", "STOP_BUDGET": "stop",
           "STOP_UNSAFE": "stop"}  # every other decision (CONTINUE_*, OBSERVE_WAIT, STOP_SUCCESS) is continue


def action_for(decision: str, *, verifier_failed: bool) -> str:
    action = _ACTION.get(decision, "continue")
    return "retry" if action == "continue" and verifier_failed else action


def _snapshot(failed: bool) -> dict:
    return {"acs_open": int(failed), "verifiers_failed": int(failed)}


def assess(ladder: escalation.EscalationState, *, failed: bool, unverified: bool = False) -> dict:
    """The decision for the attempts in `ladder` (the last one is the current): {action, decision, reason, ...}.

    The one place the RunProjection is built. Two consumers read it: the failed-verify path of host mode (its ladder
    is already loaded; `stop` ends the escalation, `escalate` climbs a role) and the verify point (evidence).
    """
    records = ladder.records
    failed_attempts = sum(1 for r in records if r.outcome != "ok")
    projection = {
        **_snapshot(failed),
        "effects_unverified": int(unverified),
        "history": [_snapshot(r.outcome != "ok") for r in records],
        # a verified result is never refused for the cost of the attempts behind it
        "hard_constraints": {"within_budget": not failed or (
            ladder.can_escalate() and failed_attempts < ladder.attempt_ceiling_per_issue)},
    }
    decision = control_policy.decide(projection)
    return {"decision": decision["decision"], "action": action_for(decision["decision"], verifier_failed=failed),
            "reason": decision["reason_code"], "v_t": decision.get("v_t"), "attempts": len(records),
            "failed_attempts": failed_attempts, "weights_version": decision["weights_version"]}
