"""`simplicio-loop turbo`: the default way to run a task.

Host mode (the default: no provider call, no key). The invoking model plans and simplicio-dev-cli applies:

1. ``turbo --task T`` surveys with Mapper and prints a ``needs_plan`` request: the map slice, the task and
   the current file text, plus the exact ``--apply`` command to run next.
2. The model writes a find/replace JSON plan to ``plan_path``; ``turbo --apply PLAN`` applies it through
   dev-cli and runs ``--verify``.

Provider mode (``--provider openrouter``, explicit): the headless benchmarked engine. One model call per
lane (``turbo_provider``: OpenRouter, pinned session, reasoning off), then dev-cli applies each plan.

The output is one compact JSON document. Exit code: 0 ok / needs_plan, 1 failed, 2 blocked.
"""
from __future__ import annotations

import difflib
import functools
import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "simplicio.turbo-run/v1"
REQUEST_SCHEMA = "simplicio.turbo-request/v1"
PLAN_PATH = ".simplicio-loop/turbo/plan.json"
REQUEST_PATH = ".simplicio-loop/turbo/request.json"
PLAN_FORMAT = {"operations": [{"path": "<repo-relative>",
                               "find": "<exact text that occurs once; empty creates the file>",
                               "replace": "<new text>"}]}
_EXCERPT_CHARS = 600
_CODE_EXTENSIONS = frozenset((
    "py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "html", "htm", "css", "scss", "md", "json", "yml",
    "yaml", "toml", "ini", "cfg", "txt", "go", "rs", "java", "kt", "rb", "php", "cs", "c", "h", "cpp",
    "hpp", "sh", "sql", "vue", "svelte", "swift", "dart", "lua", "xml",
))
_PATH_TOKEN = re.compile(r"(?<![\w/.-])((?:[\w-]+/)*[\w.-]*\w\.([A-Za-z][A-Za-z0-9]{0,7}))(?![\w/-])")


def mentioned_paths(text: str, root: Path) -> list[str]:
    """File paths named in the task text: existing files, or new files with a code extension."""
    found: list[str] = []
    for match in _PATH_TOKEN.finditer(text):
        path, extension = match.group(1), match.group(2).lower()
        if path in found:
            continue
        if (root / path).is_file() or extension in _CODE_EXTENSIONS:
            found.append(path)
    return found


def build_tasks(root: Path, texts: Sequence[str], target: str | None = None,
                context: Sequence[str] = (), tasks_file: str | None = None) -> list[dict[str, Any]]:
    if tasks_file:
        raw = json.loads(Path(tasks_file).read_text(encoding="utf-8"))
        specs = [dict(item) for item in raw]
    else:
        specs = [{"text": text} for text in texts]
        if len(specs) == 1 and (target or context):
            specs[0]["target"] = target
            specs[0]["context"] = list(context)
    tasks: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        named = mentioned_paths(str(spec["text"]), root)
        task_target = spec.get("target") or (named[0] if named else None)
        extra = [p for p in [*(spec.get("context") or []), *named] if p != task_target and (root / p).is_file()]
        task = {"index": index, "text": str(spec["text"]), "target": task_target,
                "context": list(dict.fromkeys(extra))}
        files = {task_target, *task["context"]} - {None}
        # Tasks that touch the same file stay in order; the rest can fan out.
        task["depends_on"] = spec.get("depends_on") or [
            earlier["index"] for earlier in tasks
            if files & ({earlier["target"], *earlier["context"]} - {None})
        ]
        tasks.append(task)
    return tasks


def _emit(document: dict[str, Any]) -> None:
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))


def _run_verify(root: Path, command: str) -> tuple[dict[str, Any], str]:
    """Run the verify command in the repo. Returns the report and the full output."""
    try:
        proc = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=900)  # noqa: S602
    except subprocess.TimeoutExpired:
        return {"command": command, "passed": False, "returncode": None, "output_tail": "verify timed out after 900s"}, ""
    output = (proc.stdout + proc.stderr).strip()
    return {"command": command, "passed": proc.returncode == 0, "returncode": proc.returncode,
            "output_tail": output[-1500:]}, output


