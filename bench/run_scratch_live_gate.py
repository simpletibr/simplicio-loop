"""Run the live scratch v0.5 gate matrix in resumable slices.

Unlike the preflight, this runner invokes the real `simplicio-py scratch` command.
It can run a bounded slice with `--max-runs` so the 15 x 5 matrix can be
collected incrementally without redefining partial evidence as release-ready.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.run_scratch_release_gate import PILOT_STACKS, RELEASE_GOALS  # noqa: E402
from simplicio.scratch.stack_registry import StackRegistry  # noqa: E402


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---", re.DOTALL)
_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*?)\s*$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")

RESULTS_JSON = ROOT / "bench" / "results_scratch_live_gate.json"
RESULTS_MD = ROOT / "bench" / "results_scratch_live_gate.md"
CODEGEN_DISABLED_RESULTS_JSON = (
    ROOT / "bench" / "results_scratch_live_gate_codegen_disabled_baseline.json"
)
CODEGEN_DISABLED_RESULTS_MD = (
    ROOT / "bench" / "results_scratch_live_gate_codegen_disabled_baseline.md"
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_live_gate(
    *,
    work_dir: Path,
    stacks: tuple[str, ...] = PILOT_STACKS,
    goals: tuple[str, ...] = RELEASE_GOALS,
    max_runs: int | None = None,
    plan_only: bool = False,
    skip_install: bool = False,
    post_verify: bool = False,
    disable_codegen: bool = False,
    timeout_seconds: int = 900,
    skillopt_review: dict[str, Any] | None = None,
    skip_existing_keys: set[tuple[str, str]] | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    if max_runs is not None and max_runs < 1:
        raise ValueError("max_runs must be >= 1 when provided")
    work_dir.mkdir(parents=True, exist_ok=True)
    projects_dir = work_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    registry = StackRegistry()

    matrix = [
        (goal_index, stack)
        for goal_index, _goal in enumerate(goals, start=1)
        for stack in stacks
    ]
    if skip_existing_keys:
        matrix = [
            (goal_index, stack)
            for goal_index, stack in matrix
            if (goals[goal_index - 1], stack) not in skip_existing_keys
        ]
    if max_runs is not None:
        matrix = matrix[:max_runs]

    selected_stacks = tuple(dict.fromkeys(stack for _goal_index, stack in matrix))
    runtime_tool_preflight = _post_verify_tool_preflight(
        selected_stacks,
        enabled=post_verify and not plan_only,
        registry=registry,
    )
    rows = []
    t0 = time.perf_counter()
    for run_number, (goal_index, stack) in enumerate(matrix, start=1):
        goal = goals[goal_index - 1]
        rows.append(
            _run_one(
                run_number=run_number,
                goal_index=goal_index,
                goal=goal,
                stack=stack,
                projects_dir=projects_dir,
                plan_only=plan_only,
                skip_install=skip_install,
                post_verify=post_verify,
                disable_codegen=disable_codegen,
                timeout_seconds=timeout_seconds,
                runner=runner,
                registry=registry,
            )
        )

    elapsed_s = round(time.perf_counter() - t0, 3)
    summary = _summarize(
        rows,
        elapsed_s,
        plan_only=plan_only,
        post_verify=post_verify,
        skillopt_review=skillopt_review,
        runtime_tool_preflight=runtime_tool_preflight,
    )
    return {
        "benchmark": "scratch-live-gate",
        "scope": (
            "live scratch v0.5 gate execution slice; partial runs are evidence "
            "only for the executed slice and do not replace the full 75-run gate"
        ),
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "matrix": {
            "goals": len(goals),
            "stacks": len(stacks),
            "planned_runs": len(goals) * len(stacks),
            "release_planned_runs": len(RELEASE_GOALS) * len(PILOT_STACKS),
            "selected_runs": len(matrix),
            "plan_only": plan_only,
            "skip_install": skip_install,
            "post_verify": post_verify,
            "disable_codegen": disable_codegen,
        },
        "work_dir": "$WORK_DIR",
        "summary": summary,
        "runs": rows,
    }


def _run_one(
    *,
    run_number: int,
    goal_index: int,
    goal: str,
    stack: str,
    projects_dir: Path,
    plan_only: bool,
    skip_install: bool,
    post_verify: bool,
    disable_codegen: bool,
    timeout_seconds: int,
    runner: Runner,
    registry: StackRegistry,
) -> dict[str, Any]:
    project_name = f"gate-g{goal_index:02d}-{stack}"
    cmd = [
        sys.executable,
        "-m",
        "simplicio.cli",
        "scratch",
        goal,
        "--stack",
        stack,
        "--name",
        project_name,
        "--dest",
        str(projects_dir),
        "--json",
    ]
    if plan_only:
        cmd.append("--plan-only")
    if skip_install:
        cmd.append("--skip-install")

    started = time.perf_counter()
    try:
        proc = runner(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_scratch_env(disable_codegen),
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        duration_s = round(time.perf_counter() - started, 3)
        return {
            "run_number": run_number,
            "goal_index": goal_index,
            "stack": stack,
            "goal": goal,
            "project_name": project_name,
            "command": _redact_command(cmd),
            "returncode": None,
            "timed_out": True,
            "duration_s": duration_s,
            "planner_valid": False,
            "scaffold_clean": None,
            "task_all_passed": False,
            "e2e_green": None,
            "tasks_passed": 0,
            "tasks_total": 0,
            "codegen_disabled": disable_codegen,
            "post_verify": {
                "enabled": post_verify and not plan_only,
                "passed": False if post_verify and not plan_only else None,
                "error": "scratch command timed out",
            },
            "json_parse_error": "scratch command timed out before JSON output",
            "error": f"TIMEOUT after {timeout_seconds}s",
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
        }

    duration_s = round(time.perf_counter() - started, 3)
    stdout_text = _as_text(proc.stdout)
    stderr_text = _as_text(proc.stderr)
    payload, parse_error = _parse_json_stdout(stdout_text)
    verify = _post_verify(
        payload,
        stack_slug=stack,
        enabled=post_verify and not plan_only,
        timeout_seconds=timeout_seconds,
        runner=runner,
        registry=registry,
    )
    metrics = _row_metrics(
        payload,
        returncode=proc.returncode,
        plan_only=plan_only,
        post_verify=post_verify,
        verify=verify,
    )
    scratch_metrics = _scratch_metrics(payload)
    line_stats = _payload_line_stats(payload)
    cost_usd = _payload_cost_usd(payload)
    return {
        "run_number": run_number,
        "goal_index": goal_index,
        "stack": stack,
        "goal": goal,
        "project_name": project_name,
        "command": _redact_command(cmd),
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        **metrics,
        "scratch_metrics": scratch_metrics,
        "line_stats": line_stats,
        "cost_usd": cost_usd,
        "codegen_disabled": disable_codegen,
        "post_verify": verify,
        "json_parse_error": parse_error,
        "stdout_tail": _tail_text(stdout_text),
        "stderr_tail": _tail_text(stderr_text),
    }


def _scratch_env(disable_codegen: bool) -> dict[str, str] | None:
    if not disable_codegen:
        return None
    env = os.environ.copy()
    env["SIMPLICIO_DISABLE_CODEGEN"] = "1"
    return env


def _row_metrics(
    payload: dict[str, Any] | None,
    *,
    returncode: int,
    plan_only: bool,
    post_verify: bool,
    verify: dict[str, Any],
) -> dict[str, Any]:
    if not payload:
        return {
            "planner_valid": False,
            "scaffold_clean": None,
            "task_all_passed": False,
            "e2e_green": None,
            "tasks_passed": 0,
            "tasks_total": 0,
        }

    if plan_only:
        tasks = payload.get("tasks", [])
        planner_valid = returncode == 0 and isinstance(tasks, list) and bool(tasks)
        return {
            "planner_valid": planner_valid,
            "scaffold_clean": None,
            "task_all_passed": False,
            "e2e_green": None,
            "tasks_passed": 0,
            "tasks_total": len(tasks) if isinstance(tasks, list) else 0,
        }

    tasks_total, total_error = _coerce_int(payload.get("tasks_total", 0), "tasks_total")
    tasks_passed, passed_error = _coerce_int(
        payload.get("tasks_passed", 0),
        "tasks_passed",
    )
    if total_error or passed_error:
        return {
            "planner_valid": False,
            "scaffold_clean": False,
            "task_all_passed": False,
            "e2e_green": False if post_verify else None,
            "tasks_passed": max(tasks_passed, 0),
            "tasks_total": max(tasks_total, 0),
            "error": "; ".join(error for error in (total_error, passed_error) if error),
        }
    files_written = payload.get("files_written", [])
    scaffold_clean = isinstance(files_written, list) and bool(files_written)
    task_all_passed = (
        returncode == 0 and tasks_total > 0 and tasks_passed == tasks_total
    )
    e2e_green = bool(verify.get("passed")) if post_verify else None
    return {
        "planner_valid": tasks_total > 0 or scaffold_clean,
        "scaffold_clean": scaffold_clean,
        "task_all_passed": task_all_passed,
        "e2e_green": e2e_green,
        "tasks_passed": tasks_passed,
        "tasks_total": tasks_total,
    }


def _post_verify(
    payload: dict[str, Any] | None,
    *,
    stack_slug: str,
    enabled: bool,
    timeout_seconds: int,
    runner: Runner,
    registry: StackRegistry,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "passed": None}
    if not payload:
        return {"enabled": True, "passed": False, "error": "missing scratch payload"}
    project_dir_raw = str(payload.get("project_dir", "")).strip()
    if not project_dir_raw:
        return {"enabled": True, "passed": False, "error": "missing project_dir"}
    project_dir = Path(project_dir_raw)
    if not project_dir.is_dir():
        return {
            "enabled": True,
            "passed": False,
            "error": f"project_dir not found: {project_dir}",
        }
    stack = registry.get(stack_slug)
    if stack is None:
        return {
            "enabled": True,
            "passed": False,
            "error": f"unknown stack: {stack_slug}",
        }
    commands = [
        ("test", stack.test_command),
        ("lint", stack.lint_command),
    ]
    runtime_tool_preflight = _command_tool_preflight(
        [(stack_slug, name, command) for name, command in commands]
    )
    rows = []
    started = time.perf_counter()
    for name, command in commands:
        if not command:
            rows.append(
                {"name": name, "command": "", "returncode": None, "skipped": True}
            )
            continue
        command_start = time.perf_counter()
        rows.append(
            _run_verify_command(
                name=name,
                command=command,
                project_dir=project_dir,
                timeout_seconds=timeout_seconds,
                runner=runner,
                started=command_start,
            )
        )
    ran = [row for row in rows if not row.get("skipped")]
    return {
        "enabled": True,
        "passed": bool(ran) and all(row.get("passed") for row in ran),
        "duration_s": round(time.perf_counter() - started, 3),
        "runtime_tool_preflight": runtime_tool_preflight,
        "commands": rows,
    }


def _post_verify_tool_preflight(
    stack_slugs: tuple[str, ...],
    *,
    enabled: bool,
    registry: StackRegistry,
) -> dict[str, Any]:
    if not enabled:
        return _empty_runtime_tool_preflight(enabled=False)

    command_specs = []
    unknown_stacks = []
    for stack_slug in stack_slugs:
        stack = registry.get(stack_slug)
        if stack is None:
            unknown_stacks.append(stack_slug)
            continue
        command_specs.extend(
            [
                (stack_slug, "test", stack.test_command),
                (stack_slug, "lint", stack.lint_command),
            ]
        )
    preflight = _command_tool_preflight(command_specs)
    if unknown_stacks:
        preflight["unknown_stacks"] = unknown_stacks
    return preflight


def _command_tool_preflight(
    command_specs: list[tuple[str, str, str]],
) -> dict[str, Any]:
    rows = []
    for stack_slug, name, command in command_specs:
        row: dict[str, Any] = {
            "stack": stack_slug,
            "name": name,
            "command": command or "",
        }
        if command:
            row.update(_runtime_tool_check(command))
        else:
            row.update(
                {
                    "tool": None,
                    "available": None,
                    "path": None,
                    "skipped": True,
                    "diagnostic": "empty post-verify command",
                }
            )
        rows.append(row)

    checked = [row for row in rows if row.get("available") is not None]
    available_tools = sorted(
        {str(row["tool"]) for row in checked if row.get("available")}
    )
    missing_tools = sorted(
        {str(row["tool"]) for row in checked if row.get("available") is False}
    )
    return {
        "enabled": True,
        "scope": "post_verify",
        "commands": rows,
        "required_tools": sorted({str(row["tool"]) for row in checked}),
        "available_tools": available_tools,
        "missing_tools": missing_tools,
        "checked_commands": len(checked),
        "unchecked_commands": sum(1 for row in rows if row.get("available") is None),
    }


def _empty_runtime_tool_preflight(*, enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "scope": "post_verify",
        "commands": [],
        "required_tools": [],
        "available_tools": [],
        "missing_tools": [],
        "checked_commands": 0,
        "unchecked_commands": 0,
    }


def _runtime_tool_check(command: str) -> dict[str, Any]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {
            "tool": None,
            "available": None,
            "path": None,
            "diagnostic": f"could not parse command: {exc}",
        }
    tool = _runtime_tool_name(parts)
    if not tool:
        return {
            "tool": None,
            "available": None,
            "path": None,
            "diagnostic": "no runtime tool found in command",
        }
    if _is_project_local_tool(tool):
        return {
            "tool": tool,
            "available": None,
            "path": None,
            "diagnostic": "project-local command; availability checked by post-verify",
        }

    path = shutil.which(tool)
    if path:
        return {
            "tool": tool,
            "available": True,
            "path": path,
            "diagnostic": "found on PATH",
        }
    fallback = _python_module_fallback(command)
    if fallback and importlib.util.find_spec(str(fallback[2])) is not None:
        return {
            "tool": tool,
            "available": True,
            "path": None,
            "fallback_available": True,
            "diagnostic": "missing from PATH; Python module fallback available",
        }
    return {
        "tool": tool,
        "available": False,
        "path": None,
        "diagnostic": "missing from PATH",
    }


def _runtime_tool_name(parts: list[str]) -> str | None:
    for part in parts:
        if part == "env" or _ENV_ASSIGNMENT_RE.match(part):
            continue
        return part
    return None


def _is_project_local_tool(tool: str) -> bool:
    return (
        tool.startswith(".")
        or tool.startswith("/")
        or tool.startswith("\\")
        or "/" in tool
        or "\\" in tool
    )


def _run_verify_command(
    *,
    name: str,
    command: str,
    project_dir: Path,
    timeout_seconds: int,
    runner: Runner,
    started: float,
) -> dict[str, Any]:
    row = _invoke_verify_command(
        command,
        project_dir=project_dir,
        timeout_seconds=timeout_seconds,
        runner=runner,
        shell=True,
    )
    fallback = _python_module_fallback(command)
    if fallback and _verify_command_unavailable(row):
        row = _invoke_verify_command(
            fallback,
            project_dir=project_dir,
            timeout_seconds=timeout_seconds,
            runner=runner,
            shell=False,
        ) | {"fallback_for": command}

    row.update(
        {
            "name": name,
            "duration_s": round(time.perf_counter() - started, 3),
            "passed": row.get("returncode") == 0,
        }
    )
    return row


def _invoke_verify_command(
    command: str | list[str],
    *,
    project_dir: Path,
    timeout_seconds: int,
    runner: Runner,
    shell: bool,
) -> dict[str, Any]:
    try:
        proc = runner(
            command,
            cwd=project_dir,
            capture_output=True,
            text=True,
            shell=shell,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "timed_out": True,
            "stdout_tail": _tail_text(exc.stdout, limit=1000),
            "stderr_tail": _tail_text(exc.stderr, limit=1000),
        }
    return {
        "command": command,
        "returncode": proc.returncode,
        "timed_out": False,
        "stdout_tail": _tail_text(proc.stdout, limit=1000),
        "stderr_tail": _tail_text(proc.stderr, limit=1000),
    }


def _python_module_fallback(command: str) -> list[str] | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    module = parts[0].lower()
    if module not in {"pytest", "ruff"}:
        return None
    return [sys.executable, "-m", module, *parts[1:]]


def _verify_command_unavailable(row: dict[str, Any]) -> bool:
    if row.get("returncode") == 0 or row.get("timed_out"):
        return False
    if row.get("stdout_tail"):
        return False
    stderr = str(row.get("stderr_tail", "")).lower()
    return any(
        marker in stderr
        for marker in (
            "not recognized",
            "not found",
            "reconhecido",
            "no such file",
        )
    )


def _parse_json_stdout(stdout: str) -> tuple[dict[str, Any] | None, str]:
    text = (stdout or "").strip()
    if not text:
        return None, "stdout was empty"
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None, "stdout did not contain a JSON object"
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON stdout: {exc}"
    if not isinstance(value, dict):
        return None, "stdout JSON was not an object"
    return value, ""


def _coerce_int(value: Any, field: str) -> tuple[int, str]:
    try:
        return int(value or 0), ""
    except (TypeError, ValueError):
        return 0, f"{field} must be an integer"


def _scratch_metrics(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    metrics = payload.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _payload_line_stats(payload: dict[str, Any] | None) -> dict[str, int]:
    metrics = _scratch_metrics(payload)
    mapping = {
        "files_created": "files_created_total",
        "files_changed": "files_changed_total",
        "files_deleted": "files_deleted_total",
        "lines_generated": "lines_generated_total",
        "lines_modified": "lines_modified_total",
        "lines_added": "lines_added_total",
        "lines_removed": "lines_removed_total",
    }
    out = {}
    for key, metric_key in mapping.items():
        value, _error = _coerce_int(metrics.get(metric_key), metric_key)
        out[key] = value
    return out


def _payload_cost_usd(payload: dict[str, Any] | None) -> float | None:
    metrics = _scratch_metrics(payload)
    explicit = metrics.get("cost_usd")
    if explicit is not None:
        try:
            return round(float(explicit), 6)
        except (TypeError, ValueError):
            return None
    tasks_llm = metrics.get("tasks_llm")
    if tasks_llm is not None:
        try:
            return 0.0 if int(tasks_llm) == 0 else None
        except (TypeError, ValueError):
            return None
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _tail_text(value: Any, *, limit: int = 1500) -> str:
    return _as_text(value)[-limit:]


def _summarize(
    rows: list[dict[str, Any]],
    elapsed_s: float,
    *,
    plan_only: bool,
    post_verify: bool,
    skillopt_review: dict[str, Any] | None = None,
    runtime_tool_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(rows)
    planner_valid = sum(1 for row in rows if row.get("planner_valid"))
    scaffold_rows = [row for row in rows if row.get("scaffold_clean") is not None]
    e2e_rows = [row for row in rows if row.get("e2e_green") is not None]
    scaffold_clean = sum(1 for row in scaffold_rows if row.get("scaffold_clean"))
    e2e_green = sum(1 for row in e2e_rows if row.get("e2e_green"))
    task_all_passed = sum(1 for row in rows if row.get("task_all_passed"))
    durations = [float(row["duration_s"]) for row in rows if not row.get("timed_out")]
    median_wall_clock_s = round(statistics.median(durations), 3) if durations else None
    planner_valid_rate = _ratio(planner_valid, total)
    scaffold_clean_rate = _ratio(scaffold_clean, len(scaffold_rows))
    e2e_green_rate = _ratio(e2e_green, len(e2e_rows))
    cost_values = [
        float(row["cost_usd"]) for row in rows if row.get("cost_usd") is not None
    ]
    average_cost_usd = (
        round(sum(cost_values) / len(cost_values), 6)
        if len(cost_values) == total and total
        else None
    )
    lines_generated_total = sum(
        int((row.get("line_stats") or {}).get("lines_generated") or 0)
        for row in rows
    )
    lines_modified_total = sum(
        int((row.get("line_stats") or {}).get("lines_modified") or 0)
        for row in rows
    )
    skillopt = _normalize_skillopt_review(skillopt_review)
    runtime_tools = runtime_tool_preflight or _empty_runtime_tool_preflight(
        enabled=post_verify and not plan_only
    )
    release_gates = {
        "full_75_run_matrix": _has_full_release_matrix(rows),
        "planner_valid_ge_90": planner_valid_rate >= 0.90 if total else False,
        "scaffold_clean_ge_95": None if plan_only else scaffold_clean_rate >= 0.95,
        "e2e_green_ge_80": (
            e2e_green_rate >= 0.80 if post_verify and e2e_rows else None
        ),
        "median_wall_clock_le_8m": (
            median_wall_clock_s <= 480 if median_wall_clock_s is not None else None
        ),
        "average_cost_le_1": (
            average_cost_usd <= 1.0 if average_cost_usd is not None else None
        ),
        "skillopt_human_approval_ge_80": skillopt["gate_passed"],
    }
    release_gates["release_ready"] = all(
        value is True for value in release_gates.values()
    )
    return {
        "total_runs": total,
        "planner_valid": planner_valid,
        "planner_valid_rate": planner_valid_rate,
        "scaffold_clean": scaffold_clean,
        "scaffold_clean_rate": scaffold_clean_rate,
        "task_all_passed": task_all_passed,
        "task_all_passed_rate": _ratio(task_all_passed, total),
        "e2e_green": e2e_green,
        "e2e_green_rate": e2e_green_rate,
        "timed_out": sum(1 for row in rows if row.get("timed_out")),
        "median_wall_clock_s": median_wall_clock_s,
        "average_cost_usd": average_cost_usd,
        "lines_generated_total": lines_generated_total,
        "lines_modified_total": lines_modified_total,
        "avg_lines_generated_per_run": _ratio(lines_generated_total, total),
        "avg_lines_modified_per_run": _ratio(lines_modified_total, total),
        "skillopt_review": skillopt,
        "runtime_tool_preflight": runtime_tools,
        "elapsed_s": elapsed_s,
        "release_gates": release_gates,
        "missing_release_evidence": _missing_release_evidence(
            release_gates,
            plan_only,
            post_verify,
        ),
    }


def _missing_release_evidence(
    release_gates: dict[str, Any],
    plan_only: bool,
    post_verify: bool,
) -> list[str]:
    missing = []
    if not release_gates["full_75_run_matrix"]:
        missing.append("full 15 goals x 5 pilot stacks live matrix")
    if plan_only:
        missing.append("scaffold and end-to-end execution, not only plan validation")
    elif not post_verify:
        missing.append("post-scratch stack test/lint verification")
    if release_gates["average_cost_le_1"] is None:
        missing.append("average cost measurement")
    if not release_gates["skillopt_human_approval_ge_80"]:
        missing.append("SkillOpt human approval evidence >=80%")
    return missing


def load_skillopt_review_evidence(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_skillopt_review(raw, source=str(path))


def _normalize_skillopt_review(
    evidence: dict[str, Any] | None,
    *,
    source: str = "inline",
) -> dict[str, Any]:
    if not evidence:
        return {
            "source": source,
            "total_reviews": 0,
            "approved": 0,
            "approval_rate": 0.0,
            "gate_passed": False,
            "reviews": [],
            "invalid_reviews": 0,
            "duplicate_reviews": 0,
            "artifact_verified": 0,
        }
    rows = evidence.get("reviews") or evidence.get("skill_reviews") or []
    normalized = []
    invalid = int(evidence.get("invalid_reviews") or 0)
    duplicate = int(evidence.get("duplicate_reviews") or 0)
    seen_artifacts: set[tuple[str, str]] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            invalid += 1
            continue
        skill = str(row.get("skill") or row.get("slug") or "").strip()
        reviewer = str(row.get("reviewer") or "").strip()
        reviewed_at = str(row.get("reviewed_at") or "").strip()
        approved = row.get("approved")
        artifact_path = str(row.get("skill_md") or row.get("path") or "").strip()
        sha256 = str(row.get("sha256") or "").strip()
        artifact_key = _skillopt_artifact_key(artifact_path, sha256)
        artifact_verified = _skillopt_artifact_hash_matches(artifact_path, sha256)
        artifact_frontmatter_valid = _skillopt_artifact_frontmatter_valid(artifact_path)
        if (
            not skill
            or not reviewer
            or not reviewed_at
            or not isinstance(approved, bool)
            or not artifact_path
            or not sha256
            or artifact_verified is not True
            or artifact_frontmatter_valid is not True
        ):
            invalid += 1
            continue
        if artifact_key in seen_artifacts:
            duplicate += 1
            invalid += 1
            continue
        seen_artifacts.add(artifact_key)
        normalized.append(
            {
                "skill": skill,
                "reviewer": reviewer,
                "approved": approved,
                "reviewed_at": reviewed_at,
                "notes": str(row.get("notes") or "").strip(),
                "path": artifact_path,
                "sha256": sha256,
                "artifact_verified": artifact_verified,
                "artifact_frontmatter_valid": artifact_frontmatter_valid,
            }
        )
    total = len(normalized)
    approved_count = sum(1 for row in normalized if row["approved"])
    approval_rate = _ratio(approved_count, total)
    return {
        "source": str(evidence.get("source") or source),
        "total_reviews": total,
        "approved": approved_count,
        "approval_rate": approval_rate,
        "gate_passed": total >= 10 and approval_rate >= 0.80,
        "reviews": normalized,
        "invalid_reviews": invalid,
        "duplicate_reviews": duplicate,
        "artifact_verified": sum(
            1 for row in normalized if row.get("artifact_verified") is True
        ),
    }


def _skillopt_artifact_key(path: str, expected_sha256: str) -> tuple[str, str]:
    artifact = Path(path)
    if not artifact.is_absolute():
        artifact = ROOT / artifact
    try:
        artifact_id = str(artifact.resolve())
    except OSError:
        artifact_id = str(artifact)
    return artifact_id, expected_sha256


def _skillopt_artifact_hash_matches(path: str, expected_sha256: str) -> bool:
    if not path or not expected_sha256:
        return False
    artifact = _skillopt_artifact_path(path)
    if not artifact.is_file():
        return False
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return actual == expected_sha256


def _skillopt_artifact_frontmatter_valid(path: str) -> bool:
    artifact = _skillopt_artifact_path(path)
    if not artifact.is_file():
        return False
    try:
        fields = _skillopt_frontmatter(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return (
        fields.get("review_required", "").lower() == "true"
        and fields.get("by") == "skill-opt"
        and bool(fields.get("source_goal"))
        and bool(fields.get("planner_model"))
    )


def _skillopt_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        parsed = _FIELD_RE.match(line.strip())
        if parsed:
            fields[parsed.group("key")] = parsed.group("value").strip('"')
    return fields


def _skillopt_artifact_path(path: str) -> Path:
    artifact = Path(path)
    if not artifact.is_absolute():
        artifact = ROOT / artifact
    return artifact


def _has_full_release_matrix(rows: list[dict[str, Any]]) -> bool:
    required = {(goal, stack) for goal in RELEASE_GOALS for stack in PILOT_STACKS}
    observed = {
        (str(row.get("goal")), str(row.get("stack")))
        for row in rows
        if row.get("goal") and row.get("stack")
    }
    return required.issubset(observed)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _redact_command(cmd: list[str]) -> list[str]:
    redacted = []
    for part in cmd:
        text = str(part)
        if str(ROOT) in text:
            text = text.replace(str(ROOT), "$ROOT")
        redacted.append(text)
    return redacted


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def merge_results(
    existing: dict[str, Any],
    current: dict[str, Any],
    *,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    if existing.get("benchmark") != current.get("benchmark"):
        raise ValueError("cannot merge different benchmark result types")
    current_matrix = current.get("matrix", {})
    _validate_merge_compatible(
        existing,
        plan_only=bool(current_matrix.get("plan_only")),
        skip_install=bool(current_matrix.get("skip_install")),
        post_verify=bool(current_matrix.get("post_verify")),
        disable_codegen=bool(current_matrix.get("disable_codegen")),
    )

    rows_by_key = {
        _row_key(row): row
        for row in existing.get("runs", [])
        if _row_key(row) is not None
    }
    for row in current.get("runs", []):
        key = _row_key(row)
        if key is not None:
            if key in rows_by_key and not allow_overwrite:
                raise ValueError(
                    "refusing to overwrite existing live gate row: "
                    f"goal={key[0]!r} stack={key[1]!r}"
                )
            rows_by_key[key] = row
    rows = sorted(
        rows_by_key.values(),
        key=lambda row: (
            int(row.get("goal_index") or 0),
            _pilot_stack_index(str(row.get("stack", ""))),
            str(row.get("stack", "")),
        ),
    )
    for index, row in enumerate(rows, start=1):
        row["run_number"] = index

    elapsed_s = round(
        float(existing.get("summary", {}).get("elapsed_s") or 0)
        + float(current.get("summary", {}).get("elapsed_s") or 0),
        3,
    )
    matrix = dict(current_matrix)
    matrix["goals"] = len({row.get("goal") for row in rows if row.get("goal")})
    matrix["stacks"] = len({row.get("stack") for row in rows if row.get("stack")})
    matrix["planned_runs"] = len(rows)
    matrix["selected_runs"] = len(rows)

    return {
        **current,
        "matrix": matrix,
        "runs": rows,
        "summary": _summarize(
            rows,
            elapsed_s,
            plan_only=bool(current_matrix.get("plan_only")),
            post_verify=bool(current_matrix.get("post_verify")),
            skillopt_review=(
                current.get("summary", {}).get("skillopt_review")
                or existing.get("summary", {}).get("skillopt_review")
            ),
            runtime_tool_preflight=_post_verify_tool_preflight(
                tuple(
                    dict.fromkeys(
                        str(row.get("stack"))
                        for row in rows
                        if row.get("stack")
                    )
                ),
                enabled=bool(current_matrix.get("post_verify"))
                and not bool(current_matrix.get("plan_only")),
                registry=StackRegistry(),
            ),
        ),
    }


def _validate_merge_compatible(
    result: dict[str, Any],
    *,
    plan_only: bool,
    skip_install: bool,
    post_verify: bool,
    disable_codegen: bool,
) -> None:
    if result.get("benchmark") != "scratch-live-gate":
        raise ValueError("cannot merge different benchmark result types")
    matrix = result.get("matrix")
    if not isinstance(matrix, dict):
        raise ValueError("existing live gate report has no matrix")
    expected = {
        "plan_only": plan_only,
        "skip_install": skip_install,
        "post_verify": post_verify,
        "disable_codegen": disable_codegen,
    }
    for field, expected_value in expected.items():
        if bool(matrix.get(field)) != bool(expected_value):
            raise ValueError(f"cannot merge live gate results with different {field}")


def _row_key(row: dict[str, Any]) -> tuple[str, str] | None:
    goal = row.get("goal")
    stack = row.get("stack")
    if not goal or not stack:
        return None
    return str(goal), str(stack)


def existing_row_keys(result: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        key
        for row in result.get("runs", [])
        if (key := _row_key(row)) is not None
    }


def _pilot_stack_index(stack: str) -> int:
    try:
        return PILOT_STACKS.index(stack)
    except ValueError:
        return len(PILOT_STACKS)


def _to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    matrix = result["matrix"]
    skillopt = summary.get("skillopt_review") or {}
    runtime_tools = summary.get("runtime_tool_preflight") or {}
    lines = [
        "# Scratch Live Gate",
        "",
        result["scope"],
        "",
        "## Matrix",
        "",
        f"- release planned runs: {matrix['release_planned_runs']}",
        f"- selected matrix runs: {matrix['planned_runs']}",
        f"- selected runs: {matrix['selected_runs']}",
        f"- plan only: {matrix['plan_only']}",
        f"- skip install: {matrix['skip_install']}",
        f"- post verify: {matrix['post_verify']}",
        f"- codegen disabled: {matrix.get('disable_codegen', False)}",
        "",
        "## Summary",
        "",
        f"- planner valid: {summary['planner_valid']}/{summary['total_runs']} ({summary['planner_valid_rate']:.2%})",
        f"- scaffold clean: {summary['scaffold_clean']} ({summary['scaffold_clean_rate']:.2%})",
        f"- task all passed: {summary['task_all_passed']} ({summary['task_all_passed_rate']:.2%})",
        f"- e2e green: {summary['e2e_green']} ({summary['e2e_green_rate']:.2%})",
        f"- median wall-clock: {summary['median_wall_clock_s']} s",
        f"- average cost: {summary['average_cost_usd']}",
        f"- lines generated: {summary['lines_generated_total']}",
        f"- lines modified: {summary['lines_modified_total']}",
        f"- runtime tool preflight: {runtime_tools.get('enabled', False)}",
        (
            "- missing runtime tools: "
            f"{_format_markdown_list(runtime_tools.get('missing_tools') or [])}"
        ),
        f"- release ready: {summary['release_gates']['release_ready']}",
        "",
        "## Release Gate Status",
        "",
    ]
    for gate, value in summary["release_gates"].items():
        lines.append(f"- {gate}: {value}")
    lines.extend(
        [
            "",
            "## SkillOpt Review Evidence",
            "",
            f"- source: {skillopt.get('source', 'inline')}",
            (
                f"- reviewed skills: {skillopt.get('approved', 0)}/"
                f"{skillopt.get('total_reviews', 0)} approved"
            ),
            f"- approval rate: {float(skillopt.get('approval_rate', 0.0)):.2%}",
            f"- invalid review rows: {skillopt.get('invalid_reviews', 0)}",
        ]
    )
    lines.extend(
        [
            "",
            "## Runtime Tool Preflight",
            "",
            (
                "- required tools: "
                f"{_format_markdown_list(runtime_tools.get('required_tools') or [])}"
            ),
            (
                "- available tools: "
                f"{_format_markdown_list(runtime_tools.get('available_tools') or [])}"
            ),
            (
                "- missing tools: "
                f"{_format_markdown_list(runtime_tools.get('missing_tools') or [])}"
            ),
            f"- checked commands: {runtime_tools.get('checked_commands', 0)}",
            f"- unchecked commands: {runtime_tools.get('unchecked_commands', 0)}",
        ]
    )
    lines.extend(
        [
            "",
            "## Runs",
            "",
            "| # | stack | goal_index | rc | planner | scaffold | tasks | e2e | duration_s |",
            "| ---: | --- | ---: | ---: | --- | --- | --- | --- | ---: |",
        ]
    )
    for row in result["runs"]:
        lines.append(
            "| {run} | {stack} | {goal_index} | {rc} | {planner} | {scaffold} | {tasks} | {e2e} | {duration} |".format(
                run=row["run_number"],
                stack=row["stack"],
                goal_index=row["goal_index"],
                rc=row["returncode"],
                planner=row["planner_valid"],
                scaffold=row["scaffold_clean"],
                tasks=row.get("task_all_passed"),
                e2e=row["e2e_green"],
                duration=row["duration_s"],
            )
        )
    lines.extend(["", "## Missing Release Evidence", ""])
    if summary["missing_release_evidence"]:
        for item in summary["missing_release_evidence"]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _format_markdown_list(values: list[Any]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--goal-limit", type=int, default=len(RELEASE_GOALS))
    parser.add_argument("--stack", action="append", dest="stacks")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument(
        "--post-verify",
        action="store_true",
        help="after scratch execution, run the selected stack test and lint commands",
    )
    parser.add_argument(
        "--disable-codegen",
        action="store_true",
        help=(
            "run scratch with SIMPLICIO_DISABLE_CODEGEN=1 so mechanical tasks "
            "fall through to the LLM path; intended for real baseline capture"
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument(
        "--skillopt-review-json",
        type=Path,
        help=(
            "human review evidence JSON for generated SkillOpt skills; requires "
            ">=10 reviewed skills and >=80%% approved"
        ),
    )
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="merge this slice into an existing JSON report instead of replacing it",
    )
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="skip rows already present in --json-output before applying --max-runs",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="replace existing output files instead of preserving or merging them",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.resume_existing and args.overwrite_existing:
        parser.error("--resume-existing cannot be combined with --overwrite-existing")
    if args.merge_existing and (args.resume_existing or args.overwrite_existing):
        parser.error(
            "--merge-existing cannot be combined with "
            "--resume-existing or --overwrite-existing"
        )
    return args


def _resolve_output_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    json_output = args.json_output
    md_output = args.md_output
    if args.disable_codegen:
        if json_output == RESULTS_JSON:
            json_output = CODEGEN_DISABLED_RESULTS_JSON
        if md_output == RESULTS_MD:
            md_output = CODEGEN_DISABLED_RESULTS_MD
    return json_output, md_output


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    json_output, md_output = _resolve_output_paths(args)
    goals = RELEASE_GOALS[: args.goal_limit]
    stacks = tuple(args.stacks) if args.stacks else PILOT_STACKS
    existing = None
    preserving_existing = args.resume_existing or args.merge_existing
    if (
        not preserving_existing
        and not args.overwrite_existing
        and (json_output.exists() or md_output.exists())
    ):
        print(
            "refusing to overwrite existing live gate output; use "
            "--resume-existing, --merge-existing, or --overwrite-existing",
            file=sys.stderr,
        )
        return 2
    if (args.resume_existing or args.merge_existing) and json_output.is_file():
        try:
            existing = json.loads(json_output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"failed to read existing live gate report: {exc}", file=sys.stderr)
            return 2
        try:
            _validate_merge_compatible(
                existing,
                plan_only=args.plan_only,
                skip_install=args.skip_install,
                post_verify=args.post_verify,
                disable_codegen=args.disable_codegen,
            )
        except ValueError as exc:
            print(f"existing live gate report is incompatible: {exc}", file=sys.stderr)
            return 2
    result = run_live_gate(
        work_dir=args.work_dir,
        stacks=stacks,
        goals=goals,
        max_runs=args.max_runs,
        plan_only=args.plan_only,
        skip_install=args.skip_install,
        post_verify=args.post_verify,
        disable_codegen=args.disable_codegen,
        timeout_seconds=args.timeout_seconds,
        skillopt_review=(
            load_skillopt_review_evidence(args.skillopt_review_json)
            if args.skillopt_review_json
            else None
        ),
        skip_existing_keys=(
            existing_row_keys(existing) if args.resume_existing and existing else None
        ),
    )
    if preserving_existing and existing:
        try:
            result = merge_results(
                existing,
                result,
            )
        except ValueError as exc:
            print(f"failed to merge existing live gate report: {exc}", file=sys.stderr)
            return 2
    write_reports(result, json_output, md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {json_output}")
        print(f"wrote {md_output}")
    summary = result["summary"]
    return (
        0
        if summary["total_runs"] > 0
        and summary["planner_valid"] == summary["total_runs"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
