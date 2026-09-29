"""`simplicio-loop turbo`: the default way to run a task.

Hybrid mode (the default when the invoking host has a headless CLI, see ``turbo_host_llm``): ONE command. The turbo engine runs the
whole flow (Mapper survey, fan-out, dev-cli apply, ``--verify``, one repair) and every model call it needs goes through the
host's own CLI (a chain of dependent tasks is ONE call, independent tasks are asked at the same time), so it uses the same model, account and configuration with no key of its own. The result has ``mode: "hybrid"``
and ``llm: <host>``. When the hybrid backend cannot be used (no host detected, its CLI missing, no network, an auth or HTTP
error, a timeout, the ``SIMPLICIO_TURBO_BUDGET_S`` time budget spent) the same invocation prints the host-mode request below with
``reason: "hybrid_unavailable: <cause>"``; a failure mid-run keeps what was applied and hands over the remaining tasks only.

Host mode (no host CLI to call; no provider call, no key). The invoking model plans and simplicio-dev-cli applies, in
exactly two commands:

1. ``turbo --task T`` surveys with Mapper and prints a ``needs_plan`` request: the task, the map slice, the
   current text of the files it names, the plan format and the ONE next command, in heredoc form.
2. That command, ``turbo --apply - [--verify V] <<'PLAN'`` + the find/replace JSON plan + ``PLAN``, reads the
   plan from stdin, applies it through dev-cli and runs ``--verify``. ``--apply FILE`` reads the plan from a
   file instead: the same code path.

Provider mode (``--provider openrouter``, headless automation only): the benchmarked engine. One model call per
group of dependent tasks, the groups at the same time (``turbo_provider``: OpenRouter, pinned session, reasoning off), then dev-cli applies each plan.

The output is one compact JSON document. Exit code: 0 ok / needs_plan, 1 failed, 2 blocked.
"""
from __future__ import annotations

import difflib
import functools
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from .state_dir import ensure_state_dir

SCHEMA = "simplicio.turbo-run/v1"
REQUEST_SCHEMA = "simplicio.turbo-request/v1"
PLAN_FORMAT = {"operations": [{"path": "<repo-relative>",
                               "find": "<exact text that occurs once; empty creates the file>",
                               "replace": "<new text>"}]}
RULES = ("Write the plan from the file contents above; do not open, list or read other files; "
         "do not run tests yourself; run the command below once.")
STDIN_HINT = ("pipe the JSON plan on stdin: `simplicio-loop turbo --repo <path> --apply - <<'PLAN'`, the plan, "
              "then `PLAN`")
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
        # Tasks that touch the same file depend on each other (one model call); the rest are asked at the same time.
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


def _verify_with_repair(root: Path, tasks: Sequence[dict[str, Any]], complete, verify: str, document: dict[str, Any],
                        calls: list[dict[str, Any]]) -> None:
    """Run ``--verify``; when it fails, ONE repair call with the test output, then the tests run again."""
    from .turbo import repair_with_test_output

    document["verify"], output = _run_verify(root, verify)
    if document["verify"]["passed"]:
        return
    repair = repair_with_test_output(root, tasks, complete, output)
    calls.extend(repair["llm_calls"])
    retry = {"attempted": True, "applied": repair["applied"], "reason": repair["reason"], "passed": False}
    if repair["applied"]:
        document["verify"], _output = _run_verify(root, verify)
        retry["passed"] = document["verify"]["passed"]
    document["verify_retry"] = retry
    if not retry["passed"]:
        document["status"] = "failed"


def run(repo: str, texts: Sequence[str], target: str | None = None, context: Sequence[str] = (),
        tasks_file: str | None = None, verify: str | None = None, apply: str | None = None,
        provider: str | None = None) -> int:
    """Hybrid when a host CLI can answer the model calls, else host mode. ``apply`` applies the plan the host wrote (``-``:
    from stdin).

    ``provider="openrouter"`` is the headless engine, for automation only; only then is a key needed.
    """
    if provider == "openrouter":
        return _run_provider(repo, texts, target, context, tasks_file, verify)
    if apply:
        return _apply_plan(repo, apply, verify)
    from . import turbo_host_llm as host_llm

    choice = host_llm.resolve()
    if choice.provider:  # SIMPLICIO_TURBO_LLM=provider
        return _run_provider(repo, texts, target, context, tasks_file, verify)
    if choice.cause == "unknown_llm":
        valid = [h["id"] for h in host_llm.catalog() if (h.get("llm") or {}).get("argv")] + ["host", "provider", "auto"]
        _emit({"schema": SCHEMA, "repo": str(Path(repo).resolve()), "mode": "host", "status": "blocked",
               "reason_code": "turbo_llm_unknown",
               "detail": f"{host_llm.LLM_ENV}={choice.detail!r} is not one of: {', '.join(valid)}"})
        return 2
    if choice.backend is None:
        return _request_plan(repo, texts, target, context, tasks_file, verify, reason=choice.reason, detail=choice.detail)
    return _run_hybrid(repo, texts, target, context, tasks_file, verify, choice.backend)


