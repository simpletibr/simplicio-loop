"""Feature-scope orchestration for ``simplicio-py run``.

This is the first Ralph-style layer above the atomic task primitive: the
planner decomposes a goal into ordered tasks, each task runs through the
existing verify-loop, and a failing task can trigger one bounded replan.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..scratch.codegen import try_execute
from ..scratch._pipeline_adapter import run_task as run_plan_task
from ..scratch.planner import generate_plan
from ..scratch.stack_registry import StackRegistry, slugify_project
from .cost_governor import BudgetExceeded, provider_budget


TaskRunner = Callable[..., tuple[bool, str]]


def _codegen_disabled() -> bool:
    return os.environ.get("SIMPLICIO_DISABLE_CODEGEN", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _run_feature_task(task, project_dir: Path, stack, *, quiet: bool = False):
    """Run feature tasks through deterministic codegen before the LLM pipeline."""
    codegen_log = ""
    if not _codegen_disabled():
        codegen_result = try_execute(task, project_dir, stack)
        if codegen_result is not None:
            codegen_log = codegen_result.log
            if codegen_result.passed or not codegen_result.fallback_to_llm:
                mode = codegen_result.executor_name or "codegen"
                return codegen_result.passed, f"codegen:{mode}: {codegen_log}"

    passed, log = run_plan_task(task, project_dir, stack, quiet=quiet)
    if codegen_log:
        log = f"codegen fallback: {codegen_log}\n\n{log}"
    return passed, log


def _ordered_tasks(tasks: list[object]) -> list[object]:
    seen_ids: set[str] = set()
    for task in tasks:
        task_id = getattr(task, "id", "")
        if task_id in seen_ids:
            raise ValueError(f"duplicate task id in feature plan: {task_id}")
        seen_ids.add(task_id)
    pending = list(tasks)
    ordered = []
    completed: set[str] = set()
    while pending:
        ready = [
            task
            for task in pending
            if all(dep in completed for dep in getattr(task, "depends_on", []))
        ]
        if not ready:
            ids = ", ".join(getattr(task, "id", "<unknown>") for task in pending)
            raise ValueError(f"task dependency cycle or blocked dependency: {ids}")
        for task in ready:
            pending.remove(task)
            ordered.append(task)
            completed.add(getattr(task, "id", ""))
    return ordered


def run_feature(
    *,
    root: str,
    stack_slug: str,
    goal: str,
    max_iter: int = 3,
    max_cost: str | float | int | None = None,
    planner: Callable[..., object] | None = None,
    task_runner: TaskRunner | None = None,
    quiet: bool = False,
) -> dict:
    """Run a multi-task feature plan against an existing repository."""

    if max_iter < 0:
        raise ValueError("max_iter must be >= 0")
    planner_fn = planner or generate_plan
    default_task_runner = task_runner is None
    task_runner_fn = task_runner or _run_feature_task

    reg = StackRegistry()
    stack = reg.get(stack_slug)
    if stack is None:
        raise ValueError(
            f"unknown stack '{stack_slug}'. Run `simplicio-py scratch --list-stacks`."
        )

    project_name = slugify_project(goal)
    feature_goal = goal
    replans = 0
    task_results: list[dict] = []
    completed_task_ids: set[str] = set()
    last_plan = None

    with provider_budget(max_cost) as governor:
        try:
            while True:
                last_plan = planner_fn(stack, feature_goal, project_name)
                governor.refresh_from_env()
                try:
                    planned_tasks = _ordered_tasks(last_plan.tasks)
                except ValueError as exc:
                    return {
                        "scope": "feature",
                        "goal": goal,
                        "stack": stack.slug,
                        "applied": False,
                        "plan_tasks": len(last_plan.tasks),
                        "tasks": task_results,
                        "replans": replans,
                        "warnings": [str(exc)],
                        "cost": governor.report(),
                    }
                failed = None

                for task in planned_tasks:
                    if task.id in completed_task_ids:
                        continue
                    if default_task_runner:
                        passed, log = task_runner_fn(
                            task,
                            Path(root),
                            stack,
                            quiet=quiet,
                        )
                    else:
                        passed, log = task_runner_fn(task, Path(root), stack)
                    governor.refresh_from_env()
                    row = {
                        "id": task.id,
                        "goal": task.goal,
                        "target": task.target,
                        "passed": bool(passed),
                        "log": log[:1500],
                        "replan": replans,
                    }
                    task_results.append(row)
                    if not passed:
                        failed = row
                        break
                    completed_task_ids.add(task.id)

                if failed is None:
                    return {
                        "scope": "feature",
                        "goal": goal,
                        "stack": stack.slug,
                        "applied": True,
                        "plan_tasks": len(last_plan.tasks),
                        "tasks": task_results,
                        "replans": replans,
                        "warnings": [],
                        "cost": governor.report(),
                    }

                if replans >= max_iter:
                    return {
                        "scope": "feature",
                        "goal": goal,
                        "stack": stack.slug,
                        "applied": False,
                        "plan_tasks": len(last_plan.tasks),
                        "tasks": task_results,
                        "replans": replans,
                        "warnings": [
                            f"feature task {failed['id']} failed after {replans} replans"
                        ],
                        "cost": governor.report(),
                    }

                replans += 1
                feature_goal = (
                    f"{goal}\n\n[REPLAN CONTEXT]\n"
                    f"Previous plan failed at {failed['id']} targeting {failed['target']}.\n"
                    f"Failure log:\n{failed['log']}\n\n"
                    "Return a revised plan for the remaining feature work."
                )
        except BudgetExceeded as exc:
            governor.refresh_from_env()
            return {
                "scope": "feature",
                "goal": goal,
                "stack": stack.slug,
                "applied": False,
                "plan_tasks": len(last_plan.tasks) if last_plan else 0,
                "tasks": task_results,
                "replans": replans,
                "warnings": [str(exc)],
                "cost": governor.report(),
            }
