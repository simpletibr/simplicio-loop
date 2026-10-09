"""capability_rank (plan): which skill fits the subtask, from the Prism route (simplicio_loop.route, no new ranker).

The route gives the intent and the skills to load; the skill that owns the intent goes first, the rest keep the
route's order. squad_routing (PR #1507) is not on main yet, so the Prism route is the single source.
"""
from ... import route
from .registry import PointContext, PointResult, register

NAME = "capability_rank"
_PRIMARY = {"mutate": "simplicio-dev-cli", "validate": "simplicio-dev-cli", "orchestrate": "simplicio-loop",
            "retrieve": "simplicio-mapper", "survey": "simplicio-mapper"}


def rank(task: str) -> dict:
    decided = route.route(task)
    skills = list(decided["skills_to_load"])
    primary = _PRIMARY.get(decided["intent"])
    if primary in skills:
        skills.remove(primary)
        skills.insert(0, primary)
    return {"intent": decided["intent"], "skills": skills, "top": skills[0] if skills else None,
            "route_id": decided["route_id"]}


def applies(ctx: PointContext) -> bool:
    return bool(ctx.task_text)


async def capability_rank(ctx: PointContext) -> PointResult:
    return PointResult(NAME, "ok", rank(ctx.task_text))


register(NAME, "plan", capability_rank, applies=applies)
