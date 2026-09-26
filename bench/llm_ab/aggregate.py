"""Pure results-aggregation functions shared by run.py (building results.json)
and report.py (rendering REPORT.html). Every function here takes plain
dicts/lists already parsed from JSON (the agentic-arm shape written by
agent.run_agent + run.py -- one ``totals``/``commands``/``llm_calls`` per
task) and returns plain data; the only I/O is ``load_history``, which just
reads sibling result files off disk.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Optional


def token_totals(arm_data: dict) -> dict:
    """Sum LLM token/cost usage across every task's ``totals`` in one arm's
    results, splitting cached vs uncached prompt tokens and reasoning vs
    non-reasoning completion tokens. A task with no ``totals`` (a fatal
    error before any LLM call) contributes nothing."""
    prompt_uncached = completion_non_reasoning = reasoning = cached = 0
    cost = 0.0
    for task in arm_data.get("tasks", []):
        totals = task.get("totals") or {}
        pt = totals.get("prompt_tokens") or 0
        ct = totals.get("completion_tokens") or 0
        rt = totals.get("reasoning_tokens") or 0
        cat = totals.get("cached_tokens") or 0
        prompt_uncached += max(pt - cat, 0)
        cached += cat
        completion_non_reasoning += max(ct - rt, 0)
        reasoning += rt
        cost += totals.get("cost_usd") or 0
    return {
        "prompt_uncached": prompt_uncached,
        "cached": cached,
        "completion_non_reasoning": completion_non_reasoning,
        "reasoning": reasoning,
        "cost_usd": cost,
    }


def turns_stats(arm_data: dict) -> tuple[int, int, int]:
    """``(total_turns, first_try_successes, n_tasks)`` across one arm --
    ``first_try_successes`` counts tasks the agent solved in exactly one
    LLM turn."""
    tasks = arm_data.get("tasks", [])
    total_turns = sum(t.get("turns") or 0 for t in tasks)
    first_try = sum(1 for t in tasks if t.get("turns") == 1 and t.get("success"))
    return total_turns, first_try, len(tasks)


def success_summary(arm_data: dict) -> tuple[int, int]:
    """``(n_success, n_tasks)`` for one arm."""
    tasks = arm_data.get("tasks", [])
    return sum(1 for t in tasks if t.get("success")), len(tasks)


def cpu_ram(arm_data: dict) -> tuple[float, float]:
    """Total CPU seconds and peak RSS (MB) across every command every task
    ran (the agent's own bash-tool commands, each already measured by
    ``measure.run_subprocess``)."""
    cpu_total = 0.0
    peak_rss = 0.0
    for task in arm_data.get("tasks", []):
        for cmd in task.get("commands", []):
            cpu_total += cmd.get("cpu_s") or 0
            peak_rss = max(peak_rss, cmd.get("peak_rss_mb") or 0)
    return cpu_total, peak_rss


def simplicio_command_count(arm_data: dict) -> int:
    """How many of the agent's own bash-tool commands, across every task,
    invoked a simplicio-loop/mapper/dev-cli/fast binary (``totals.
    n_simplicio_commands``, summed)."""
    return sum((t.get("totals") or {}).get("n_simplicio_commands") or 0
               for t in arm_data.get("tasks", []))


def check_run_count(arm_data: dict) -> int:
    """How many times the agent itself invoked the harness-owned acceptance
    checker (``check_cadastro.py``) via its own bash-tool commands, across
    every task -- a signal of whether the agent verified its own work."""
    count = 0
    for task in arm_data.get("tasks", []):
        for cmd in task.get("commands", []):
            if "check_cadastro.py" in (cmd.get("command") or ""):
                count += 1
    return count


def diff_history(current: dict, previous: dict) -> dict:
    """Per-arm ``total_wall_s`` delta between two results.json-shaped dicts.

    Missing data on either side (an arm absent from ``previous``, or an
    older results file that used different arm names entirely -- e.g. the
    pre-agent-loop ``simplicio-files``/``simplicio-fast`` split) yields
    ``None`` for that arm rather than a fabricated number or a raised
    exception.
    """
    current_arms = current.get("arms") or {}
    previous_arms = previous.get("arms") or {}
    out: dict[str, dict] = {}
    for name, data in current_arms.items():
        prev = previous_arms.get(name) or {}
        cur_wall = data.get("total_wall_s")
        prev_wall = prev.get("total_wall_s")
        delta = (
            cur_wall - prev_wall
            if isinstance(cur_wall, (int, float)) and isinstance(prev_wall, (int, float))
            else None
        )
        out[name] = {"total_wall_s_delta": delta}
    return out


def load_history(
    results_dir: str, exclude_path: Optional[str] = None, task_count: Optional[int] = None
) -> list[dict]:
    """Load every ``*.json`` results file in ``results_dir`` (append-only
    history), sorted by filename (the ``<UTC-date>-<shortsha>-t<N>.json``
    naming convention sorts chronologically), excluding ``exclude_path`` (the
    file currently being written). A file that fails to parse (corrupt, or
    from a format this harness no longer writes) is skipped rather than
    raised.

    When ``task_count`` is given, only files whose name ends in
    ``-t<task_count>.json`` are kept -- a 2-task run and a 4-task run are not
    comparable, so history/diffing must never mix them. This also excludes
    legacy files written before the ``-tN`` suffix existed (no way to know
    how many tasks they ran)."""
    exclude_abs = os.path.abspath(exclude_path) if exclude_path else None
    paths = sorted(glob.glob(os.path.join(results_dir, "*.json")))
    suffix = f"-t{task_count}.json" if task_count is not None else None
    history = []
    for path in paths:
        if exclude_abs and os.path.abspath(path) == exclude_abs:
            continue
        if suffix is not None and not os.path.basename(path).endswith(suffix):
            continue
        try:
            with open(path) as f:
                history.append(json.load(f))
        except (OSError, ValueError):
            continue
    return history


def savings(normal_value: float, simplicio_value: float) -> dict:
    """What simplicio saved versus normal: positive = cheaper/faster with
    simplicio, negative = it cost more. ``pct`` is relative to normal."""
    value = round(normal_value - simplicio_value, 10)
    pct = round(value / normal_value * 100, 2) if normal_value else None
    return {"value": value, "pct": pct}


def effort_counts(arm_data: dict) -> dict[str, int]:
    """Count of ok LLM calls at each reasoning-effort value, across every
    task's ``llm_calls`` (issue #1310 follow-up: per-phase reasoning-effort
    hints). A call with no ``reasoning_effort`` (no hint was in hand yet, or
    ``--effort-policy none``) is bucketed under the literal key
    ``"default"`` -- no reasoning param was sent, so the model ran at its
    own default. A failed call (``ok`` false) is skipped, same as
    ``token_totals``."""
    counts: dict[str, int] = {}
    for task in arm_data.get("tasks", []):
        for call in task.get("llm_calls", []):
            if not call.get("ok"):
                continue
            effort = call.get("reasoning_effort") or "default"
            counts[effort] = counts.get(effort, 0) + 1
    return counts


def task_wall(arm_data: dict) -> float:
    """Wall-clock seconds summed over the arm's (possibly kind-scoped) tasks."""
    return round(sum(t.get("wall_s") or 0 for t in arm_data.get("tasks", [])), 3)
