"""`simplicio-loop orient` wrapper: one cold call up front, then one warm
call per task, with cache-hit detection against the previous call's Mapper
and Fast generation ids (see cache.py for the pure comparison).
"""
from __future__ import annotations

import json

import cache
import measure


def try_parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


def run_orient(loop_bin: str, repo: str, task_text: str, target: str, timeout: int = 90):
    """Run ``simplicio-loop orient --json`` once. Returns
    ``(orient_json_or_none, raw_output, metrics)``."""
    cmd = [loop_bin, "orient", "--task", task_text, "--repo", ".", "--target", target, "--json"]
    out, metrics = measure.run_subprocess(cmd, cwd=repo, timeout=timeout)
    return try_parse_json(out), out, metrics


def orient_call_record(loop_bin: str, repo: str, task_text: str, target: str,
                       previous_generations: dict, *, label: str) -> dict:
    """Run one orient call and build its full record: metrics, extracted
    generations, and whether it hit the previous call's cache (Mapper and
    Fast generation ids compared independently).

    ``previous_generations`` is mutated in place to the newly observed
    generations, so the caller can chain calls (cold -> warm task 1 -> warm
    task 2) and each one compares against the one immediately before it.
    """
    orient_json, raw_out, metrics = run_orient(loop_bin, repo, task_text, target)
    generations = cache.extract_generations(orient_json)
    record = {
        "label": label,
        "status": (orient_json or {}).get("status"),
        "metrics": metrics,
        "mapper_generation": generations["mapper_generation"],
        "fast_generation": generations["fast_generation"],
        "mapper_cache_hit": cache.is_cache_hit(
            previous_generations.get("mapper_generation"), generations["mapper_generation"]
        ),
        "fast_cache_hit": cache.is_cache_hit(
            previous_generations.get("fast_generation"), generations["fast_generation"]
        ),
    }
    previous_generations.update(generations)
    return record, orient_json


def orient_json_for_prompt(orient_json: dict | None) -> str:
    """Serialize the whole orient JSON (Mapper survey + Fast understanding/plan)
    for the LLM prompt -- the context SKILL.md step 1 hands the host."""
    if not orient_json:
        return "{}"
    return json.dumps(orient_json, ensure_ascii=False)
