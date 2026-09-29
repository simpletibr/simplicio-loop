"""Turbo survey: one Mapper pass reused for every task in the run.

The DeepSeek harness cache rule (``request-cache.e2e.ts``) is separate and
lives in ``bench.llm_ab.report.run_prefix_cache_miss``. This module only
owns the Mapper stage: index once, then hand the same generation to each
later task.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

IndexFn = Callable[[Path], str]
_clock = time.monotonic  # the run deadline is measured with this (a test replaces it)


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


_MAPPER_READING_LIMIT = 12000


SLICE_ENV = "SIMPLICIO_TURBO_SLICE"


def slice_enabled() -> bool:
    import os

    return os.environ.get(SLICE_ENV, "1").strip() != "0"


def focus_paths(tasks: Sequence[Mapping[str, Any]]) -> list[str]:
    paths: list[str] = []
    for task in tasks:
        for name in [task.get("target"), *(task.get("context") or [])]:
            if name and str(name) not in paths:
                paths.append(str(name))
    return paths


def mapper_reading(root: Path, focus: Sequence[str] | None = None) -> str:
    """The Mapper project map. This is the only repo reading sent to the model.

    With ``focus`` (a single task) only the map entries for those files are kept, plus the
    small top-level fields: one call cannot reuse a cached header, so the full map would be
    paid uncached for nothing (measured on the benchmark fixture: 3,294 map tokens -> ~340).
    """
    path = root / ".simplicio-loop" / "project-map.json"
    if not (path.is_file() and path.stat().st_size):
        raise RuntimeError(f"mapper survey produced no project-map under {root}")
    text = path.read_text(encoding="utf-8")
    if focus:
        try:
            project = json.loads(text)
        except ValueError:
            project = None
        if isinstance(project, dict):
            wanted = [str(p) for p in focus if p]
            sliced = {k: v for k, v in project.items() if k != "files" and len(json.dumps(v)) <= 400}
            sliced["files"] = [
                entry for entry in project.get("files") or []
                if any(name in json.dumps(entry) for name in wanted)
            ]
            return json.dumps(sliced, separators=(",", ":"))[:_MAPPER_READING_LIMIT]
    return text[:_MAPPER_READING_LIMIT]


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
        raise ValueError("the plan has no operations")
    return operations


def load_operations(text: str) -> list[dict]:
    """Parse the plan a host model wrote: ``{"operations":[{"path","find","replace"}]}``.

    ``find`` may be absent or empty (create the file). Anything else that is not a string is refused here,
    so a malformed plan is reported before dev-cli is called.
    """
    operations = _parse_operations(text)
    for number, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise ValueError(f"operation {number} is not an object")
        path = operation.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"operation {number} needs a string path")
        if not isinstance(operation.get("find", ""), str) or not isinstance(operation.get("replace"), str):
            raise ValueError(f"operation {number} needs a string find and a string replace")
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


FILE_CHARS = 6000


def current_files(root: Path, tasks: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """The current text of every existing target and context file, each once, in task order.

    A file past ``FILE_CHARS`` is cut and the last line says so, so a model that needs the rest knows to read it.
    """
    files: dict[str, str] = {}
    for task in tasks:
        for name in [task.get("target"), *(task.get("context") or [])]:
            path = root / str(name) if name else None
            if not name or str(name) in files or path is None or not path.is_file():
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            cut = len(body) - FILE_CHARS
            files[str(name)] = body if cut <= 0 else body[:FILE_CHARS] + f"\n[truncated: {cut} more characters not shown]"
    return files


def task_message(tasks: Sequence[Mapping[str, Any]], root: Path | None = None) -> dict[str, str]:
    """Task text plus the current target bytes. This is the suffix, not the header."""
    parts = []
    for task in tasks:
        parts.append(f"{task.get('index')}. {task.get('text')}")
        if root is None:
            continue
        for name in [task.get("target"), *(task.get("context") or [])]:
            path = root / str(name) if name else None
            if path is not None and path.is_file():
                body = path.read_text(encoding="utf-8", errors="replace")[:FILE_CHARS]
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
        "hedged": bool(reply.get("hedged")),
        "hedge_winner": reply.get("hedge_winner"),
    }


def _fatal_of(reply: Mapping[str, Any]) -> dict[str, str]:
    """The cause of a reply the engine must not retry (``fatal``: the host CLI, not the plan, failed)."""
    return {"reason_code": str(reply.get("reason_code") or "host_error"), "detail": str(reply.get("error") or "")}


def _skipped(task: Mapping[str, Any], stopped: Mapping[str, str]) -> dict[str, Any]:
    return {"tasks": [int(task.get("index") or 0)], "applied": False, "skipped": True,
            "reason": f"not attempted: {stopped['reason_code']}"}


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


def apply_plan(root: Path, operations: list[dict], label: str = "host-1", dev_cli: str | None = None) -> dict[str, Any]:
    """Apply one find/replace plan through simplicio-dev-cli. ``reason`` is dev-cli's own message on refusal."""
    commands = _apply_operations(root, operations, dev_cli or _dev_cli_bin(), label)
    reason = _rejection(commands)
    return {"applied": reason is None, "reason": reason, "commands": commands}


