"""convergence_policy (verify): records the convergence decision (continue, retry, escalate or stop) in the evidence.

The decision comes from `watcher247.convergence.assess` (control_policy.decide over the escalation history of the
clone). The decision that CHANGES the run is made on the failed-verify path (host_mode.run_exec calls `assess` after
a failed attempt: stop ends the escalation, escalate climbs a role, retry keeps the role order); the tick never
reaches the verify stage on a failed verify. This point is observational: it records the decision of the verified
run, and returns `blocked` on stop.
"""
import asyncio

from ... import escalation
from .. import convergence
from .registry import PointContext, PointResult, register

NAME = "convergence_policy"


def applies(ctx: PointContext) -> bool:
    return ctx.clone is not None and (ctx.issue or {}).get("number") is not None


def _decide(ctx: PointContext) -> PointResult:
    ladder = escalation.load_escalation_state(ctx.clone, int(ctx.issue["number"]), ctx.family or "")
    verdict = convergence.assess(ladder, failed=bool(ctx.verify and ctx.verify.startswith("MEASURED|verify_failed")),
                                 unverified=bool(ctx.verify and ctx.verify.startswith("UNVERIFIED")))
    if verdict["action"] == "stop":
        return PointResult(NAME, "blocked", verdict, verdict["reason"])
    return PointResult(NAME, "ok", verdict)


async def convergence_point(ctx: PointContext) -> PointResult:
    return await asyncio.to_thread(_decide, ctx)


register(NAME, "verify", convergence_point, applies=applies)
