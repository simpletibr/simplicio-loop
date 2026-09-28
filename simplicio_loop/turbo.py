"""Turbo survey: one Mapper pass reused for every task in the run.

The DeepSeek harness cache rule (``request-cache.e2e.ts``) is separate and
lives in ``bench.llm_ab.report.run_prefix_cache_miss``. This module only
owns the Mapper stage: index once, then hand the same generation to each
later task.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

IndexFn = Callable[[Path], str]


def _default_index(root: Path) -> str:
    """Run the shipped Mapper index once and digest the project map it wrote.

    Mapper writes ``.simplicio/project-map.json``. An empty digest is not a
    survey, so a missing map fails instead of being cached.
    """
    import hashlib
    from .cli_impl import _ensure_project_map

    _ensure_project_map(root)
    candidates = (
        root / ".simplicio" / "project-map.json",
        root / ".simplicio-loop" / "project-map.json",
    )
    payload = b""
    for path in candidates:
        if path.is_file():
            payload = path.read_bytes()
            if payload:
                break
    if not payload:
        raise RuntimeError(f"mapper survey produced no project-map under {root}")
    return hashlib.sha256(payload).hexdigest()


def survey_tasks(
    root: Path,
    tasks: Sequence[Mapping[str, Any]],
    index: IndexFn | None = None,
) -> dict[str, Any]:
    """Survey ``root`` once and attach that generation to every task.

    A second call on an unchanged survey file does not call ``index`` again.
    """
    indexer = index or _default_index
    state_path = root / ".simplicio-loop" / "turbo-survey.json"
    if state_path.is_file():
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        generation = str(saved["generation"])
        indexed = False
    else:
        generation = str(indexer(root))
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"generation": generation}, ensure_ascii=False),
            encoding="utf-8",
        )
        indexed = True
    traces = [
        {"index": task.get("index"), "generation": generation, "reused": not indexed or i > 0}
        for i, task in enumerate(tasks)
    ]
    # The first task of a fresh survey is the one that paid for the index.
    if indexed and traces:
        traces[0]["reused"] = False
    return {
        "generation": generation,
        "indexed": indexed,
        "tasks": traces,
    }


_PLANNER_SYSTEM = (
    "You plan simplicio edits. Reply with JSON only, no prose: "
    '{"operations":[{"path":"relative/path","find":"","replace":"file text"}]}. '
    "An empty find creates the file. A non-empty find must match once. "
    "Do not mention tools or steps."
)


# Wave turbo starts above three tasks: each lane is the same read -> AI -> dev-cli path.
WAVE_TURBO_ABOVE = 3
_MAPPER_READING_LIMIT = 12000


def mapper_reading(root: Path) -> str:
    """The Mapper project map. This is the only repo reading sent to the model."""
    for path in (
        root / ".simplicio" / "project-map.json",
        root / ".simplicio-loop" / "project-map.json",
    ):
        if path.is_file() and path.stat().st_size:
            return path.read_text(encoding="utf-8")[:_MAPPER_READING_LIMIT]
    raise RuntimeError(f"mapper survey produced no project-map under {root}")


def _parse_operations(content: str) -> list[dict]:
    import json
    import re
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    payload = json.loads(text)
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list) or not operations:
        raise ValueError("the model did not return operations")
    return operations


def _dev_cli_bin() -> str:
    import os
    import shutil
    import sys
    candidate = os.path.join(os.path.dirname(sys.executable), "simplicio-dev-cli")
    if os.path.isfile(candidate):
        return candidate
    found = shutil.which("simplicio-dev-cli")
    if not found:
        raise RuntimeError("simplicio-dev-cli is not installed")
    return found



def _messages(reading: str, generation: str, tasks: Sequence[Mapping[str, Any]]) -> list[dict]:
    task_lines = "\n".join(f"{task.get('index')}. {task.get('text')}" for task in tasks)
    return [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": (
            f"Mapper survey generation {generation}.\n"
            f"Mapper project map:\n{reading}\n\nTasks:\n{task_lines}"
        )},
    ]


def _call_record(reply: Mapping[str, Any], turn: int) -> dict[str, Any]:
    return {
        "ok": bool(reply.get("ok", True)),
        "turn": turn,
        "prompt_tokens": reply.get("prompt_tokens") or 0,
        "completion_tokens": reply.get("completion_tokens") or 0,
        "reasoning_tokens": reply.get("reasoning_tokens") or 0,
        "cached_tokens": reply.get("cached_tokens") or 0,
        "cost_usd": reply.get("cost"),
    }


def _apply_operations(root: Path, operations: list[dict], binary: str, label: str) -> list[dict]:
    import json
    import subprocess
    import threading
    state = root / ".simplicio-loop"
    state.mkdir(parents=True, exist_ok=True)
    ops_path = state / f"turbo-ops-{label}.json"
    plan_path = state / f"turbo-plan-{label}.json"
    ops_path.write_text(json.dumps({"operations": operations}, ensure_ascii=False), encoding="utf-8")
    compile_cmd = [binary, "edit", "--root", str(root), "--plan", str(ops_path), "--compile", str(plan_path), "--json", "--no-runtime"]
    apply_cmd = [binary, "edit", "--root", str(root), "--plan", str(plan_path), "--apply", "--json", "--no-runtime"]
    commands = []
    with _apply_lock:
        for cmd in (compile_cmd, apply_cmd):
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            commands.append({"command": " ".join(cmd), "returncode": proc.returncode, "stdout": (proc.stdout or "")[-500:]})
            if proc.returncode != 0:
                break
    return commands


_apply_lock = __import__("threading").Lock()


def _one_lane(root: Path, tasks: Sequence[Mapping[str, Any]], complete, reading: str, generation: str, binary: str, turn: int) -> tuple[dict, list[dict], str]:
    messages = _messages(reading, generation, tasks)
    reply = complete("simplicio", messages)
    content = reply.get("content") or ""
    operations = _parse_operations(content) if reply.get("ok", True) else []
    commands = _apply_operations(root, operations, binary, str(turn)) if operations else []
    return _call_record(reply, turn), commands, content


def run_turbo(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Mapper reads once. Up to 3 tasks share one model call. Above that, asyncio lanes."""
    import asyncio
    survey = survey_tasks(root, tasks)
    reading = mapper_reading(root)
    binary = dev_cli or _dev_cli_bin()
    task_list = list(tasks)
    if len(task_list) <= WAVE_TURBO_ABOVE:
        call, commands, content = _one_lane(root, task_list, complete, reading, survey["generation"], binary, 1)
        calls = [call]
    else:
        async def _gather():
            async def _run(index: int, task: Mapping[str, Any]):
                return await asyncio.to_thread(
                    _one_lane, root, [task], complete, reading, survey["generation"], binary, index
                )
            return await asyncio.gather(*[_run(index, task) for index, task in enumerate(task_list, start=1)])
        lanes = asyncio.run(_gather())
        calls = [lane[0] for lane in lanes]
        commands = [cmd for lane in lanes for cmd in lane[1]]
        content = "\n".join(lane[2] for lane in lanes)
    return {
        "turns": len(calls),
        "llm_calls": calls,
        "commands": commands,
        "final_text": content,
        "totals": {
            "prompt_tokens": sum(call["prompt_tokens"] for call in calls),
            "completion_tokens": sum(call["completion_tokens"] for call in calls),
            "reasoning_tokens": sum(call["reasoning_tokens"] for call in calls),
            "cached_tokens": sum(call["cached_tokens"] for call in calls),
            "n_commands": len(commands),
            "n_simplicio_commands": len(commands),
        },
        "survey": survey,
        "wave": len(task_list) > WAVE_TURBO_ABOVE,
    }


def run_read_ai_devcli(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Read with Mapper, ask the model, apply with dev-cli."""
    return run_turbo(root, tasks, complete, dev_cli=dev_cli)
