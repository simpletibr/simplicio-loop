"""Turbo survey: one Mapper pass reused for every task in the run.

The DeepSeek harness cache rule (``request-cache.e2e.ts``) is separate and
lives in ``bench.llm_ab.report.run_prefix_cache_miss``. This module only
owns the Mapper stage: index once, then hand the same generation to each
later task.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from . import operator_exec, plan_paths, turbo_window

IndexFn = Callable[[Path], Awaitable[str]]


async def _default_index(root: Path) -> str:
    """Run the shipped Mapper index once and digest the project map it wrote.

    Mapper writes ``.simplicio-loop/project-map.json``. An empty digest is not a
    survey, so a missing map fails instead of being cached.
    """
    import hashlib
    from .cli_impl import _ensure_project_map

    # Let MapperIndexError propagate up, don't swallow it
    await _ensure_project_map(root)
    path = root / ".simplicio-loop" / "project-map.json"
    payload = path.read_bytes() if path.is_file() else b""
    if not payload:
        raise RuntimeError(f"mapper survey produced no project-map under {root}")
    return hashlib.sha256(payload).hexdigest()


async def survey_tasks(
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
        generation = str(await indexer(root))
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
# Bump the version whenever _PLANNER_SYSTEM changes; the digest pins the exact template text a run used.
PLAN_PROMPT_VERSION = "turbo-plan/v1"
NO_RECEIPT = "no_apply_receipt"
RECEIPT_SCHEMAS = ("simplicio.dev-cli.edit-receipt/v1", "simplicio.mechanical-edit-result/v1")


def plan_prompt() -> dict[str, str]:
    """The plan prompt's version and the sha256 of its template text."""
    return {
        "prompt_version": PLAN_PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(_PLANNER_SYSTEM.encode("utf-8")).hexdigest(),
    }


def parse_apply_receipt(stdout: str) -> dict | None:
    """The dev-cli receipt in ``edit --apply`` output: the JSON object with ``applied: true`` and a receipt schema.

    dev-cli may print human text before its JSON, so every ``{`` is tried, outermost object first.
    """
    decoder = json.JSONDecoder()
    for start, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(stdout, start)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("applied") is True and obj.get("schema") in RECEIPT_SCHEMAS:
            return obj
    return None


# Wave turbo starts above three tasks: each lane is the same read -> AI -> dev-cli path.
WAVE_TURBO_ABOVE = 3
_MAPPER_READING_LIMIT = 12000


SLICE_ENV = "SIMPLICIO_TURBO_SLICE"
_WARM_MESSAGE = {"role": "user", "content": "Reply with OK."}


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


def _payload(content: str) -> Any:
    """The JSON a model reply holds (a fence or prose around it is tolerated)."""
    import re
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def load_need(text: str) -> list[dict]:
    """The lines a plan asks for instead of editing, ``{"operations": [], "need": [{"path","start","end"}]}``; ``[]`` for a plan."""
    payload = _payload(text)
    if not isinstance(payload, dict) or payload.get("operations"):
        return []
    return turbo_window.parse_need(payload.get("need"))


class EmptyPlanError(ValueError):
    """The plan holds no operations."""


def _parse_operations(content: str) -> list[dict]:
    payload = _payload(content)
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list) or not operations:
        raise EmptyPlanError("the plan has no operations")
    for number, operation in enumerate(operations, start=1):
        path = operation.get("path") if isinstance(operation, dict) else None
        if isinstance(path, str) and (reason := plan_paths.refusal(path)):
            raise ValueError(f"operation {number}: {reason}")
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
        for fallback in ("/usr/local/bin/simplicio-dev-cli", os.path.expanduser("~/.local/bin/simplicio-dev-cli")):
            if os.path.isfile(fallback):
                return fallback
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