def _register_state_dir(root: Path) -> None:
    """Mapper, the survey marker and dev-cli all write under `.simplicio-loop/`: register it with git first."""
    if root.is_dir():
        ensure_state_dir(root)


def _map_slice(reading: str) -> Any:
    """The map slice as JSON, so the request does not carry it escaped inside a string."""
    try:
        return json.loads(reading)
    except ValueError:  # a map cut at the size cap is not JSON any more
        return reading


def _apply_command(root: Path, verify: str | None) -> str:
    """The ONE next command of host mode: apply the plan the host writes as the heredoc body."""
    command = f"simplicio-loop turbo --repo {shlex.quote(str(root))} --apply -"
    if verify:
        command += f" --verify {shlex.quote(verify)}"
    return command + " <<'PLAN'\n<JSON plan>\nPLAN"


def _request_plan(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                  tasks_file: str | None, verify: str | None, reason: str | None = None, detail: str | None = None) -> int:
    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "mode": "host"}
    tasks = build_tasks(root, texts, target, context, tasks_file)
    if not tasks:
        _emit({**head, "status": "blocked", "reason_code": "turbo_no_tasks", "detail": "pass --task or --tasks-file"})
        return 2
    _register_state_dir(root)
    return _emit_request(root, tasks, verify, head, reason=reason, detail=detail)


def _emit_request(root: Path, tasks: Sequence[dict[str, Any]], verify: str | None, head: dict[str, Any],
                  reason: str | None = None, detail: str | None = None, applied: Sequence[int] = ()) -> int:
    """Print the host-mode ``needs_plan`` request for ``tasks``.

    ``reason`` (``hybrid_unavailable: <cause>``) says why the hybrid backend did not answer; ``applied`` lists the tasks it
    had already applied before it stopped, and ``tasks`` are then the remaining ones only.
    """
    from .turbo import current_files, focus_paths, mapper_reading, slice_enabled, survey_tasks

    # The saved survey marker belongs to one run. Ask Mapper again on every invocation: its own
    # tree-state cache keeps an unchanged tree free and byte-identical, and a changed tree gets a new map.
    (root / ".simplicio-loop" / "turbo-survey.json").unlink(missing_ok=True)
    try:
        survey_tasks(root, tasks)
        # No prompt cache to warm in host mode: the map is only the slice of the files the tasks name.
        reading = mapper_reading(root, focus=focus_paths(tasks) if slice_enabled() else None)
    except RuntimeError as exc:
        _emit({**head, "status": "blocked", "reason_code": "turbo_engine_error", "detail": str(exc)})
        return 2
    document: dict[str, Any] = {"schema": REQUEST_SCHEMA, "status": "needs_plan", "mode": "host"}
    if reason:
        document["reason"] = reason
        if detail:
            document["detail"] = detail[:300]
    if applied:
        document["applied"] = list(applied)
    document.update({
        "tasks": [task["text"] for task in tasks],
        "map": _map_slice(reading),
        "files": current_files(root, tasks),
        "format": PLAN_FORMAT,
        "rules": RULES,
        "apply": _apply_command(root, verify),
    })
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


def _plan_text(root: Path, plan: str) -> tuple[str | None, str]:
    """The plan text (stdin for ``-``, else a file) or None with the reason there is none. UTF-8 either way."""
    if plan == "-":
        if sys.stdin is None or sys.stdin.isatty():
            return None, f"stdin is a terminal or closed, not a plan: {STDIN_HINT}"
        stream = getattr(sys.stdin, "buffer", None)
        # Bytes, not the locale-decoded text stream: a plan in Portuguese must survive a cp1252 or C locale.
        text = stream.read().decode("utf-8-sig") if stream is not None else sys.stdin.read()
        return (text, "") if text.strip() else (None, f"nothing arrived on stdin: {STDIN_HINT}")
    path = Path(plan)
    if not path.is_absolute() and (root / path).is_file():
        path = root / path
    if not path.is_file():
        return None, f"no plan at {plan}: write the JSON plan there, or {STDIN_HINT}"
    return path.read_text(encoding="utf-8"), ""


