"""``simplicio-py task`` — run a task.

Extracted from `cli.py`'s `_run_task_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._shared import force_local_if_requested


def _load_task_spec(a: argparse.Namespace):
    from ..task_spec import TaskSpec, TaskSpecDocument, TaskSpecValidationError

    path = getattr(a, "task_spec", None)
    from_stdin = bool(getattr(a, "task_spec_stdin", False))
    if not path and not from_stdin:
        return None
    try:
        text = sys.stdin.read() if from_stdin else Path(str(path)).read_text(encoding="utf-8")
        payload = json.loads(text)
        if isinstance(payload, dict) and "task_id" not in payload and "tasks" in payload:
            document = TaskSpecDocument.from_dict(payload)
            if len(document.tasks) != 1:
                raise TaskSpecValidationError(
                    ["task execution requires exactly one task in the TaskSpec document"]
                )
            return document.tasks[0]
        return TaskSpec.from_dict(payload)
    except (OSError, json.JSONDecodeError, TaskSpecValidationError) as exc:
        print(f"invalid TaskSpec input: {exc}", file=sys.stderr)
        return False


def _task_arguments(a: argparse.Namespace):
    task_spec = _load_task_spec(a)
    if task_spec is False:
        return None
    if task_spec is None:
        if not a.goal or not a.target:
            print("goal and --target are required unless --task-spec is provided", file=sys.stderr)
            return None
        return a.goal, a.target, a.criteria, a.constraints, None
    narrative = task_spec.narrative
    goal = str(narrative.get("goal") or narrative.get("want") or task_spec.functionality or task_spec.task_id)
    criteria = "\n".join(
        str(item.get("text") or item.get("then") or item["id"]) for item in task_spec.acceptance_criteria
    )
    constraints = "\n".join(
        str(item.get("text") or item.get("description") or item.get("id", ""))
        for item in task_spec.business_rules
    )
    return goal, task_spec.task_id, criteria, constraints, task_spec


def run(a: argparse.Namespace) -> int:
    from ..pipeline import run_task
    from ..precedent import auto_detect_stack

    force_local_if_requested(a)
    stack = auto_detect_stack(a.root, a.stack)
    task_arguments = _task_arguments(a)
    if task_arguments is None:
        return 2
    goal, target, criteria, constraints, task_spec = task_arguments
    if a.json or a.dry_run_task:
        result = run_task(
            a.root,
            stack,
            goal,
            target,
            criteria,
            constraints,
            dry_run_task=a.dry_run_task,
            bound_paths=a.bound_paths,
            quiet=a.json,
            mode=getattr(a, "mode", None),
            task_spec=task_spec,
            context_snapshot_path=getattr(a, "context_snapshot", None),
            context_pack_path=getattr(a, "context_pack", None),
            execution_context_path=getattr(a, "execution_context", None),
            authorization_path=getattr(a, "effect_authorization", None),
            attempt_id=getattr(a, "attempt_id", None),
            lease_id=getattr(a, "lease_id", None),
            fencing_token=getattr(a, "fencing_token", None),
            context_handle=getattr(a, "context_handle", None),
            coordinator_kind=getattr(a, "coordinator_kind", None),
            coordinator_id=getattr(a, "coordinator_id", None),
        )
        if a.json:
            print(json.dumps(result, sort_keys=True))
        else:
            status = (
                "BLOCKED" if result.get("status") == "blocked" else ("DRY-RUN" if a.dry_run_task else "DONE")
            )
            print(f"{status}: {result['diff_summary']}")
            for warning in result["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
        if a.dry_run_task:
            return 1 if result.get("status") == "blocked" else 0
        return 0 if result["applied"] else 1
    result = run_task(
        a.root,
        stack,
        goal,
        target,
        criteria,
        constraints,
        bound_paths=a.bound_paths,
        mode=getattr(a, "mode", None),
        task_spec=task_spec,
        context_snapshot_path=getattr(a, "context_snapshot", None),
        context_pack_path=getattr(a, "context_pack", None),
        execution_context_path=getattr(a, "execution_context", None),
        authorization_path=getattr(a, "effect_authorization", None),
        attempt_id=getattr(a, "attempt_id", None),
        lease_id=getattr(a, "lease_id", None),
        fencing_token=getattr(a, "fencing_token", None),
        context_handle=getattr(a, "context_handle", None),
        coordinator_kind=getattr(a, "coordinator_kind", None),
        coordinator_id=getattr(a, "coordinator_id", None),
    )
    status = "DONE" if result["applied"] else "FAILED"
    print(f"{status}: {result['diff_summary']}")
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0 if result["applied"] else 1