def current_files(root: Path, tasks: Sequence[Mapping[str, Any]], windows: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The current text of every existing target and context file, each once, in task order (``turbo_window``).

    A file that fits is its text. A bigger one is a window object around what the tasks name, with the omitted line
    ranges (#1643); ``windows`` are the lines the caller asked for.
    """
    return turbo_window.build_files(root, tasks, windows)


def task_message(tasks: Sequence[Mapping[str, Any]], root: Path | None = None) -> dict[str, str]:
    """Task text plus the current target bytes. This is the suffix, not the header."""
    parts = []
    files = turbo_window.build_files(root, tasks) if root is not None else {}
    for task in tasks:
        parts.append(f"{task.get('index')}. {task.get('text')}")
        for name in [task.get("target"), *(task.get("context") or [])]:
            entry = files.get(str(name)) if name else None
            if entry is not None:
                parts.append(f"Current {name}:\n{entry}" if isinstance(entry, str) else turbo_window.provider_text(str(name), entry))
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
        "usage_reported": bool(reply.get("usage_reported")),
        "latency_s": reply.get("latency_s"),
        "provider": reply.get("provider"),
        "hedged": bool(reply.get("hedged")),
        "hedge_winner": reply.get("hedge_winner"),
    }


async def _apply_operations(root: Path, operations: list[dict], binary: str, label: str, apply_lock: asyncio.Lock) -> list[dict]:
    import json
    if reason := plan_paths.operations_refusal(operations, root):  # followed through symlinks: an old dev-cli does not
        return [{"command": "plan_paths", "returncode": 1, "stdout": reason, "label": label}]
    state = root / ".simplicio-loop"
    state.mkdir(parents=True, exist_ok=True)
    ops_path = state / f"turbo-ops-{label}.json"
    plan_path = state / f"turbo-plan-{label}.json"
    ops_path.write_text(json.dumps({"operations": operations}, ensure_ascii=False), encoding="utf-8")
    compile_cmd = [binary, "edit", "--root", str(root), "--plan", str(ops_path), "--compile", str(plan_path), "--json", "--no-runtime"]
    apply_cmd = [binary, "edit", "--root", str(root), "--plan", str(plan_path), "--apply", "--json", "--no-runtime"]
    commands = []
    async with apply_lock:
        for cmd in (compile_cmd, apply_cmd):
            try:
                returncode, stdout_str, stderr_str = await operator_exec.run(cmd, timeout=120)
            except subprocess.TimeoutExpired:
                detail = "dev-cli timed out after 120s"
                commands.append({"command": " ".join(cmd), "returncode": -1, "stdout": detail, "label": label})
                break
            detail = (stdout_str + stderr_str)[-800:]
            entry = {"command": " ".join(cmd), "returncode": returncode, "stdout": detail, "label": label}
            if cmd is apply_cmd:
                entry["receipt"] = parse_apply_receipt(stdout_str) if returncode == 0 else None
            commands.append(entry)
            if returncode != 0:
                break
    return commands


def _rejection(commands: list[dict]) -> str | None:
    for command in commands:
        if command["returncode"] != 0:
            return command.get("stdout") or f"dev-cli exited {command['returncode']}"
    return None


def _verdict(operations: list[dict], commands: list[dict]) -> tuple[bool, str | None]:
    """(applied, reason). A plan counts as applied only when dev-cli refused nothing AND its apply left a receipt.

    The agent's text never decides success: without the dev-cli receipt the answer is ``NO_RECEIPT``.
    """
    if not operations:
        return False, None
    refusal = _rejection(commands)
    if refusal is not None:
        return False, refusal
    if not commands or commands[-1].get("receipt") is None:
        return False, NO_RECEIPT
    return True, None


async def apply_plan(root: Path, operations: list[dict], label: str = "host-1", dev_cli: str | None = None, apply_lock: asyncio.Lock | None = None) -> dict[str, Any]:
    """Apply one find/replace plan through simplicio-dev-cli. ``reason`` is dev-cli's own message on refusal."""
    if apply_lock is None:
        apply_lock = asyncio.Lock()
    commands = await _apply_operations(root, operations, dev_cli or _dev_cli_bin(), label, apply_lock)
    applied, reason = _verdict(operations, commands)
    return {"applied": applied, "reason": reason, "commands": commands}


async def _one_lane(root: Path, tasks: Sequence[Mapping[str, Any]], complete, reading: str, generation: str, binary: str, turn: int, base: list[dict] | None = None, apply_lock: asyncio.Lock | None = None) -> tuple[list[dict], list[dict], str, list[dict], dict]:
    """Ask once. If dev-cli rejects the plan, send that error back one time."""
    if apply_lock is None:
        apply_lock = asyncio.Lock()
    messages = [*(base if base is not None else [header_message(reading)]), task_message(tasks, root)]
    calls: list[dict] = []
    commands: list[dict] = []
    content = ""
    applied_ok, reason = False, None
    for attempt in (1, 2):
        reply = await complete("simplicio", messages)
        content = reply.get("content") or ""
        calls.append(_call_record(reply, len(calls) + 1 if turn == 1 else turn))
        try:
            operations = _parse_operations(content) if reply.get("ok", True) else []
        except (ValueError, json.JSONDecodeError) as exc:
            operations = []
            reason = str(exc)
        else:
            reason = None
        applied = await _apply_operations(root, operations, binary, f"{turn}-{attempt}", apply_lock) if operations else []
        commands.extend(applied)
        applied_ok, refusal = _verdict(operations, applied)
        if not applied_ok:
            reason = refusal or reason or (str(reply.get("error")) if not reply.get("ok", True) else None) \
                or "the model returned no plan"
        if applied_ok:
            reason = None
            break
        if attempt == 2:
            break
        detail = refusal or reason or "dev-cli did not apply a plan"
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


async def _wave_task(root: Path, task: Mapping[str, Any], messages: list[dict], complete, binary: str,
                     apply_lock: asyncio.Lock) -> tuple[list[dict], list[dict], str, dict]:
    """One fanned-out task: ask, apply under the lock, and on a refusal send it back once."""
    calls: list[dict] = []
    commands: list[dict] = []
    content, reason, applied_ok = "", None, False
    for attempt in (1, 2):
        reply = await complete("simplicio", messages)
        content = reply.get("content") or ""
        calls.append(_call_record(reply, 0))
        try:
            operations = _parse_operations(content) if reply.get("ok", True) else []
            reason = None
        except (ValueError, json.JSONDecodeError) as exc:
            operations, reason = [], str(exc)
        applied = await _apply_operations(root, operations, binary, f"wave-{task.get('index')}-{attempt}", apply_lock) if operations else []
        commands.extend(applied)
        applied_ok, refusal = _verdict(operations, applied)
        if applied_ok:
            reason = None
            break
        reason = refusal or reason or str(reply.get("error") or "the model returned no plan")
        if attempt == 1:
            messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "user", "content": "dev-cli rejected the plan:\n" + reason + "\nReturn a corrected JSON plan."},
            ]
    outcome = {"tasks": [int(task.get("index") or 0)], "applied": applied_ok, "reason": reason}
    return calls, commands, content, outcome


