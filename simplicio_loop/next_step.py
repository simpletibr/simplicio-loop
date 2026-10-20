"""The one plain `next:` line a BLOCKED result prints, and the top-level plan_required block (issue #1812).

A BLOCKED result must say what to do next. `emit` prints the line on stderr so stdout stays one JSON
document for machine readers. `plan_required_block` puts the plan schema and the apply steps at the top
level of a `wave` result instead of only inside its nested `state`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

from .task_contract import contract_hints

PLAN_SCHEMA = "simplicio.dev-cli.edit-plan/v1"
PLAN_SCHEMA_PATH = "packages/dev-cli/contracts/dev-cli-edit/edit-plan.schema.json"
MINIMAL_PLAN = '{"operations": [{"path": "<repo-relative file>", "find": "<exact text>", "replace": "<new text>"}]}'
TARGET_MISSING_RE = re.compile(r"target_missing_without_to_create:([^,\s]+)")


def emit(line: str) -> None:
    """Print the one `next:` line on stderr. Line breaks are folded so the result stays one line."""
    print("next: " + " ".join(str(line).split()), file=sys.stderr)


def task_path_of(run_dir: Path) -> str:
    """The task file a run was prepared from (its first task's source path), or a placeholder."""
    try:
        contract = json.loads((run_dir / "task-contract.json").read_text(encoding="utf-8"))
        for task in contract.get("tasks") or []:
            path = str(((task or {}).get("source") or {}).get("path") or "")
            if path:
                return path
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return "<task-file>"


def plan_required_block(*, repo: str, run_id: str, run_dir: Path, task_index: int, task_path: str) -> dict[str, Any]:
    task = task_path or "<task-file>"
    return {
        "schema": PLAN_SCHEMA,
        "schema_path": PLAN_SCHEMA_PATH,
        "minimal_form": MINIMAL_PLAN,
        "blocked_run": run_id,
        "blocked_run_accepts_plan": False,
        "plan_file": str(Path(run_dir) / f"edit-plan-{task_index}.json"),
        "apply_steps": [
            f"simplicio-loop prepare --repo {repo} --task {task}",
            f"write the plan to <run_dir printed by that prepare>/edit-plan-{task_index}.json",
            f"simplicio-loop wave <run_id printed by that prepare> --repo {repo}",
        ],
        "apply_command": f"simplicio-loop wave <run_id printed by that prepare> --repo {repo}",
        "reason": "a run already blocked at plan_required takes no plan; the plan must be in the run directory before wave",
    }


def plan_required_next(block: Mapping[str, Any], *, repo: str, run_id: str, task_path: str) -> str:
    task = task_path or "<task-file>"
    return (
        f"run {run_id} is blocked at plan_required and takes no plan now; start a new run with "
        f"`simplicio-loop prepare --repo {repo} --task {task}`, write the plan (schema {block['schema']}, "
        f"see {block['schema_path']}) to its edit-plan-N.json, then `simplicio-loop wave <new run_id> --repo {repo}`"
    )


def operator_plan_required_index(run_dir: Path) -> Optional[int]:
    """The task index whose operator receipt is plan_required, read from operator-receipt-N.json."""
    for path in sorted(Path(run_dir).glob("operator-receipt-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, Mapping) and payload.get("reason_code") == "plan_required":
            tail = path.stem.rsplit("-", 1)[-1]
            if tail.isdigit():
                return int(tail)
    return None


def orient_command(repo: str) -> str:
    return (f'simplicio-loop orient --brief --repo {repo} --task "<what the task changes>" '
            "(the Mapper survey comes first; then prepare again)")


def contract_problems(task_path: str, message: str) -> dict[str, Any]:
    """The validator's errors plus the located hints from the task file (issue #1812, observation 3)."""
    errors = [part.strip() for part in message.split("invalid task contract:", 1)[-1].split(";") if part.strip()]
    try:
        hints = contract_hints(Path(task_path).read_text(encoding="utf-8"))
    except OSError:
        hints = []
    return {"errors": errors, "hints": hints[:5]}


def _missing_targets(blockers: Any) -> list[str]:
    """The paths a blocked prepare lists as target_missing_without_to_create, in order and without repeats."""
    paths: list[str] = []
    for blocker in blockers or []:
        text = str(blocker.get("message") or "") if isinstance(blocker, Mapping) else str(blocker)
        for path in TARGET_MISSING_RE.findall(text):
            if path not in paths:
                paths.append(path)
    return paths


def prepare_next(repo: str, task_path: str, payload: Mapping[str, Any]) -> None:
    """The one `next:` line for a prepare that did not arm the run."""
    hints = (payload.get("task_contract") or {}).get("hints") or []
    if hints:
        hint = hints[0]
        where = f"line {hint['line']}" if hint.get("line") else "the task file"
        found = f" ({hint['found']})" if hint.get("found") else ""
        emit(f"{task_path} {where}: {hint['problem']}{found}; {hint['fix']}; "
             "a valid file: simplicio-loop prepare --example")
        return
    if payload.get("reason_code") == "prepare_failed":
        emit(f"fix the error above in {task_path}; a valid task file: simplicio-loop prepare --example")
        return
    missing = _missing_targets(payload.get("blockers"))
    if missing:
        emit(f"{', '.join(missing)} not found in {repo}: name only existing files in {task_path}, or give each "
             "new file its own task (a task starts with a 'System:' line) with the lines 'Type: Creation' and "
             "'Target: <path>'")
        return
    run_id = str(payload.get("run_id") or "")
    if run_id:
        emit(f"simplicio-loop status --repo {repo} --run-id {run_id} shows the blocker "
             f"(reason {payload.get('reason_code') or 'blocked'}); fix it, then prepare again")
        return
    emit(f"simplicio-loop status --repo {repo} shows why the run is blocked; then prepare again")


def annotate_blocked(payload: Mapping[str, Any], *, repo: str, run_id: str, flow: str,
                     run_dir: Path) -> dict[str, Any]:
    """A BLOCKED flow result names its next step: `plan_required` at top level, and one `next:` line."""
    annotated = dict(payload)
    if str(annotated.get("status") or "").upper() != "BLOCKED":
        return annotated
    state = annotated.get("state") if isinstance(annotated.get("state"), Mapping) else {}
    operator = state.get("operator") if isinstance(state.get("operator"), Mapping) else {}
    blockers = [b for b in (state.get("blockers") or []) if isinstance(b, Mapping)]
    blocker_text = " ".join(str(b.get("message") or "") for b in blockers)
    task_path = task_path_of(run_dir)
    if operator.get("reason_code") == "plan_required":
        index = operator_plan_required_index(run_dir) or 1
        block = plan_required_block(repo=repo, run_id=run_id, run_dir=run_dir, task_index=index,
                                    task_path=task_path)
        annotated["plan_required"] = block
        emit(plan_required_next(block, repo=repo, run_id=run_id, task_path=task_path))
        return annotated
    if "stale mapper context" in blocker_text or "repository changed after planning" in blocker_text:
        emit(f'simplicio-loop orient --brief --repo {repo} --task "<what the task changes>" '
             "(the changed paths are listed in the blocker; then prepare a new run and wave it)")
        return annotated
    if "Open a new run" in blocker_text:
        emit(f"this run cannot be re-applied; start a new run: simplicio-loop prepare --repo {repo} "
             f"--task {task_path}, then wave the new run_id")
        return annotated
    reason = str(operator.get("reason_code") or annotated.get("reason_code") or "blocked")
    emit(f"simplicio-loop status --repo {repo} --run-id {run_id} shows the blocker ({reason}); "
         "fix it, then prepare a new run")
    return annotated


__all__ = ["MINIMAL_PLAN", "PLAN_SCHEMA", "PLAN_SCHEMA_PATH", "annotate_blocked", "contract_problems", "emit",
           "operator_plan_required_index", "orient_command", "plan_required_block", "plan_required_next",
           "prepare_next", "task_path_of"]
