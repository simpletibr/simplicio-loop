"""Pure results-aggregation functions shared by run.py (building results.json)
and report.py (rendering REPORT.html). Every function here takes plain
dicts/lists already parsed from JSON and returns plain data; the only I/O is
``load_history``, which just reads sibling result files off disk.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Optional


def token_totals(arm_data: dict) -> dict:
    """Sum LLM token/cost usage across every attempt of every task in one
    arm's results, splitting cached vs uncached prompt tokens and reasoning
    vs non-reasoning completion tokens. Attempts whose LLM call failed
    (``ok`` falsy) contribute nothing -- there is no usage to report for a
    call that never returned."""
    prompt_uncached = completion_non_reasoning = reasoning = cached = 0
    cost = 0.0
    for task in arm_data.get("tasks", []):
        for attempt in task.get("attempts", []):
            call = attempt.get("llm_call") or {}
            if not call.get("ok"):
                continue
            pt = call.get("prompt_tokens") or 0
            ct = call.get("completion_tokens") or 0
            rt = call.get("reasoning_tokens") or 0
            cat = call.get("cached_tokens") or 0
            prompt_uncached += max(pt - cat, 0)
            cached += cat
            completion_non_reasoning += max(ct - rt, 0)
            reasoning += rt
            if call.get("cost_usd") is not None:
                cost += call["cost_usd"]
    return {
        "prompt_uncached": prompt_uncached,
        "cached": cached,
        "completion_non_reasoning": completion_non_reasoning,
        "reasoning": reasoning,
        "cost_usd": cost,
    }


def attempts_stats(arm_data: dict) -> tuple[int, int, int]:
    """``(total_attempts, first_try_successes, n_tasks)`` across one arm."""
    tasks = arm_data.get("tasks", [])
    total_attempts = sum(len(t.get("attempts", [])) for t in tasks)
    first_try = sum(1 for t in tasks if len(t.get("attempts", [])) == 1 and t.get("success"))
    return total_attempts, first_try, len(tasks)


def success_summary(arm_data: dict) -> tuple[int, int]:
    """``(n_success, n_tasks)`` for one arm."""
    tasks = arm_data.get("tasks", [])
    return sum(1 for t in tasks if t.get("success")), len(tasks)


def cpu_ram(arm_data: dict) -> tuple[float, float]:
    """Total CPU seconds and peak RSS (MB) across every measured step
    (per-attempt ``*_step``/``llm_call`` dicts, plus arm-level ``steps``
    entries such as ``orient``)."""
    cpu_total = 0.0
    peak_rss = 0.0
    for task in arm_data.get("tasks", []):
        for attempt in task.get("attempts", []):
            for value in attempt.values():
                if not isinstance(value, dict):
                    continue
                if "cpu_s" in value:
                    cpu_total += value.get("cpu_s") or 0
                    peak_rss = max(peak_rss, value.get("peak_rss_mb") or 0)
                if "step_cpu_s" in value:
                    cpu_total += value.get("step_cpu_s") or 0
                    peak_rss = max(peak_rss, value.get("step_peak_rss_mb") or 0)
    for step in arm_data.get("steps", []):
        metrics = step.get("metrics") or {}
        cpu_total += metrics.get("cpu_s") or 0
        peak_rss = max(peak_rss, metrics.get("peak_rss_mb") or 0)
    return cpu_total, peak_rss


def check_run_count(arm_data: dict) -> int:
    """How many times the harness-owned acceptance checker
    (``check_cadastro.py``) actually ran, across every attempt of every task
    -- one ``check_step`` per invocation."""
    count = 0
    for task in arm_data.get("tasks", []):
        for attempt in task.get("attempts", []):
            if "check_step" in attempt:
                count += 1
    return count


def diff_history(current: dict, previous: dict) -> dict:
    """Per-arm ``total_wall_s`` delta between two results.json-shaped dicts.

    Missing data on either side yields ``None`` for that arm rather than a
    fabricated number or a raised exception -- a prior run that never
    exercised an arm is not a regression.
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


def load_history(results_dir: str, exclude_path: Optional[str] = None) -> list[dict]:
    """Load every ``*.json`` results file in ``results_dir`` (append-only
    history), sorted by filename (the ``<UTC-date>-<shortsha>.json`` naming
    convention sorts chronologically), excluding ``exclude_path`` (the file
    currently being written)."""
    exclude_abs = os.path.abspath(exclude_path) if exclude_path else None
    paths = sorted(glob.glob(os.path.join(results_dir, "*.json")))
    history = []
    for path in paths:
        if exclude_abs and os.path.abspath(path) == exclude_abs:
            continue
        try:
            with open(path) as f:
                history.append(json.load(f))
        except (OSError, ValueError):
            continue
    return history