async def _run_wave(root: Path, tasks: Sequence[Mapping[str, Any]], complete, reading: str, generation: str, binary: str,
                    apply_lock: asyncio.Lock) -> tuple[list[dict], list[dict], str, list[dict]]:
    """First call runs alone so the header is cached. Later calls append or fan out after it."""
    pending = list(tasks)
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
        if not calls and len(ready) > 1:
            # Independent tasks: a 1-token call writes the header into the provider's cache,
            # then every ready task fans out at once instead of waiting for a whole first task.
            warm = await complete("simplicio", [header_message(reading), _WARM_MESSAGE], max_tokens=1)
            calls.append({**_call_record(warm, 0), "warm": True})
        elif not calls or len(ready) == 1:
            task = ready[0]
            lane_calls, lane_commands, content, stack, outcome = await _one_lane(
                root, [task], complete, reading, generation, binary, len(calls) + 1, base=stack, apply_lock=apply_lock,
            )
            outcomes.append(outcome)
            calls.extend(lane_calls)
            commands.extend(lane_commands)
            contents.append(content)
            done.add(int(task.get("index") or 0))
            pending.remove(task)
            continue
        base = list(stack)
        # The prompts are built before any plan is applied; the model calls run together (bounded by the
        # caller's semaphore) and dev-cli applies one plan at a time (apply_lock).
        lanes = await asyncio.gather(*(
            _wave_task(root, task, [*base, task_message([task], root)], complete, binary, apply_lock)
            for task in ready
        ))
        for task, (lane_calls, lane_commands, content, outcome) in zip(ready, lanes):
            first = len(calls) + 1
            calls.extend({**record, "turn": first + i} for i, record in enumerate(lane_calls))
            commands.extend(lane_commands)
            contents.append(content)
            outcomes.append(outcome)
            done.add(int(task.get("index") or 0))
            pending.remove(task)
    return calls, commands, "\n".join(contents), outcomes