def run(repo: str, texts: Sequence[str], target: str | None = None, context: Sequence[str] = (),
        tasks_file: str | None = None, verify: str | None = None, apply: str | None = None,
        provider: str | None = None) -> int:
    """Host mode by default: ``apply`` applies the plan the host wrote, otherwise print the plan request.

    ``provider="openrouter"`` is the explicit opt-in to the headless engine; only then is a key needed.
    """
    if provider == "openrouter":
        return _run_provider(repo, texts, target, context, tasks_file, verify)
    if apply:
        return _apply_plan(repo, apply, verify)
    return _request_plan(repo, texts, target, context, tasks_file, verify)


def _request_plan(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                  tasks_file: str | None, verify: str | None) -> int:
    from .turbo import focus_paths, header_message, mapper_reading, slice_enabled, survey_tasks, task_message

    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "mode": "host"}
    tasks = build_tasks(root, texts, target, context, tasks_file)
    if not tasks:
        _emit({**head, "status": "blocked", "reason_code": "turbo_no_tasks", "detail": "pass --task or --tasks-file"})
        return 2
    # The saved survey marker belongs to one run. Ask Mapper again on every invocation: its own
    # tree-state cache keeps an unchanged tree free and byte-identical, and a changed tree gets a new map.
    state = root / ".simplicio-loop"
    (state / "turbo-survey.json").unlink(missing_ok=True)
    try:
        survey_tasks(root, tasks)
        reading = mapper_reading(root, focus=focus_paths(tasks) if len(tasks) == 1 and slice_enabled() else None)
    except RuntimeError as exc:
        _emit({**head, "status": "blocked", "reason_code": "turbo_engine_error", "detail": str(exc)})
        return 2
    apply_command = f"simplicio-loop turbo --repo {shlex.quote(str(root))} --apply {PLAN_PATH}"
    if verify:
        apply_command += f" --verify {shlex.quote(verify)}"
    document = {
        "schema": REQUEST_SCHEMA,
        "status": "needs_plan",
        "mode": "host",
        "repo": str(root),
        "plan_path": PLAN_PATH,
        "apply": apply_command,
        "format": PLAN_FORMAT,
        "tasks": [{k: task[k] for k in ("index", "text", "target", "context")} for task in tasks],
        "prompt": header_message(reading)["content"] + "\n\n" + task_message(tasks, root)["content"],
    }
    request = root / REQUEST_PATH
    request.parent.mkdir(parents=True, exist_ok=True)
    (root / PLAN_PATH).unlink(missing_ok=True)  # a plan left by an earlier request must not be applied to this one
    request.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    _emit(document)
    return 0


def _excerpt(text: str | None, find: str) -> str:
    """A few lines of the current file around where ``find`` was meant to match."""
    if text is None:
        return "(the file does not exist)"
    lines = text.splitlines()
    needle = next((line.strip() for line in find.splitlines() if line.strip()), "")
    at = next((i for i, line in enumerate(lines) if needle and needle in line), None)
    if at is None and needle:
        close = difflib.get_close_matches(needle, [line.strip() for line in lines], n=1, cutoff=0.6)
        at = next((i for i, line in enumerate(lines) if close and line.strip() == close[0]), None)
    first = max(0, (at or 0) - 3)
    return "\n".join(lines[first:first + 12])[:_EXCERPT_CHARS]


def _plan_failures(root: Path, operations: list[dict], reason: str) -> list[dict[str, Any]]:
    """One entry per operation whose ``find`` no longer matches exactly once, else one entry with dev-cli's reason."""
    failures = []
    for operation in operations:
        find = operation.get("find") or ""
        target = root / operation["path"]
        text = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        if find and (text is None or text.count(find) != 1):
            failures.append({"path": operation["path"], "reason": reason, "excerpt": _excerpt(text, find)})
    return failures or [{"path": None, "reason": reason, "excerpt": ""}]


