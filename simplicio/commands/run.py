"""``simplicio-py run`` — run a task, feature, sprint, or scratch goal.

Extracted from `cli.py`'s `_run_run_command`/`_run_scratch_command`/
`_run_feature_command`/`_run_sprint_command` and their private sprint-state
helpers (issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from ..utils.fs import write_text_atomic
from ._shared import force_local_if_requested

CLI_PROG = "simplicio-py"


def _mode_guard(a: argparse.Namespace) -> tuple[dict, int] | None:
    """Block non-task integrated scopes before planners or local effects."""
    from ..execution_mode import (
        ExecutionInputError,
        blocked_input_profile,
        negotiate_execution_mode,
        prepare_execution_inputs,
        require_coordinator_attempt,
    )

    try:
        prepared = prepare_execution_inputs(
            getattr(a, "mode", None),
            root=a.root,
            context_snapshot_path=getattr(a, "context_snapshot", None),
            attempt_id=getattr(a, "attempt_id", None),
            lease_id=getattr(a, "lease_id", None),
            fencing_token=getattr(a, "fencing_token", None),
            context_handle=getattr(a, "context_handle", None),
        )
        profile = negotiate_execution_mode(
            getattr(a, "mode", None),
            root=a.root,
            runtime_handshake=prepared.runtime_handshake,
            context_snapshot=prepared.context_snapshot,
            effect_sink=prepared.effect_sink,
            coordinator_kind=getattr(a, "coordinator_kind", None),
            coordinator_id=getattr(a, "coordinator_id", None),
        )
        profile = require_coordinator_attempt(profile, prepared.attempt)
    except ExecutionInputError as exc:
        profile = blocked_input_profile(
            getattr(a, "mode", None),
            exc,
            root=a.root,
            coordinator_kind=getattr(a, "coordinator_kind", None),
            coordinator_id=getattr(a, "coordinator_id", None),
        )
    if profile.effective_mode != "blocked" and profile.effective_mode != "integrated":
        return None
    payload = {
        "scope": a.scope,
        "applied": False,
        "warnings": [profile.reason_code],
        "execution_profile": profile.to_dict(),
    }
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"{CLI_PROG} run: {profile.reason_code}", file=sys.stderr)
    return payload, 1


def _first_file_signal(signals: list[str]) -> str | None:
    for signal in signals:
        if signal.startswith("file:"):
            return signal.split(":", 1)[1]
    return None


def _run_scratch(a: argparse.Namespace) -> int:
    from ..scratch.cli import main as scratch_main

    scratch_argv = [a.goal]
    if a.stack:
        scratch_argv += ["--stack", a.stack]
    if a.root:
        scratch_argv += ["--root", a.root]
    if a.name:
        scratch_argv += ["--name", a.name]
    if a.dest:
        scratch_argv += ["--dest", a.dest]
    if a.planner:
        scratch_argv += ["--planner", a.planner]
    for slot in a.slot:
        scratch_argv += ["--slot", slot]
    if a.plan_only:
        scratch_argv.append("--plan-only")
    if a.skip_install:
        scratch_argv.append("--skip-install")
    if a.json:
        scratch_argv.append("--json")
    return scratch_main(scratch_argv)


def _run_feature(a: argparse.Namespace) -> int:
    if not a.stack:
        print(f"{CLI_PROG} run --scope feature requires --stack <slug>", file=sys.stderr)
        return 2
    guarded = _mode_guard(a)
    if guarded:
        return guarded[1]
    from ..orchestrator import run_feature

    force_local_if_requested(a)
    try:
        result = run_feature(
            root=a.root,
            stack_slug=a.stack,
            goal=a.goal,
            max_iter=a.max_iter,
            max_cost=a.max_cost,
            quiet=a.json,
        )
    except ValueError as exc:
        print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(result, sort_keys=True))
    else:
        status = "DONE" if result["applied"] else "FAILED"
        print(f"{status}: feature tasks={len(result['tasks'])} replans={result['replans']}")
        for warning in result["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
    return 0 if result["applied"] else 1


def _infer_sprint_name(goal: str) -> str | None:
    match = re.search(r"\bsprint[-\s_]*(\d+)\b", goal, flags=re.IGNORECASE)
    if not match:
        return None
    return f"sprint-{int(match.group(1)):02d}"


def _load_resumable_sprint_results(
    path: Path,
    sprint_name: str,
    stack: str,
) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if payload.get("scope") != "sprint":
        return []
    if payload.get("sprint_name") != sprint_name or payload.get("stack") != stack:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [
        row
        for row in results
        if isinstance(row, dict)
        and isinstance(row.get("result"), dict)
        and row["result"].get("applied") is True
        and row.get("task")
    ]


def _sprint_task_id(task) -> str:
    try:
        return task.path.name
    except AttributeError:
        return str(getattr(task, "title", ""))


def _write_sprint_state(
    path: Path,
    *,
    sprint,
    sprint_name: str,
    stack: str,
    max_cost: str,
    results: list[dict],
    dod_results: list[dict],
    complete: bool,
    cost: dict[str, str | None] | None = None,
) -> None:
    total = len(sprint.tasks)
    completed = sum(1 for row in results if row["result"]["applied"])
    failed = [row for row in results if not row["result"]["applied"]]
    failed_gates = [row["label"] for row in dod_results if not row["passed"]]
    state = "complete" if complete else "in-progress"
    if failed or failed_gates or (total == 0 and not complete):
        state = "failed"
    payload = {
        "scope": "sprint",
        "state": state,
        "sprint": sprint.title,
        "sprint_name": sprint_name,
        "stack": stack,
        "max_cost": max_cost,
        "total_features": total,
        "completed_features": completed,
        "failed_features": [row["task"] for row in failed],
        "failed_dod_gates": failed_gates,
        "complete": complete,
        "updated_at": int(time.time()),
        "results": results,
        "dod": dod_results,
        "cost": cost,
    }
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _run_sprint(a: argparse.Namespace) -> int:
    if not a.max_cost:
        print(f"{CLI_PROG} run --scope sprint requires --max-cost", file=sys.stderr)
        return 2
    if not a.stack:
        print(f"{CLI_PROG} run --scope sprint requires --stack <slug>", file=sys.stderr)
        return 2
    guarded = _mode_guard(a)
    if guarded:
        return guarded[1]
    from ..dod import load_dod, load_sprint_dod, run_dod_gates
    from ..orchestrator import run_feature
    from ..orchestrator.cost_governor import CostGovernor, provider_budget
    from ..sprint_loader import load_sprint

    sprint_name = a.sprint or _infer_sprint_name(a.goal)
    if not sprint_name:
        print(f"{CLI_PROG} run --scope sprint requires --sprint sprint-XX", file=sys.stderr)
        return 2

    try:
        sprint = load_sprint(a.root, sprint_name)
    except FileNotFoundError as exc:
        print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
        return 2

    try:
        CostGovernor.from_value(a.max_cost)
    except ValueError as exc:
        print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
        return 2

    state_dir = Path(a.root) / ".simplicio"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "sprint_state.json"
    if not sprint.tasks:
        _write_sprint_state(
            state_path,
            sprint=sprint,
            sprint_name=sprint_name,
            stack=a.stack,
            max_cost=a.max_cost,
            results=[],
            dod_results=[],
            complete=False,
            cost=None,
        )
        print(f"{CLI_PROG} run: sprint has no task specs: {sprint.root}", file=sys.stderr)
        return 2

    results = _load_resumable_sprint_results(state_path, sprint_name, a.stack)
    resumed = bool(results)
    duplicate_titles = {
        task.title
        for task in sprint.tasks
        if sum(1 for other in sprint.tasks if other.title == task.title) > 1
    }
    if duplicate_titles:
        results = [row for row in results if row.get("task_id")]
    completed_task_ids = {
        row.get("task_id")
        for row in results
        if isinstance(row.get("result"), dict) and row["result"].get("applied")
    }
    completed_tasks = {
        row["task"] for row in results if isinstance(row.get("result"), dict) and row["result"].get("applied")
    }
    with provider_budget(a.max_cost) as governor:
        for task in sprint.tasks:
            task_id = _sprint_task_id(task)
            if task_id in completed_task_ids or (
                task.title not in duplicate_titles and task.title in completed_tasks
            ):
                continue
            try:
                result = run_feature(
                    root=a.root,
                    stack_slug=a.stack,
                    goal=task.goal,
                    max_iter=a.max_iter,
                    max_cost=None,
                    quiet=a.json,
                )
            except ValueError as exc:
                result = {
                    "scope": "feature",
                    "goal": task.goal,
                    "stack": a.stack,
                    "applied": False,
                    "tasks": [],
                    "replans": 0,
                    "warnings": [str(exc)],
                }
                results.append({"task": task.title, "task_id": task_id, "result": result})
                governor.refresh_from_env()
                cost = governor.report()
                _write_sprint_state(
                    state_path,
                    sprint=sprint,
                    sprint_name=sprint_name,
                    stack=a.stack,
                    max_cost=a.max_cost,
                    results=results,
                    dod_results=[],
                    complete=False,
                    cost=cost,
                )
                print(f"{CLI_PROG} run: {exc}", file=sys.stderr)
                return 2
            governor.refresh_from_env()
            results.append({"task": task.title, "task_id": task_id, "result": result})
            _write_sprint_state(
                state_path,
                sprint=sprint,
                sprint_name=sprint_name,
                stack=a.stack,
                max_cost=a.max_cost,
                results=results,
                dod_results=[],
                complete=False,
                cost=governor.report(),
            )
            if not result["applied"]:
                break

        dod_gates = [*load_dod(a.root), *load_sprint_dod(sprint.root)]
        dod_results = run_dod_gates(a.root, dod_gates)
        applied = (
            len(results) == len(sprint.tasks)
            and all(row["result"]["applied"] for row in results)
            and all(row["passed"] for row in dod_results)
        )
        governor.refresh_from_env()
        cost = governor.report()
        _write_sprint_state(
            state_path,
            sprint=sprint,
            sprint_name=sprint_name,
            stack=a.stack,
            max_cost=a.max_cost,
            results=results,
            dod_results=dod_results,
            complete=applied,
            cost=cost,
        )
        payload = {
            "scope": "sprint",
            "sprint": sprint.title,
            "applied": applied,
            "features": results,
            "dod": dod_results,
            "cost": cost,
            "resumed": resumed,
        }
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "DONE" if applied else "FAILED"
        print(f"{status}: sprint features={len(results)} dod_gates={len(dod_results)}")
    return 0 if applied else 1


def run(a: argparse.Namespace) -> int:
    from ..intent import AUTO_CONFIDENCE_THRESHOLD, classify_goal

    result = classify_goal(a.goal, explicit_scope=a.scope)
    if result.confidence < AUTO_CONFIDENCE_THRESHOLD:
        print(
            f"{CLI_PROG} run: goal is ambiguous; pass --scope task|feature|sprint|scratch",
            file=sys.stderr,
        )
        return 2

    if result.scope == "task":
        if not a.target:
            a.target = _first_file_signal(result.signals)
        if not a.target and a.scope != "auto":
            a.target = _first_file_signal(classify_goal(a.goal).signals)
        if not a.target:
            print(f"{CLI_PROG} run --scope task requires --target or a file in goal", file=sys.stderr)
            return 2
        from .task import run as task_run

        return task_run(a)
    if result.scope == "scratch":
        return _run_scratch(a)
    if result.scope == "feature":
        return _run_feature(a)
    if result.scope == "sprint":
        return _run_sprint(a)
    print(f"{CLI_PROG} run: unsupported scope {result.scope!r}", file=sys.stderr)
    return 2
