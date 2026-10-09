"""convergence_policy (verify): continue, retry, escalate or stop, from control_policy.decide (RunProjection -> LoopDecision).

The attempt history is the escalation state the exec executor already keeps in the clone. The decision that CHANGES
the run is made on the failed-verify path (host_mode.run_exec calls `assess` after a failed attempt: stop ends the
escalation, escalate climbs a role, retry keeps the role order); the tick never reaches the verify stage on a failed
verify. The point itself is observational: it records the decision of the verified run in the evidence.
"""
import asyncio

from ... import control_policy, escalation
from .registry import PointContext, PointResult, register

NAME = "convergence_policy"
_ACTION = {"REPLAN": "retry", "ESCALATE": "escalate", "STOP_BLOCKED": "stop", "STOP_BUDGET": "stop",
           "STOP_UNSAFE": "stop"}  # every other decision (CONTINUE_*, OBSERVE_WAIT, STOP_SUCCESS) is continue


def applies(ctx: PointContext) -> bool:
    return ctx.clone is not None and (ctx.issue or {}).get("number") is not None


def action_for(decision: str, *, verifier_failed: bool) -> str:
    action = _ACTION.get(decision, "continue")
    return "retry" if action == "continue" and verifier_failed else action


def _snapshot(failed: bool) -> dict:
    return {"acs_open": int(failed), "verifiers_failed": int(failed)}


def assess(ladder: escalation.EscalationState, *, failed: bool, unverified: bool = False) -> dict:
    """The decision for the attempts in `ladder` (the last one is the current): {action, decision, reason, ...}.

    The one place the RunProjection is built. Two consumers read it: the failed-verify path of host mode (its ladder
    is already loaded; `stop` ends the escalation, `escalate` climbs a role) and the verify point below (evidence).
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


def _decide(ctx: PointContext) -> PointResult:
    ladder = escalation.load_escalation_state(ctx.clone, int(ctx.issue["number"]), ctx.family or "")
    verdict = assess(ladder, failed=bool(ctx.verify and ctx.verify.startswith("MEASURED|verify_failed")),
                     unverified=bool(ctx.verify and ctx.verify.startswith("UNVERIFIED")))
    if verdict["action"] == "stop":
        return PointResult(NAME, "blocked", verdict, verdict["reason"])
    return PointResult(NAME, "ok", verdict)


async def convergence(ctx: PointContext) -> PointResult:
    return await asyncio.to_thread(_decide, ctx)


register(NAME, "verify", convergence, applies=applies)
