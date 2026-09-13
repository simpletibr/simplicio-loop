"""Offline, deterministic task-batch planning for zero-target handoffs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from .task_context import select_context_targets
from .task_intent import canonical_json, parse_task_intent

TASK_BATCH_SCHEMA = "simplicio.task-batch/v1"


def _stable_id(raw: Any, index: int, fingerprint: str) -> str:
    value = str(raw or "").strip()
    if value:
        return value
    return f"task-{index:03d}-{fingerprint[:8]}"


def _task_input(item: Any) -> tuple[str, Mapping[str, Any] | str, list[str], dict[str, Any]]:
    if isinstance(item, Mapping):
        raw = item.get("task", item.get("intent", item))
        depends = item.get("depends_on", [])
        if not isinstance(depends, list):
            depends = [depends]
        metadata = item.get("metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        return (
            str(item.get("id") or ""),
            raw,
            [str(value) for value in depends if str(value).strip()],
            dict(metadata),
        )
    return "", item, [], {}


def _topological_order(tasks: list[dict[str, Any]]) -> list[str]:
    ids = {task["id"] for task in tasks}
    indegree = {task["id"]: 0 for task in tasks}
    outgoing = {task["id"]: [] for task in tasks}
    for task in tasks:
        for dependency in task["depends_on"]:
            if dependency not in ids:
                raise ValueError(f"unknown task dependency: {dependency}")
            indegree[task["id"]] += 1
            outgoing[dependency].append(task["id"])
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in sorted(outgoing[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(ordered) != len(tasks):
        raise ValueError("task batch contains a dependency cycle")
    return ordered


def build_task_batch(
    root: str,
    raw_tasks: Sequence[Any] | Mapping[str, Any],
    project_map: Mapping[str, Any],
    *,
    confidence_threshold: float = 0.2,
    minimum_margin: float = 0.1,
) -> dict[str, Any]:
    """Create a plan envelope; never edits, invokes an LLM, or executes a task."""
    items = raw_tasks.get("tasks", []) if isinstance(raw_tasks, Mapping) else raw_tasks
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or not items:
        raise ValueError("task batch must contain at least one task")
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        supplied_id, raw, depends_on, metadata = _task_input(item)
        intent = parse_task_intent(raw)
        task_id = _stable_id(supplied_id, index, intent["fingerprint"])
        selection = select_context_targets(
            root,
            project_map,
            goal=intent.get("functionality", ""),
            task_intent=intent,
            task_fingerprint=intent["fingerprint"],
        )
        candidates = selection["targets"]
        top = float(candidates[0]["relevance_score"]) if candidates else 0.0
        second = float(candidates[1]["relevance_score"]) if len(candidates) > 1 else 0.0
        margin = top - second
        if not candidates:
            resolution = "abstained"
        elif top < confidence_threshold or (len(candidates) > 1 and margin < minimum_margin):
            resolution = "ambiguous"
        else:
            resolution = "selected"
        tasks.append(
            {
                "id": task_id,
                "source_index": index,
                "intent": intent,
                "depends_on": sorted(set(depends_on)),
                "metadata": metadata,
                "candidates": candidates,
                "selection": {
                    "status": resolution,
                    "top_score": round(top, 6),
                    "margin": round(margin, 6),
                    "confidence_threshold": confidence_threshold,
                    "minimum_margin": minimum_margin,
                    "query_fingerprint": selection["query_fingerprint"],
                },
            }
        )
    order = _topological_order(tasks)
    paths: dict[str, list[str]] = {}
    for task in tasks:
        for candidate in task["candidates"]:
            paths.setdefault(candidate["path"], []).append(task["id"])
    shared = [
        {"path": path, "task_ids": sorted(task_ids), "reason": "shared_candidate_surface"}
        for path, task_ids in sorted(paths.items())
        if len(task_ids) > 1
    ]
    conflicts = [
        {"task_ids": surface["task_ids"], "paths": [surface["path"]], "reason": surface["reason"]}
        for surface in shared
    ]
    batch_id = hashlib.sha256(canonical_json({"tasks": tasks, "order": order}).encode()).hexdigest()
    return {
        "schema": TASK_BATCH_SCHEMA,
        "batch_id": batch_id,
        "tasks": tasks,
        "order": order,
        "shared_surfaces": shared,
        "conflicts": conflicts,
        "execution": {"mode": "plan-only", "executed": False},
    }


__all__ = ["TASK_BATCH_SCHEMA", "build_task_batch"]