def _one_lane(root: Path, tasks: Sequence[Mapping[str, Any]], complete, reading: str, binary: str, turn: int
              ) -> tuple[list[dict], list[dict], str, dict]:
    """One component, one model call. If dev-cli rejects the plan, send that error back one time."""
    messages = [header_message(reading), task_message(tasks, root)]
    calls: list[dict] = []
    commands: list[dict] = []
    content = ""
    applied_ok, reason, fatal = False, None, None
    for attempt in (1, 2):
        reply = complete("simplicio", messages)
        content = reply.get("content") or ""
        calls.append(_call_record(reply, len(calls) + 1))
        if reply.get("fatal"):
            fatal = _fatal_of(reply)
            reason = fatal["detail"] or fatal["reason_code"]
            break
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
    outcome = {"tasks": [int(t.get("index") or 0) for t in tasks], "applied": applied_ok, "reason": reason}
    if fatal:
        outcome["fatal"] = fatal
    return calls, commands, content, outcome


def _components(tasks: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Tasks that depend on each other (``depends_on``, which ``build_tasks`` also sets for a shared file) are one component."""
    parent = {int(task.get("index") or 0): int(task.get("index") or 0) for task in tasks}

    def root_of(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for task in tasks:
        for dep in task.get("depends_on") or []:
            if int(dep) in parent:
                parent[root_of(int(dep))] = root_of(int(task.get("index") or 0))
    groups: dict[int, list[Mapping[str, Any]]] = {}
    for task in tasks:
        groups.setdefault(root_of(int(task.get("index") or 0)), []).append(task)
    return list(groups.values())


def run_turbo(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None,
              deadline: float | None = None) -> dict[str, Any]:
    """Mapper reads once. Each dependency component is ONE model call; components that do not depend on each other run together.

    The model calls overlap (asyncio); dev-cli applies one plan at a time. ``stopped`` is None for a run that asked every
    component, else ``{"reason_code", "detail"}``: a reply marked ``fatal`` (a host failure, not a bad plan) or a
    ``deadline`` (a ``time.monotonic()`` value) already spent when the run starts. What the other components applied stays.
    """
    import asyncio
    survey = survey_tasks(root, tasks)
    task_list = list(tasks)
    reading = mapper_reading(root, focus=focus_paths(tasks) if len(task_list) == 1 and slice_enabled() else None)
    binary = dev_cli or _dev_cli_bin()
    calls: list[dict] = []
    commands: list[dict] = []
    contents: list[str] = []
    outcomes: list[dict] = []
    if deadline is not None and _clock() >= deadline:
        stopped: dict[str, str] | None = {"reason_code": "budget", "detail": "the time budget is spent"}
        outcomes = [_skipped(task, stopped) for task in task_list]
    else:
        async def _fan_out():
            return await asyncio.gather(*(
                asyncio.to_thread(_one_lane, root, group, complete, reading, binary, turn)
                for turn, group in enumerate(_components(task_list), 1)
            ))

        for lane_calls, lane_commands, content, outcome in asyncio.run(_fan_out()):
            calls.extend(lane_calls)
            commands.extend(lane_commands)
            contents.append(content)
            outcomes.append(outcome)
        for number, call in enumerate(calls, 1):
            call["turn"] = number
        stopped = next((outcome["fatal"] for outcome in outcomes if outcome.get("fatal")), None)
    return {
        "turns": len(calls),
        "llm_calls": calls,
        "commands": commands,
        "final_text": "\n".join(contents),
        "totals": {
            "prompt_tokens": sum(call["prompt_tokens"] for call in calls),
            "completion_tokens": sum(call["completion_tokens"] for call in calls),
            "reasoning_tokens": sum(call["reasoning_tokens"] for call in calls),
            "cached_tokens": sum(call["cached_tokens"] for call in calls),
            "n_commands": len(commands),
            "n_simplicio_commands": len(commands),
        },
        "survey": survey,
        "outcomes": outcomes,
        "stopped": stopped,
        "applied_all": all(outcome["applied"] for outcome in outcomes),
    }


def _rewrite_existing_creates(root: Path, operations: list[dict]) -> list[dict]:
    """Turn a create (empty ``find``) of a file that already exists into a whole-file replacement.

    The repair runs after the first plan was applied, so a task that created a file is answered with the same
    create again, and dev-cli refuses it (``create_target_exists``). ``find`` becomes the file's current text,
    read as bytes so its own line endings survive. What cannot be a whole-file find stays as it is and dev-cli
    decides: a real ``find``, a new file, an empty file, a path outside the repository, a file that is not UTF-8.
    """
    base = root.resolve()
    rewritten = []
    for operation in operations:
        target = (base / str(operation.get("path", ""))).resolve()
        if operation.get("find") or not target.is_relative_to(base) or not target.is_file():
            rewritten.append(operation)
            continue
        try:
            current = target.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            current = ""
        rewritten.append({**operation, "find": current} if current else operation)
    return rewritten


def repair_with_test_output(root: Path, tasks: Sequence[Mapping[str, Any]], complete, test_output: str,
                            dev_cli: str | None = None) -> dict[str, Any]:
    """One more call after the tests failed: the same header, the current files and the test output.

    The header is byte-identical to the run's, so the provider serves it from cache. The files the task named
    exist by now, so the prompt says so, and an empty ``find`` for one of them is sent as a whole-file replacement
    (see ``_rewrite_existing_creates``); this is the only path that rewrites a plan.
    """
    task_list = list(tasks)
    single = len(task_list) == 1
    reading = mapper_reading(root, focus=focus_paths(task_list) if single and slice_enabled() else None)
    binary = dev_cli or _dev_cli_bin()
    messages = [
        header_message(reading),
        task_message(task_list, root),
        {"role": "user", "content": "The tests failed after your plan was applied:\n" + test_output[-4000:]
         + "\nNote: the files above already exist; to rewrite one, send its whole current text as find."
         + "\nReturn a JSON plan that makes them pass."},
    ]
    reply = complete("simplicio", messages)
    if reply.get("fatal"):
        fatal = _fatal_of(reply)
        return {"llm_calls": [_call_record(reply, 1)], "commands": [], "applied": False,
                "reason": fatal["detail"] or fatal["reason_code"], "fatal": fatal}
    try:
        operations = _parse_operations(reply.get("content") or "") if reply.get("ok", True) else []
        reason = None
    except (ValueError, json.JSONDecodeError) as exc:
        operations, reason = [], str(exc)
    operations = _rewrite_existing_creates(root, operations)
    applied = _apply_operations(root, operations, binary, "repair-1") if operations else []
    rejected = _rejection(applied)
    return {
        "llm_calls": [_call_record(reply, 1)],
        "commands": applied,
        "applied": bool(operations) and rejected is None,
        "reason": None if operations and rejected is None else (rejected or reason or "the model returned no plan"),
    }


def run_read_ai_devcli(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Read with Mapper, ask the model, apply with dev-cli."""
    return run_turbo(root, tasks, complete, dev_cli=dev_cli)
