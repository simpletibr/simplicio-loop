"""_pipeline_adapter.py — bridge between scratch.executor (which iterates
plan tasks) and simplicio.pipeline (which runs the cli verify-loop on one
task at a time).

The existing simplicio.pipeline helpers read SIMPLICIO_TEST_CMD from the
environment. We adapt one Task from the plan into one pipeline invocation,
with SIMPLICIO_TEST_CMD temporarily set to the per-task verify command.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .plan_schema import Task
from .stack_registry import Stack


def run_task(
    task: Task,
    project_dir: Path,
    stack: Stack,
    *,
    quiet: bool = False,
    forwarded_pipeline_kwargs: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Run one plan task through simplicio.pipeline.
    Returns (passed, log_tail)."""
    from .. import pipeline

    # Per-task verify command supersedes any global SIMPLICIO_TEST_CMD
    prev_test_cmd = os.environ.get("SIMPLICIO_TEST_CMD")
    previous_cwd = Path.cwd()
    os.environ["SIMPLICIO_TEST_CMD"] = task.verify
    try:
        stack_label = stack.language
        if stack.framework:
            stack_label = f"{stack.language} + {stack.framework}"

        _ensure_git_repo(project_dir)
        os.chdir(project_dir)
        # Explicitly typed `dict[str, Any]` (not the narrower `dict[str, str]`
        # mypy would otherwise infer) so **kwargs-unpacking this dict into
        # run_task's typed keyword-only parameters (e.g. `mode`, `effect_sink`,
        # added for issue #166/#167's integrated mode) doesn't trip a spurious
        # dict[str, str]-vs-Literal/EffectSink mismatch. Kept as **kwargs
        # unpacking (not explicit positional args) because callers/tests rely
        # on `pipeline.run`/`run_task` being invoked with keyword arguments
        # here (see tests/python/test_scratch.py).
        pipeline_kwargs: dict[str, Any] = {
            "root": str(project_dir),
            "stack": stack_label,
            "goal": task.goal,
            "target": task.target,
            "criteria": task.criteria,
            "constraints": task.constraints,
        }
        if forwarded_pipeline_kwargs is not None:
            pipeline_kwargs.update(forwarded_pipeline_kwargs)
        if quiet:
            output = pipeline.run_task(**pipeline_kwargs, quiet=True)
        else:
            output = pipeline.run(**pipeline_kwargs)
    finally:
        os.chdir(previous_cwd)
        if prev_test_cmd is None:
            os.environ.pop("SIMPLICIO_TEST_CMD", None)
        else:
            os.environ["SIMPLICIO_TEST_CMD"] = prev_test_cmd

    if output is None:
        return False, "(pipeline returned None — task did not converge)"
    if isinstance(output, str):
        log = output
    else:
        log = json.dumps(output, indent=2, sort_keys=True)
    return bool(not isinstance(output, dict) or output.get("applied")), log[:1500]


def _ensure_git_repo(project_dir: Path) -> None:
    if (project_dir / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "init"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