def _apply_plan(repo: str, plan: str, verify: str | None) -> int:
    from .turbo import apply_plan, load_operations

    started = time.time()
    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "mode": "host"}
    path = Path(plan)
    if not path.is_absolute() and (root / path).is_file():
        path = root / path
    if not path.is_file():
        _emit({**head, "status": "failed", "reason_code": "turbo_plan_missing",
               "detail": f"no plan at {plan}: write the JSON plan there, then run the apply command again"})
        return 1
    try:
        operations = load_operations(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        _emit({**head, "status": "failed", "reason_code": "turbo_plan_malformed", "detail": str(exc),
               "format": PLAN_FORMAT})
        return 1
    try:
        result = apply_plan(root, operations, "host-1")
    except RuntimeError as exc:
        _emit({**head, "status": "blocked", "reason_code": "turbo_engine_error", "detail": str(exc)})
        return 2
    applied = [op["path"] for op in operations] if result["applied"] else []
    document: dict[str, Any] = {
        **head,
        "status": "ok" if result["applied"] else "failed",
        "applied": applied,
        "failed": [] if result["applied"] else _plan_failures(root, operations, result["reason"]),
        "verify": None,
    }
    if verify and result["applied"]:
        document["verify"], _output = _run_verify(root, verify)
        if not document["verify"]["passed"]:
            document["status"] = "failed"
    document["wall_s"] = round(time.time() - started, 2)
    _emit(document)
    return 0 if document["status"] == "ok" else 1


def _run_provider(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                  tasks_file: str | None, verify: str | None) -> int:
    from . import turbo_provider
    from .turbo import repair_with_test_output, run_turbo

    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "mode": "provider", "model": turbo_provider.model_name(),
            "reasoning": "off", "session_pinned": True}
    try:
        turbo_provider.require_key()
    except turbo_provider.TurboProviderError as exc:
        _emit({**head, "status": "blocked", "reason_code": exc.reason_code, "detail": str(exc),
               "fix": f"export {turbo_provider.KEY_ENV}=<your OpenRouter key>"})
        return 2
    tasks = build_tasks(root, texts, target, context, tasks_file)
    if not tasks:
        _emit({**head, "status": "blocked", "reason_code": "turbo_no_tasks", "detail": "pass --task or --tasks-file"})
        return 2
    complete = functools.partial(turbo_provider.complete, session_id=turbo_provider.session_id_for(root))
    # The saved survey marker belongs to one run. Ask Mapper again on every invocation: its own
    # tree-state cache keeps an unchanged tree free and byte-identical, and a changed tree gets a new map.
    (root / ".simplicio-loop" / "turbo-survey.json").unlink(missing_ok=True)
    started = time.time()
    try:
        result = run_turbo(root, tasks, complete)
    except RuntimeError as exc:
        _emit({**head, "status": "blocked", "reason_code": "turbo_engine_error", "detail": str(exc)})
        return 2
    calls = list(result["llm_calls"])
    document: dict[str, Any] = {
        **head,
        "status": "ok" if result["applied_all"] else "failed",
        "tasks": len(tasks),
        "model_calls": len(calls),
        "retries": max(0, len([c for c in calls if not c.get("warm")]) - len(result["outcomes"])),
        "applied": [i for o in result["outcomes"] if o["applied"] for i in o["tasks"]],
        "failed": [o for o in result["outcomes"] if not o["applied"]],
        "verify": None,
    }
    if verify and result["applied_all"]:
        document["verify"], output = _run_verify(root, verify)
        if not document["verify"]["passed"]:
            # One repair call with the test output, then the tests run again.
            repair = repair_with_test_output(root, tasks, complete, output)
            calls.extend(repair["llm_calls"])
            retry = {"attempted": True, "applied": repair["applied"], "reason": repair["reason"], "passed": False}
            if repair["applied"]:
                document["verify"], _output = _run_verify(root, verify)
                retry["passed"] = document["verify"]["passed"]
            document["verify_retry"] = retry
            if not retry["passed"]:
                document["status"] = "failed"
    losers = turbo_provider.drain_hedges()
    billed = calls + losers
    tokens = {k: sum(c.get(k) or 0 for c in billed)
              for k in ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")}
    document.update({
        "model_calls": len(calls),
        "hedged_calls": sum(1 for c in calls if c.get("hedged")),
        "tokens": tokens,
        "cache_hit_pct": round(100 * tokens["cached_tokens"] / tokens["prompt_tokens"], 1) if tokens["prompt_tokens"] else 0.0,
        "cost_usd": round(sum(c.get("cost_usd") or 0 for c in billed), 6),
        "calls": [{k: c.get(k) for k in ("latency_s", "provider", "prompt_tokens", "cached_tokens",
                                         "completion_tokens", "hedged", "warm")} for c in calls],
    })
    document["wall_s"] = round(time.time() - started, 2)
    _emit(document)
    return 0 if document["status"] == "ok" else 1
