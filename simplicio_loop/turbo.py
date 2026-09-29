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

    Mapper writes ``.simplicio-loop/project-map.json``. An empty digest is not a
    survey, so a missing map fails instead of being cached.
    """
    import hashlib
    from .cli_impl import _ensure_project_map

    _ensure_project_map(root)
    path = root / ".simplicio-loop" / "project-map.json"
    payload = path.read_bytes() if path.is_file() else b""
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
    path = root / ".simplicio-loop" / "project-map.json"
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



def header_message(reading: str) -> dict[str, str]:
    """Fixed header. The planner text and the Mapper map never change.

    Each later call appends after this message. The header stays
    byte-identical, so the provider can cache it.
    """
    return {
        "role": "system",
        "content": _PLANNER_SYSTEM + "\n\nMapper project map:\n" + reading,
    }


def _task_message(tasks: Sequence[Mapping[str, Any]], root: Path | None = None) -> dict[str, str]:
    """Task text plus the current target bytes. This is the suffix, not the header."""
    parts = []
    for task in tasks:
        parts.append(f"{task.get('index')}. {task.get('text')}")
        if root is None:
            continue
        for name in [task.get("target"), *(task.get("context") or [])]:
            path = root / str(name) if name else None
            if path is not None and path.is_file():
                body = path.read_text(encoding="utf-8", errors="replace")[:6000]
                parts.append(f"Current {name}:\n{body}")
    return {"role": "user", "content": "Tasks:\n" + "\n".join(parts)}


def _call_record(reply: Mapping[str, Any], turn: int) -> dict[str, Any]:
    return {
        "ok": bool(reply.get("ok", True)),
        "turn": turn,
        "prompt_tokens": reply.get("prompt_tokens") or 0,
        "completion_tokens": reply.get("completion_tokens") or 0,
        "reasoning_tokens": reply.get("reasoning_tokens") or 0,
        "cached_tokens": reply.get("cached_tokens") or 0,
        "cost_usd": reply.get("cost"),
        "latency_s": reply.get("latency_s"),
        "provider": reply.get("provider"),
    }


def _apply_operations(root: Path, operations: list[dict], binary: str, label: str) -> list[dict]:
    import json
    import subprocess
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
            detail = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
            commands.append({"command": " ".join(cmd), "returncode": proc.returncode, "stdout": detail})
            if proc.returncode != 0:
                break
    return commands


_apply_lock = __import__("threading").Lock()


def _rejection(commands: list[dict]) -> str | None:
    for command in commands:
        if command["returncode"] != 0:
            return command.get("stdout") or f"dev-cli exited {command['returncode']}"
    return None


def _one_lane(root: Path, tasks: Sequence[Mapping[str, Any]], complete, reading: str, generation: str, binary: str, turn: int, base: list[dict] | None = None) -> tuple[list[dict], list[dict], str, list[dict]]:
    """Ask once. If dev-cli rejects the plan, send that error back one time."""
    messages = [*(base if base is not None else [header_message(reading)]), _task_message(tasks, root)]
    calls: list[dict] = []
    commands: list[dict] = []
    content = ""
    applied_ok, reason = False, None
    for attempt in (1, 2):
        reply = complete("simplicio", messages)
        content = reply.get("content") or ""
        calls.append(_call_record(reply, len(calls) + 1 if turn == 1 else turn))
        try:
            operations = _parse_operations(content) if reply.get("ok", True) else []
        except (ValueError, json.JSONDecodeError) as exc:
            operations = []
            reason = str(exc)
        else:
            reason = None
        applied = _apply_operations(root, operations, binary, f"{turn}-{attempt}") if operations else []
        commands.extend(applied)
        rejected = _rejection(applied)
        applied_ok = bool(operations) and rejected is None
        if not applied_ok:
            reason = rejected or reason or (str(reply.get("error")) if not reply.get("ok", True) else None) \
                or "the model returned no plan"
        if applied_ok:
            reason = None
            break
        if attempt == 2:
            break
        detail = rejected or reason or "dev-cli did not apply a plan"
        messages = [
            *messages,
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"dev-cli rejected the plan:\n{detail}\nReturn a corrected JSON plan."},
        ]
    messages.append({"role": "assistant", "content": content})
    outcome = {"tasks": [int(t.get("index") or 0) for t in tasks], "applied": applied_ok, "reason": reason}
    return calls, commands, content, messages, outcome


def _ready(pending: list[Mapping[str, Any]], done: set[int]) -> list[Mapping[str, Any]]:
    ready = []
    for task in pending:
        deps = task.get("depends_on") or []
        if all(dep in done for dep in deps):
            ready.append(task)
    return ready


def _run_wave(root: Path, tasks: Sequence[Mapping[str, Any]], complete, reading: str, generation: str, binary: str) -> tuple[list[dict], list[dict], str]:
    """First call runs alone so the header is cached. Later calls append or fan out after it."""
    import asyncio
    pending = [task for task in tasks]
    done: set[int] = set()
    calls: list[dict] = []
    commands: list[dict] = []
    contents: list[str] = []
    outcomes: list[dict] = []
    stack = [header_message(reading)]
    while pending:
        ready = _ready(pending, done)
        if not ready:
            raise RuntimeError("turbo tasks have a dependency cycle")
        if not calls or len(ready) == 1:
            task = ready[0]
            lane_calls, lane_commands, content, stack, outcome = _one_lane(
                root, [task], complete, reading, generation, binary, len(calls) + 1, base=stack,
            )
            outcomes.append(outcome)
            calls.extend(lane_calls)
            commands.extend(lane_commands)
            contents.append(content)
            done.add(int(task.get("index") or 0))
            pending.remove(task)
            continue
        base = list(stack)

        def _ask(task: Mapping[str, Any]) -> tuple[Mapping[str, Any], list[dict], dict]:
            messages = [*base, _task_message([task], root)]
            reply = complete("simplicio", messages)
            return task, messages, reply

        async def _gather(ready_now=ready):
            return await asyncio.gather(*(asyncio.to_thread(_ask, task) for task in ready_now))

        # The model calls share the warmed header and run together.
        # dev-cli applies afterwards, one plan at a time.
        asked = asyncio.run(_gather())
        for task, messages, reply in asked:
            content = reply.get("content") or ""
            calls.append(_call_record(reply, len(calls) + 1))
            try:
                operations = _parse_operations(content) if reply.get("ok", True) else []
                reason = None
            except (ValueError, json.JSONDecodeError) as exc:
                operations = []
                reason = str(exc)
            applied = _apply_operations(root, operations, binary, f"wave-{task.get('index')}-1") if operations else []
            commands.extend(applied)
            rejected = _rejection(applied)
            outcome = {"tasks": [int(task.get("index") or 0)], "applied": bool(operations) and rejected is None,
                       "reason": None if operations and rejected is None else
                       (rejected or reason or str(reply.get("error") or "the model returned no plan"))}
            if not operations or rejected is not None:
                detail = rejected or reason or "dev-cli did not apply a plan"
                retry_messages = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": "dev-cli rejected the plan:\n" + detail + "\nReturn a corrected JSON plan."},
                ]
                retry = complete("simplicio", retry_messages)
                calls.append(_call_record(retry, len(calls) + 1))
                retry_content = retry.get("content") or ""
                try:
                    operations = _parse_operations(retry_content) if retry.get("ok", True) else []
                except (ValueError, json.JSONDecodeError):
                    operations = []
                applied = _apply_operations(root, operations, binary, f"wave-{task.get('index')}-2") if operations else []
                commands.extend(applied)
                content = retry_content
                retry_rejected = _rejection(applied)
                outcome = {"tasks": outcome["tasks"], "applied": bool(operations) and retry_rejected is None,
                           "reason": None if operations and retry_rejected is None else
                           (retry_rejected or str(retry.get("error") or "the model returned no plan"))}
            outcomes.append(outcome)
            contents.append(content)
            done.add(int(task.get("index") or 0))
            pending.remove(task)
    return calls, commands, "\n".join(contents), outcomes


def run_turbo(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Mapper reads once. Up to 3 tasks share one model call. Above that, the first call warms the header and the rest follow."""
    survey = survey_tasks(root, tasks)
    reading = mapper_reading(root)
    binary = dev_cli or _dev_cli_bin()
    task_list = list(tasks)
    if len(task_list) <= WAVE_TURBO_ABOVE:
        calls, commands, content, _stack, outcome = _one_lane(
            root, task_list, complete, reading, survey["generation"], binary, 1,
        )
        outcomes = [outcome]
    else:
        calls, commands, content, outcomes = _run_wave(
            root, task_list, complete, reading, survey["generation"], binary,
        )
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
        "outcomes": outcomes,
        "applied_all": all(outcome["applied"] for outcome in outcomes),
    }


def run_read_ai_devcli(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Read with Mapper, ask the model, apply with dev-cli."""
    return run_turbo(root, tasks, complete, dev_cli=dev_cli)
