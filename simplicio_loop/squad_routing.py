"""Route the FIRST worker of a task by complexity (#1504, part of #1502).

Deterministic: no model call, no I/O. The result is a role from ``model_roles``
(``execution`` or ``coordination``); the escalation ladder still applies after it.

A task is ``execution`` only when ALL hold: exactly one module, no integration with
existing modules, no shared file, not security. Anything else is ``coordination``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

EXECUTION = "execution"
COORDINATION = "coordination"
SECURITY_LABELS = frozenset({"security", "area:security", "type:security"})


@dataclass(frozen=True)
class RouteDecision:
    role: str
    reasons: tuple[str, ...]

    def explain(self) -> str:
        return f"{self.role}: " + "; ".join(self.reasons)


def _modules(task: Mapping[str, Any]) -> list[str]:
    modules = task.get("modules")
    if modules:
        return sorted({str(m) for m in modules})
    # No explicit modules: the module of a file is its top-level directory.
    return sorted({str(f).strip("/").split("/")[0] for f in task.get("files") or []})


def route(task: Mapping[str, Any]) -> RouteDecision:
    """Keys: ``files``, ``modules``, ``integrates`` (existing modules), ``touches_shared``, ``security``, ``labels``."""
    reasons: list[str] = []
    modules = _modules(task)
    if len(modules) > 1:
        reasons.append(f"touches {len(modules)} modules")
    if task.get("integrates"):
        reasons.append("integrates existing modules: " + ", ".join(sorted(map(str, task["integrates"]))))
    if task.get("touches_shared"):
        reasons.append("touches a shared file")
    if task.get("security") or SECURITY_LABELS & {str(label).lower() for label in task.get("labels") or []}:
        reasons.append("security-sensitive")
    if reasons:
        return RouteDecision(COORDINATION, tuple(reasons))
    return RouteDecision(EXECUTION, ("single module, no integration, not shared, not security",))
