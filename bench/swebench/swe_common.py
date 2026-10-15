"""Shared constants and helpers of the SWE-bench Verified harness (#1819).

The raw per-run JSON is the ``bench/llm_ab`` results schema, one (task, arm, model) per file:
``{"meta": {...}, "arms": {<arm>: {"arm", "model", "tasks": [<task>], "total_wall_s"}}}``
with the same arm names (``normal`` = loop OFF, ``simplicio`` = loop ON) and the same task
``totals`` keys (``prompt_tokens``, ``completion_tokens``, ``cached_tokens``, ``cost_usd`` ...).
Cost maths, arm specs and the OpenCode driver are reused from ``bench/llm_ab`` by path, never copied.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
LLM_AB_DIR = os.path.join(REPO_ROOT, "bench", "llm_ab")
DEFAULT_MANIFEST = os.path.join(HERE, "manifest.json")
DEFAULT_RESULTS_DIR = os.path.join(HERE, "results")
DEFAULT_CACHE_DIR = os.path.join(HERE, ".cache")

HARNESS_VERSION = "simplicio-swebench-harness/1"
RAW_SCHEMA = "simplicio-swebench-raw/1"
RUN_SCHEMA = "simplicio-swebench-run/1"
MIN_TASKS = 30

LOOP_ARMS = ("normal", "simplicio")
ARM_LABELS = {"normal": "loop OFF", "simplicio": "loop ON"}
ARM_LOOP = {"normal": "off", "simplicio": "on"}

# status: "ok" = the agent finished and the evaluator gave a verdict; "agent_timeout" = the agent ran
# out of time (a failed attempt, counted); "infra_error" = provider/docker/evaluator trouble (not a
# verdict on the arm, excluded from n and reported as ``excluded``).
STATUSES = ("ok", "agent_timeout", "infra_error")
COUNTED_STATUSES = ("ok", "agent_timeout")

_PRICE_FIELDS = ("available", "prompt", "completion", "input_cache_read", "input_cache_write", "internal_reasoning")


def load_llm_ab(name: str):
    """Import ``bench/llm_ab/<name>.py`` by path under a private alias (no sys.path pollution, no clash
    with any other module called ``aggregate``/``cost``/``arms``)."""
    alias = f"_llm_ab_{name}"
    if alias in sys.modules:
        return sys.modules[alias]
    path = os.path.join(LLM_AB_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(alias, None)
        raise
    return module


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def model_slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)


def raw_filename(instance_id: str, arm: str, model: str) -> str:
    return f"{instance_id}@{arm}@{model_slug(model)}.json"


def price_signature(pricing: dict | None) -> tuple:
    """The price fields that decide a cost (the snapshot time is deliberately left out)."""
    pricing = pricing or {}
    return tuple(pricing.get(k) for k in _PRICE_FIELDS)


def build_raw_doc(*, run_id: str, date: str, main_commit: str, model: str, pricing: dict, dataset: dict,
                  manifest_id: str, instance: dict, arm: str, status: str, success: bool, wall_s: float,
                  totals: dict, turns: int = 0, error: str | None = None, check_output_tail: str = "",
                  patch_sha256: str | None = None, final_text: str | None = None) -> dict:
    """One raw run file: the ``bench/llm_ab`` results shape with a single task."""
    llm_cost = load_llm_ab("cost")
    totals = llm_cost.finalize_task_cost(dict(totals), pricing)
    task = {
        "index": 1,
        "kind": "swebench-verified",
        "instance_id": instance["instance_id"],
        "repo": instance.get("repo"),
        "status": status,
        "success": bool(success),
        "turns": turns,
        "wall_s": wall_s,
        "totals": totals,
        "check_output_tail": check_output_tail,
    }
    if error:
        task["error"] = error
    if patch_sha256:
        task["patch_sha256"] = patch_sha256
    if final_text is not None:
        task["final_text"] = final_text[-2000:]
    return {
        "schema": RAW_SCHEMA,
        "meta": {
            "harness_version": HARNESS_VERSION,
            "run_id": run_id,
            "date": date,
            "main_commit": main_commit,
            "model": "openrouter/" + model,
            "pricing": pricing,
            "task_set": "swebench-verified",
            "agent": "opencode",
            "dataset": {"name": dataset["name"], "revision": dataset["revision"]},
            "manifest_id": manifest_id,
            "instance_id": instance["instance_id"],
            "arm": arm,
            "loop": ARM_LOOP[arm],
        },
        "arms": {arm: {"arm": arm, "model": model, "tasks": [task], "total_wall_s": wall_s}},
    }


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_raw(doc) -> list[str]:
    """Problems with a raw run file ([] = valid). The aggregate refuses a directory with any problem."""
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    problems: list[str] = []
    if doc.get("schema") != RAW_SCHEMA:
        problems.append(f"schema is {doc.get('schema')!r}, expected {RAW_SCHEMA!r}")
    meta = doc.get("meta")
    if not isinstance(meta, dict):
        return problems + ["meta missing"]
    for key in ("harness_version", "run_id", "date", "main_commit", "model", "manifest_id", "instance_id", "arm", "loop"):
        if not isinstance(meta.get(key), str) or not meta.get(key):
            problems.append(f"meta.{key} missing")
    if not isinstance(meta.get("pricing"), dict):
        problems.append("meta.pricing missing")
    ds = meta.get("dataset")
    if not (isinstance(ds, dict) and ds.get("name") and ds.get("revision")):
        problems.append("meta.dataset.name/revision missing")
    arm = meta.get("arm")
    if arm not in LOOP_ARMS:
        problems.append(f"meta.arm {arm!r} is not one of {LOOP_ARMS}")
        return problems
    arms = doc.get("arms")
    if not isinstance(arms, dict) or list(arms) != [arm]:
        return problems + [f"arms must hold exactly {arm!r}"]
    block = arms[arm]
    model = block.get("model") if isinstance(block, dict) else None
    if not isinstance(model, str) or not model:
        problems.append("arms.<arm>.model missing")
    elif meta.get("model") not in (model, "openrouter/" + model):
        problems.append("meta.model does not match arms.<arm>.model")
    if not _is_num(block.get("total_wall_s")):
        problems.append("arms.<arm>.total_wall_s missing")
    tasks = block.get("tasks")
    if not (isinstance(tasks, list) and len(tasks) == 1 and isinstance(tasks[0], dict)):
        return problems + ["arms.<arm>.tasks must hold exactly one task"]
    task = tasks[0]
    if task.get("instance_id") != meta.get("instance_id"):
        problems.append("task.instance_id differs from meta.instance_id")
    if task.get("status") not in STATUSES:
        problems.append(f"task.status {task.get('status')!r} is not one of {STATUSES}")
    if not isinstance(task.get("success"), bool):
        problems.append("task.success must be a boolean")
    elif task["success"] and task.get("status") != "ok":
        problems.append("a run can only succeed with status ok")
    if not _is_num(task.get("wall_s")) or task["wall_s"] < 0:
        problems.append("task.wall_s missing or negative")
    totals = task.get("totals")
    if not isinstance(totals, dict):
        problems.append("task.totals missing")
    else:
        for key in ("prompt_tokens", "completion_tokens", "cached_tokens"):
            v = totals.get(key)
            if not _is_num(v) or v < 0:
                problems.append(f"task.totals.{key} missing or negative")
    return problems
