"""Compute the benchmark verdict text purely from `results` data.

No hardcoded figures: every number in the returned string is read straight
out of the `results` dict handed in, so the text always matches whatever the
last real run actually measured.
"""
from __future__ import annotations


def compute_verdict(results: dict) -> str:
    arms = results.get("arms") or {}
    lines: list[str] = []
    for arm_name, data in arms.items():
        tasks = data.get("tasks") or []
        n_tasks = len(tasks)
        n_success = sum(1 for t in tasks if t.get("success"))
        wall = data.get("total_wall_s")
        wall_s = f"{wall:.1f}s" if isinstance(wall, (int, float)) else "n/d"
        cost = 0.0
        for task in tasks:
            for attempt in task.get("attempts", []):
                call = attempt.get("llm_call") or {}
                cost += call.get("cost_usd") or 0
        lines.append(f"{arm_name}: {n_success}/{n_tasks} tarefas, {wall_s}, US$ {cost:.5f}")
    if not lines:
        return "sem dados suficientes para veredito"
    return " | ".join(lines)
