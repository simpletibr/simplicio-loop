"""``simplicio-py task`` — verify-only, or fail closed without an edit plan.

Prose ``task "<goal>"`` without ``--plan`` returns ``plan_required``.
Mutation is ``edit --plan``; ``task --plan`` is a deprecated alias.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _emit_task_terminal_event(a: argparse.Namespace, result: dict) -> None:
    from ..observability import emit_event

    status = str(result.get("status") or "unknown")
    payload = {
        "target": result.get("task_id") or getattr(a, "target", None),
        "status": status,
        "applied": bool(result.get("applied", False)),
    }
    reason_code = result.get("reason_code")
    if reason_code:
        payload["reason_code"] = str(reason_code)
    emit_event(
        "task_terminal",
        payload,
        level="warning" if status in {"blocked", "failed"} else "info",
        root=str(a.root),
    )


def _emit_verification_event(a: argparse.Namespace, payload: dict) -> None:
    from ..observability import emit_event

    status = str(payload.get("status") or "unknown")
    verify = payload.get("verify")
    event_payload = {
        "target": getattr(a, "target", None),
        "status": status,
    }
    if isinstance(verify, dict) and "exit_code" in verify:
        event_payload["exit_code"] = verify["exit_code"]
    reason_code = payload.get("reason_code")
    if reason_code:
        event_payload["reason_code"] = str(reason_code)
    emit_event(
        "validation_pass" if status == "verified" else "validation_fail",
        event_payload,
        level="info" if status == "verified" else "warning",
        root=str(a.root),
    )


def _emit_blocked_diagnostics(result: dict) -> None:
    if result.get("status") != "blocked":
        return
    for blocker in result.get("blocked_preconditions", []):
        if not isinstance(blocker, dict):
            continue
        code = blocker.get("code") or blocker.get("reason") or "blocked_precondition"
        message = blocker.get("message") or code
        next_surface = blocker.get("next_surface") or "task_preconditions"
        print(f"BLOCKED[{code}]: {message}; next_surface={next_surface}", file=sys.stderr)


def _run_verification_only(a: argparse.Namespace) -> int:
    from ..pipeline_stages import _configured_test_command, _verification_timeout_seconds
    from ..runtime_env import prepare_project_command, project_subprocess_env

    command, configuration_error = _configured_test_command(getattr(a, "root", None))
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
        _emit_verification_event(a, payload)
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
            env=project_subprocess_env(a.root),
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
    _emit_verification_event(a, payload)
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


PLAN_REQUIRED_NEXT_ACTION = "use simplicio-dev-cli edit --plan <edit-plan.json> --apply"


def _mechanical_plan_path(a: argparse.Namespace) -> str | None:
    plan = getattr(a, "plan", None)
    if plan is None:
        return None
    text = str(plan).strip()
    if not text or text == "-":
        return None
    return text


def _emit_plan_required(a: argparse.Namespace) -> int:
    payload = {
        "schema": "simplicio.dev-cli.task-result/v1",
        "status": "blocked",
        "reason_code": "plan_required",
        "next_action": PLAN_REQUIRED_NEXT_ACTION,
    }
    if getattr(a, "json", False):
        print(json.dumps(payload, sort_keys=True))
    else:
        print("BLOCKED: plan_required")
    return 2


def run(a: argparse.Namespace) -> int:
    if getattr(a, "verify_only", False):
        return _run_verification_only(a)
    plan = _mechanical_plan_path(a)
    if plan is None:
        return _emit_plan_required(a)
    from .edit import run_edit

    dry_run = bool(getattr(a, "dry_run_task", False))
    return run_edit(
        argparse.Namespace(
            root=getattr(a, "root", "."),
            plan=plan,
            apply=not dry_run,
            dry_run=dry_run,
            json=bool(getattr(a, "json", False)),
            no_runtime=True,
        )
    )
