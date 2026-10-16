"""Task dependency ordering for the runner dispatch (#1818 split of runner_core).

Functions moved verbatim from `simplicio_loop/runner_core.py` (#1818).
`runner_core` re-exports them, so import paths and patch targets on `runner_core` keep working.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Collection, Dict, Iterable, Mapping, Sequence


def _normalize_dependency_reference(item: Any) -> str:
    """Reduce a dependency as an LLM writes it ("Depends on: task 1 (x.html)")
    to the runner's own alias ("task-1"); ids and titles pass through."""
    text = _DEPENDENCY_PREFIX_RE.sub("", str(item)).strip().lstrip("-* ")
    text = _DEPENDENCY_NOTE_RE.sub("", text).strip()
    number = _TASK_NUMBER_RE.match(text)
    return f"task-{number.group(1)}" if number else text


def _dependency_references(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        value = value.get("items") or value.get("depends_on") or ()
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple, set)):
        return []
    references = (_normalize_dependency_reference(item) for item in value)
    return [reference for reference in references if reference]


def _task_dependency_references(task: Mapping[str, Any], step: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    values: list[str] = []
    for source in (task, step or {}):
        raw = source.get("depends_on") or source.get("dependencies") or ()
        values.extend(_dependency_references(raw))
    return tuple(dict.fromkeys(values))


def _task_aliases(task: Mapping[str, Any], index: int, run_id: str) -> set[str]:
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    return {
        str(value).strip()
        for value in (
            task.get("id"), identity.get("id"), identity.get("system"), identity.get("title"),
            index, f"task-{index}", f"{run_id}-task-{index}",
        )
        if str(value).strip()
    }


def _assert_task_dependencies_ready(
    run_dir: Path,
    tasks: Sequence[Mapping[str, Any]],
    task_index: int,
    run_id: str,
    *,
    step: Mapping[str, Any] | None = None,
    in_batch: Collection[int] = (),
) -> None:
    """Reject a tick that arrives before every declared predecessor completed.

    A predecessor dispatched in the same batch (``in_batch``) is ordered by
    the batch's shared serial run, so it has no result marker yet."""
    aliases: dict[str, int] = {
        alias: index
        for index, task in enumerate(tasks, start=1)
        for alias in _task_aliases(task, index, run_id)
    }
    references = _task_dependency_references(tasks[task_index - 1], step)
    for reference in references:
        dependency_index = aliases.get(reference)
        if dependency_index is None:
            raise RuntimeError(
                f"task dependency is not part of the run: task {task_index}->{reference}"
            )
        if dependency_index == task_index:
            raise RuntimeError(f"task cannot depend on itself: task {task_index}")
        if dependency_index in in_batch:
            continue
        marker = run_dir / f"task-{dependency_index}-result.json"
        if not marker.is_file():
            raise RuntimeError(
                f"task dependency is not completed: task {task_index} requires task {dependency_index}"
            )
        try:
            result = _load_json(marker)
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"task dependency result is unreadable: task {dependency_index}"
            ) from exc
        if result.get("status") not in {"applied", "no_change", "succeeded", "completed"}:
            raise RuntimeError(
                f"task dependency did not complete successfully: task {dependency_index}"
            )


def _item_dependencies(item: Mapping[str, Any]) -> tuple[str, ...]:
    raw_spec = item.get("task_spec")
    spec: Mapping[str, Any] = raw_spec if isinstance(raw_spec, Mapping) else {}
    raw = spec.get("depends_on") or spec.get("dependencies") or item.get("depends_on") or ()
    return tuple(dict.fromkeys(_dependency_references(raw)))


def _completed_task_aliases(
    run_dir: Path,
    tasks: Sequence[Mapping[str, Any]],
    run_id: str,
) -> set[str]:
    """Aliases of tasks that already finished successfully in this run."""
    aliases: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        marker = run_dir / f"task-{index}-result.json"
        if not marker.is_file():
            continue
        try:
            result = _load_json(marker)
        except (OSError, TypeError, ValueError):
            continue
        if result.get("status") not in {"applied", "no_change", "succeeded", "completed"}:
            continue
        aliases.update(_task_aliases(task, index, run_id))
    return aliases


def _omit_satisfied_dispatch_dependencies(
    items: Iterable[Mapping[str, Any]],
    *,
    satisfied_aliases: Collection[str] = (),
) -> list[Dict[str, Any]]:
    """Drop DAG edges whose predecessor already completed outside this batch."""
    satisfied = {str(alias).strip() for alias in satisfied_aliases if str(alias).strip()}
    filtered: list[Dict[str, Any]] = []
    for item in items:
        row = dict(item)
        spec = dict(row["task_spec"]) if isinstance(row.get("task_spec"), Mapping) else {}
        remaining = [dependency for dependency in _item_dependencies({"task_spec": spec, **row}) if dependency not in satisfied]
        spec["depends_on"] = remaining
        row["task_spec"] = spec
        filtered.append(row)
    return filtered


def _ordered_dispatch_items(items: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    """Return a stable topological order and fail closed on unknown/cyclic edges."""
    rows = [dict(item) for item in items]
    by_id: dict[str, Dict[str, Any]] = {}
    by_index: dict[str, Dict[str, Any]] = {}
    for row in rows:
        task_id = str(row.get("task_id") or "").strip()
        if not task_id or task_id in by_id:
            raise ValueError("operator dispatch task ids must be unique and non-empty")
        by_id[task_id] = row
        if row.get("task_index") is not None:
            by_index[str(row["task_index"])] = row
    dependencies: dict[str, set[str]] = {}
    for row in rows:
        task_id = str(row["task_id"])
        resolved: set[str] = set()
        for dependency in _item_dependencies(row):
            candidate = by_id.get(dependency) or by_index.get(dependency.removeprefix("task-"))
            if candidate is None:
                raise ValueError(f"operator dispatch dependency is not in the batch: {task_id}->{dependency}")
            dependency_id = str(candidate["task_id"])
            if dependency_id == task_id:
                raise ValueError(f"operator dispatch task cannot depend on itself: {task_id}")
            resolved.add(dependency_id)
        dependencies[task_id] = resolved
    order = {str(row["task_id"]): index for index, row in enumerate(rows)}
    ready = [
        str(row["task_id"])
        for row in rows
        if not dependencies[str(row["task_id"])]
    ]
    ready.sort(key=order.__getitem__)
    result: list[Dict[str, Any]] = []
    while ready:
        task_id = ready.pop(0)
        result.append(by_id[task_id])
        for candidate in rows:
            candidate_id = str(candidate["task_id"])
            if task_id in dependencies[candidate_id]:
                dependencies[candidate_id].remove(task_id)
                if not dependencies[candidate_id] and candidate_id not in {str(row["task_id"]) for row in result}:
                    ready.append(candidate_id)
        ready.sort(key=order.__getitem__)
    if len(result) != len(rows):
        unresolved = sorted(task_id for task_id, deps in dependencies.items() if deps)
        raise ValueError("operator dispatch dependency cycle: " + ", ".join(unresolved))
    return result

from .runner_core import (_TASK_NUMBER_RE, _DEPENDENCY_NOTE_RE, _DEPENDENCY_PREFIX_RE, _load_json)  # noqa: E402
