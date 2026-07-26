"""``simplicio-py task`` — run a task.

Extracted from `cli.py`'s `_run_task_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ._shared import force_local_if_requested


def _run_verification_only(a: argparse.Namespace) -> int:
    from ..pipeline_stages import _configured_test_command, _verification_timeout_seconds
    from ..runtime_env import prepare_project_command

    command, configuration_error = _configured_test_command()
    if configuration_error:
        payload = {
            "schema": "simplicio.dev-cli.verification-only/v1",
            "status": "blocked",
            "applied": False,
            "files_changed": [],
            "model_invoked": False,
            "blocked_preconditions": [
                {
                    "code": "verification_command_missing",
                    "message": configuration_error,
                    "retryable": True,
                    "next_action": (
                        "set SIMPLICIO_TEST_CMD to a real project verification command, then retry"
                    ),
                }
            ],
        }
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"BLOCKED: {configuration_error}", file=sys.stderr)
        return 1

    assert command is not None
    cmd, use_shell = prepare_project_command(a.root, command)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            shell=use_shell,
            cwd=a.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_verification_timeout_seconds(),
            check=False,
        )
        exit_code = completed.returncode
        stdout_tail = completed.stdout[-2000:]
        stderr_tail = completed.stderr[-2000:]
        reason_code = "verification_passed" if exit_code == 0 else "verification_failed"
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout_tail = str(exc.stdout or "")[-2000:]
        stderr_tail = str(exc.stderr or "")[-2000:]
        reason_code = "verification_timeout"
    payload = {
        "schema": "simplicio.dev-cli.verification-only/v1",
        "status": "verified" if exit_code == 0 else "failed",
        "reason_code": reason_code,
        "applied": False,
        "files_changed": [],
        "model_invoked": False,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "verify": {
            "command": command,
            "exit_code": exit_code,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        },
    }
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("VERIFIED" if exit_code == 0 else f"FAILED: {reason_code}")
    return 0 if exit_code == 0 else 1


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

    if getattr(a, "verify_only", False):
        return _run_verification_only(a)
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
