"""convergence_policy (verify): continue, retry, escalate or stop, from control_policy.decide (RunProjection -> LoopDecision).

The attempt history is the escalation state the exec executor already keeps in the clone; the current verification is
the verify label of the run. A `stop` decision returns `blocked`; the decision always goes to the evidence.
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


def _decide(ctx: PointContext) -> PointResult:
    ladder = escalation.load_escalation_state(ctx.clone, int(ctx.issue["number"]), ctx.family or "")
    records = ladder.records
    failed_attempts = sum(1 for r in records if r.outcome != "ok")
    verifier_failed = bool(ctx.verify and ctx.verify.startswith("MEASURED|verify_failed"))
    projection = {
        **_snapshot(verifier_failed),
        "effects_unverified": int(bool(ctx.verify and ctx.verify.startswith("UNVERIFIED"))),
        "history": [_snapshot(r.outcome != "ok") for r in records],
        # a verified result is never refused for the cost of the attempts behind it
        "hard_constraints": {"within_budget": not verifier_failed or (
            ladder.can_escalate() and failed_attempts < ladder.attempt_ceiling_per_issue)},
    }
    decision = control_policy.decide(projection)
    action = action_for(decision["decision"], verifier_failed=verifier_failed)
    evidence = {"decision": decision["decision"], "action": action, "reason": decision["reason_code"],
                "v_t": decision.get("v_t"), "attempts": len(records), "failed_attempts": failed_attempts,
                "weights_version": decision["weights_version"]}
    if action == "stop":
        return PointResult(NAME, "blocked", evidence, decision["reason_code"])
    return PointResult(NAME, "ok", evidence)


async def convergence(ctx: PointContext) -> PointResult:
    return await asyncio.to_thread(_decide, ctx)


register(NAME, "verify", convergence, applies=applies)