async def run_turbo(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Mapper reads once. Up to 3 tasks share one model call. Above that, the first call warms the header and the rest follow.

    Any task count takes this one async path: model calls are bounded by an ``asyncio.Semaphore``
    (``SIMPLICIO_TURBO_CONCURRENCY``) and dev-cli applies never overlap (``asyncio.Lock``).
    """
    from . import turbo_provider

    survey = await survey_tasks(root, tasks)
    single = len(list(tasks)) == 1
    reading = mapper_reading(root, focus=focus_paths(tasks) if single and slice_enabled() else None)
    binary = dev_cli or _dev_cli_bin()
    task_list = list(tasks)
    semaphore = asyncio.Semaphore(turbo_provider.concurrency())
    apply_lock = asyncio.Lock()

    async def bounded(arm, messages, **kwargs):
        async with semaphore:
            return await complete(arm, messages, **kwargs)

    if len(task_list) <= WAVE_TURBO_ABOVE:
        calls, commands, content, _stack, outcome = await _one_lane(
            root, task_list, bounded, reading, survey["generation"], binary, 1, apply_lock=apply_lock,
        )
        outcomes = [outcome]
    else:
        calls, commands, content, outcomes = await _run_wave(
            root, task_list, bounded, reading, survey["generation"], binary, apply_lock,
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


async def repair_with_test_output(root: Path, tasks: Sequence[Mapping[str, Any]], complete, test_output: str,
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
    apply_lock = asyncio.Lock()
    messages = [
        header_message(reading),
        task_message(task_list, root),
        {"role": "user", "content": "The tests failed after your plan was applied:\n" + test_output[-4000:]
         + "\nNote: the files above already exist; to rewrite one, send its whole current text as find."
         + "\nReturn a JSON plan that makes them pass."},
    ]
    reply = await complete("simplicio", messages)
    try:
        operations = _parse_operations(reply.get("content") or "") if reply.get("ok", True) else []
        reason = None
    except (ValueError, json.JSONDecodeError) as exc:
        operations, reason = [], str(exc)
    operations = _rewrite_existing_creates(root, operations)
    applied = await _apply_operations(root, operations, binary, "repair-1", apply_lock) if operations else []
    ok, refusal = _verdict(operations, applied)
    return {
        "llm_calls": [_call_record(reply, 1)],
        "commands": applied,
        "applied": ok,
        "reason": None if ok else (refusal or reason or "the model returned no plan"),
    }


async def run_read_ai_devcli(root: Path, tasks: Sequence[Mapping[str, Any]], complete, dev_cli: str | None = None) -> dict[str, Any]:
    """Read with Mapper, ask the model, apply with dev-cli."""
    return await run_turbo(root, tasks, complete, dev_cli=dev_cli)