def _apply_plan(repo: str, plan: str, verify: str | None) -> int:
    from .turbo import apply_plan, load_operations

    started = time.time()
    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "mode": "host"}
    try:
        text, missing = _plan_text(root, plan)
        operations = load_operations(text) if text is not None else []
    except ValueError as exc:  # not UTF-8, not JSON, or not a plan
        _emit({**head, "status": "failed", "reason_code": "turbo_plan_malformed", "detail": str(exc),
               "format": PLAN_FORMAT})
        return 1
    if text is None:
        _emit({**head, "status": "failed", "reason_code": "turbo_plan_missing", "detail": missing})
        return 1
    _register_state_dir(root)
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
    from .turbo import run_turbo

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
    _register_state_dir(root)
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
        "retries": max(0, len(calls) - len(result["outcomes"])),
        "applied": [i for o in result["outcomes"] if o["applied"] for i in o["tasks"]],
        "failed": [o for o in result["outcomes"] if not o["applied"]],
        "verify": None,
    }
    if verify and result["applied_all"]:
        _verify_with_repair(root, tasks, complete, verify, document, calls)
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
                                         "completion_tokens", "hedged")} for c in calls],
    })
    document["wall_s"] = round(time.time() - started, 2)
    _emit(document)
    return 0 if document["status"] == "ok" else 1


def _why_unfinished(result: dict[str, Any]) -> tuple[str, str]:
    """The cause the engine stopped, or why the plan of the first task it could not apply was refused."""
    if result.get("stopped"):
        return result["stopped"]["reason_code"], result["stopped"]["detail"]
    first = next((o for o in result["outcomes"] if not o["applied"]), {})
    return "plan_rejected", str(first.get("reason") or "the model returned no usable plan")


def _run_hybrid(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                tasks_file: str | None, verify: str | None, backend) -> int:
    """The whole turbo flow behind one command, its model calls answered by the host's own CLI."""
    from . import turbo_host_llm as host_llm
    from .turbo import current_files, run_turbo

    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "mode": "hybrid", "llm": backend.id}
    tasks = build_tasks(root, texts, target, context, tasks_file)
    if not tasks:
        _emit({**head, "status": "blocked", "reason_code": "turbo_no_tasks", "detail": "pass --task or --tasks-file"})
        return 2
    _register_state_dir(root)
    started, budget = time.time(), host_llm.budget_s()
    deadline = time.monotonic() + budget
    host_llm.install_cleanup()
    notes: dict[str, Any] = {}
    models: set[str] = set()

    def complete(arm: str, messages, **kwargs):
        reply = host_llm.complete(arm, messages, backend=backend, root=root, deadline=deadline, **kwargs)
        notes.update(reply.get("notes") or {})
        if reply.get("model"):
            models.add(str(reply["model"]))
        return reply

    (root / ".simplicio-loop" / "turbo-survey.json").unlink(missing_ok=True)
    try:
        result = run_turbo(root, tasks, complete, deadline=deadline)
    except RuntimeError as exc:
        _emit({**head, "status": "blocked", "reason_code": "turbo_engine_error", "detail": str(exc)})
        return 2
    calls = list(result["llm_calls"])
    applied = [i for o in result["outcomes"] if o["applied"] for i in o["tasks"]]
    remaining = [t for t in tasks if t["index"] not in applied]
    if remaining:  # keep what was applied; the host plans the rest with the two-command flow
        cause, detail = _why_unfinished(result)
        return _emit_request(root, remaining, verify, {"schema": SCHEMA, "repo": str(root), "mode": "host"},
                             reason=f"hybrid_unavailable: {cause}", detail=detail, applied=applied)
    document: dict[str, Any] = {
        **head,
        "status": "ok",
        "tasks": len(tasks),
        "model_calls": len(calls),
        "retries": max(0, len(calls) - len(result["outcomes"])),
        "applied": applied,
        "failed": [],
        "verify": None,
    }
    if verify:
        _verify_with_repair(root, tasks, complete, verify, document, calls)
    tokens = {k: sum(c.get(k) or 0 for c in calls)
              for k in ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")}
    costs = [c["cost_usd"] for c in calls if c.get("cost_usd") is not None]
    document.update({
        "model_calls": len(calls),
        "tokens": tokens,
        "tokens_reported": bool(tokens["prompt_tokens"] or tokens["completion_tokens"]),
        "cache_hit_pct": round(100 * tokens["cached_tokens"] / tokens["prompt_tokens"], 1) if tokens["prompt_tokens"] else 0.0,
        "cost_usd": round(sum(costs), 6) if costs else None,
        "cost_basis": "host-reported",
        "calls": [{k: c.get(k) for k in ("latency_s", "prompt_tokens", "cached_tokens", "completion_tokens",
                                         "reasoning_tokens", "cost_usd", "ok")} for c in calls],
        **({"model": next(iter(models))} if len(models) == 1 else {}),
        **notes,
    })
    if document["status"] == "failed":  # what the host needs to fix it once, in host mode
        document["apply"] = _apply_command(root, verify)
        document["files"] = current_files(root, tasks)
    document["wall_s"] = round(time.time() - started, 2)
    document["budget_s"] = budget
    _emit(document)
    return 0 if document["status"] == "ok" else 1
