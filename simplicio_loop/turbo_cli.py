"""`simplicio-loop turbo`: the default way to run a task.

Host mode (the default: no provider call, no key). The invoking model plans and simplicio-dev-cli applies, in
exactly two commands:

1. ``turbo --task T`` surveys with Mapper and prints a ``needs_plan`` request: the task, the map slice, the
   current text of the files it names, the plan format and the ONE next command, in heredoc form.
2. That command, ``turbo --apply - [--verify V] <<'PLAN'`` + the find/replace JSON plan + ``PLAN``, reads the
   plan from stdin, applies it through dev-cli and runs ``--verify``. ``--apply FILE`` reads the plan from a
   file instead: the same code path.

Provider mode (``--provider openrouter``, headless automation only): the benchmarked engine. One model call per
lane (``turbo_provider``: OpenRouter, pinned session, reasoning off), then dev-cli applies each plan.

The output is one compact JSON document. Exit code: 0 ok / needs_plan, 1 failed, 2 blocked.
"""
from __future__ import annotations

import asyncio
import difflib
import functools
import json
import re
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from . import plan_paths

if TYPE_CHECKING:
    from .turbo_run import TurboRun

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
        # Tasks that touch the same file stay in order; the rest can fan out.
        task["depends_on"] = spec.get("depends_on") or [
            earlier["index"] for earlier in tasks
            if files & ({earlier["target"], *earlier["context"]} - {None})
        ]
        tasks.append(task)
    return tasks


def _emit(document: dict[str, Any]) -> None:
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))


VERIFY_TIMEOUT_S = 900


async def _run_verify(root: Path, command: str) -> tuple[dict[str, Any], str]:
    """Run the verify command in the repo. Returns the report and the full output.

    The shell runs in its own process group under ``asyncio.wait_for``: the event loop stays free while it
    runs, and on timeout the whole group (the shell and what it started) is killed.
    """
    from .exec_planner import _kill_process_tree

    sh_bin = shutil.which("sh") or "/bin/sh"
    proc = await asyncio.create_subprocess_exec(
        sh_bin, "-c", command, cwd=root, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=VERIFY_TIMEOUT_S)
    except asyncio.TimeoutError:
        await _kill_process_tree(proc)
        return {"command": command, "passed": False, "returncode": None,
                "output_tail": f"verify timed out after {VERIFY_TIMEOUT_S:g}s"}, ""
    except BaseException:
        await _kill_process_tree(proc)
        raise
    output = (stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")).strip()
    return {"command": command, "passed": proc.returncode == 0, "returncode": proc.returncode,
            "output_tail": output[-1500:]}, output


def run(repo: str, texts: Sequence[str], target: str | None = None, context: Sequence[str] = (),
        tasks_file: str | None = None, verify: str | None = None, apply: str | None = None,
        provider: str | None = None, run_id: str | None = None, leave_open: bool = False) -> int:
    """Host mode by default: ``apply`` applies the plan the host wrote (``-``: from stdin), otherwise print the request.

    ``provider="openrouter"`` is the headless engine, for automation only; only then is a key needed.
    ``run_id`` continues the run the request printed (host mode); without it an apply starts a new run. A request
    given a ``run_id`` opens (or continues) that run, so a caller can write its own stages first.
    ``leave_open`` leaves an ok apply's run open for the caller to close.
    """
    if provider == "openrouter":
        return _run_provider(repo, texts, target, context, tasks_file, verify, run_id)
    if apply:
        return _apply_plan(repo, apply, verify, run_id, leave_open)
    return _request_plan(repo, texts, target, context, tasks_file, verify, run_id)


def _map_slice(reading: str) -> Any:
    """The map slice as JSON, so the request does not carry it escaped inside a string."""
    try:
        return json.loads(reading)
    except ValueError:  # a map cut at the size cap is not JSON any more
        return reading


def _repo_missing(root: Path, mode: str) -> bool:
    """A repository that is not a directory is blocked before any run directory is created."""
    if root.is_dir():
        return False
    _emit({"schema": SCHEMA, "repo": str(root), "mode": mode, "status": "blocked",
           "reason_code": "turbo_repo_missing", "detail": f"no such repository directory: {root}"})
    return True


def _conclude(run_: TurboRun, document: dict[str, Any], calls: Any = None, leave_open: bool = False) -> int:
    """Close the run, attach its execution report and print the one JSON document. 0 ok, 1 failed, 2 blocked.

    ``leave_open`` keeps an ok run open for its caller (the 24/7 watcher closes it after the pr stage).
    """
    status = document["status"]
    document["execution_report"] = run_.finish(status, tasks=document.get("tasks", 1), calls=calls,
                                               leave_open=leave_open)
    _emit(document)
    return {"ok": 0, "failed": 1}.get(status, 2)


def _request_plan(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                  tasks_file: str | None, verify: str | None, run_id: str | None = None) -> int:
    from .turbo import current_files, focus_paths, mapper_reading, plan_prompt, slice_enabled, survey_tasks
    from .turbo_run import TurboRun

    root = Path(repo).resolve()
    if _repo_missing(root, "host"):
        return 2
    tasks = build_tasks(root, texts, target, context, tasks_file)
    if not tasks:
        _emit({"schema": SCHEMA, "repo": str(root), "mode": "host", "status": "blocked",
               "reason_code": "turbo_no_tasks", "detail": "pass --task or --tasks-file"})
        return 2
    try:
        run_ = TurboRun(root, "host", run_id)
    except ValueError as exc:
        _emit({"schema": SCHEMA, "repo": str(root), "mode": "host", "status": "blocked",
               "reason_code": "turbo_run_id_invalid", "detail": str(exc)})
        return 2
    head = {"schema": SCHEMA, "repo": str(root), "mode": "host", "run_id": run_.run_id, **plan_prompt()}
    run_.enter("orient")
    # The saved survey marker belongs to one run. Ask Mapper again on every invocation: its own
    # tree-state cache keeps an unchanged tree free and byte-identical, and a changed tree gets a new map.
    (root / ".simplicio-loop" / "turbo-survey.json").unlink(missing_ok=True)
    try:
        asyncio.run(survey_tasks(root, tasks))
        # No prompt cache to warm in host mode: the map is only the slice of the files the tasks name.
        reading = mapper_reading(root, focus=focus_paths(tasks) if slice_enabled() else None)
    except RuntimeError as exc:
        return _conclude(run_, {**head, "status": "blocked", "reason_code": "turbo_engine_error",
                                "detail": str(exc), "tasks": len(tasks)})
    run_.enter("plan")
    run_.await_plan()
    apply_command = f"simplicio-loop turbo --repo {shlex.quote(str(root))} --apply - --run-id {run_.run_id}"
    if verify:
        apply_command += f" --verify {shlex.quote(verify)}"
    apply_command += " <<'PLAN'\n<JSON plan>\nPLAN"
    _emit({
        "schema": REQUEST_SCHEMA,
        "status": "needs_plan",
        "mode": "host",
        "run_id": run_.run_id,
        **plan_prompt(),
        "tasks": [task["text"] for task in tasks],
        "map": _map_slice(reading),
        "files": current_files(root, tasks),
        "format": PLAN_FORMAT,
        "rules": RULES,
        "apply": apply_command,
    })
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
        if plan_paths.refusal(operation["path"], root):  # never read, never excerpted: it leads into .git or out of the root
            failures.append({"path": operation["path"], "reason": reason, "excerpt": ""})
            continue
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


def _apply_plan(repo: str, plan: str, verify: str | None, run_id: str | None = None, leave_open: bool = False) -> int:
    """Wrapper to call async _apply_plan_async with asyncio.run."""
    return asyncio.run(_apply_plan_async(repo, plan, verify, run_id, leave_open))


async def _apply_plan_async(repo: str, plan: str, verify: str | None, run_id: str | None = None,
                            leave_open: bool = False) -> int:
    from .turbo import NO_RECEIPT, apply_plan, load_operations, plan_prompt
    from .turbo_run import TurboRun

    started = time.time()
    root = Path(repo).resolve()
    if _repo_missing(root, "host"):
        return 2
    try:
        run_ = TurboRun(root, "host", run_id)
    except ValueError as exc:
        _emit({"schema": SCHEMA, "repo": str(root), "mode": "host", "status": "blocked",
               "reason_code": "turbo_run_id_invalid", "detail": str(exc)})
        return 2
    head = {"schema": SCHEMA, "repo": str(root), "mode": "host", "run_id": run_.run_id, **plan_prompt()}
    run_.enter("apply")
    try:
        text, missing = _plan_text(root, plan)
        operations = load_operations(text) if text is not None else []
    except ValueError as exc:  # not UTF-8, not JSON, or not a plan
        return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_plan_malformed",
                                "detail": str(exc), "format": PLAN_FORMAT})
    if text is None:
        return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_plan_missing", "detail": missing})
    try:
        result = await apply_plan(root, operations, "host-1")
    except RuntimeError as exc:
        return _conclude(run_, {**head, "status": "blocked", "reason_code": "turbo_engine_error", "detail": str(exc)})
    receipts = run_.persist_receipts(result["commands"])
    if result["reason"] == NO_RECEIPT:
        return _conclude(run_, {**head, "status": "blocked", "reason_code": NO_RECEIPT, "applied": [],
                                "receipts": receipts, "detail": "dev-cli apply left no edit receipt"})
    applied = [op["path"] for op in operations] if result["applied"] else []
    document: dict[str, Any] = {
        **head,
        "status": "ok" if result["applied"] else "failed",
        "tasks": 1,
        "applied": applied,
        "receipts": receipts,
        "failed": [] if result["applied"] else _plan_failures(root, operations, result["reason"]),
        "verify": None,
    }
    if verify and result["applied"]:
        run_.enter("verify")
        document["verify"], _output = await _run_verify(root, verify)
        if not document["verify"]["passed"]:
            document["status"] = "failed"
    document["wall_s"] = round(time.time() - started, 2)
    return _conclude(run_, document, leave_open=leave_open)


def _run_provider(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                  tasks_file: str | None, verify: str | None, run_id: str | None = None) -> int:
    """The one place the event loop starts: everything below it is awaited, and the shared client is closed."""
    from . import turbo_provider

    async def main() -> int:
        try:
            return await _run_provider_async(repo, texts, target, context, tasks_file, verify, run_id)
        finally:
            await turbo_provider.close()

    return asyncio.run(main())


async def _run_provider_async(repo: str, texts: Sequence[str], target: str | None, context: Sequence[str],
                               tasks_file: str | None, verify: str | None, run_id: str | None = None) -> int:
    from . import turbo_provider
    from .turbo import NO_RECEIPT, plan_prompt, repair_with_test_output, run_turbo
    from .turbo_run import TurboRun

    root = Path(repo).resolve()
    if _repo_missing(root, "provider"):
        return 2
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
    try:
        run_ = TurboRun(root, "provider", run_id)
    except ValueError as exc:
        _emit({**head, "status": "blocked", "reason_code": "turbo_run_id_invalid", "detail": str(exc)})
        return 2
    head = {**head, "run_id": run_.run_id, **plan_prompt()}
    complete = functools.partial(turbo_provider.complete, session_id=turbo_provider.session_id_for(root))
    # The saved survey marker belongs to one run. Ask Mapper again on every invocation: its own
    # tree-state cache keeps an unchanged tree free and byte-identical, and a changed tree gets a new map.
    (root / ".simplicio-loop" / "turbo-survey.json").unlink(missing_ok=True)
    started = time.time()
    run_.enter("orient")
    run_.enter("plan")
    try:
        # dev-cli applies run inside run_turbo, between the model calls of each wave; "apply" is entered once it returns.
        result = await run_turbo(root, tasks, complete)
    except RuntimeError as exc:
        return _conclude(run_, {**head, "status": "blocked", "reason_code": "turbo_engine_error",
                                "detail": str(exc), "tasks": len(tasks)})
    run_.enter("apply")
    receipts = run_.persist_receipts(result["commands"])
    calls = list(result["llm_calls"])
    blocked_on_receipt = any(o.get("reason") == NO_RECEIPT for o in result["outcomes"])
    document: dict[str, Any] = {
        **head,
        "status": "ok" if result["applied_all"] else "failed",
        "tasks": len(tasks),
        "model_calls": len(calls),
        "retries": max(0, len([c for c in calls if not c.get("warm")]) - len(result["outcomes"])),
        "applied": [i for o in result["outcomes"] if o["applied"] for i in o["tasks"]],
        "failed": [o for o in result["outcomes"] if not o["applied"]],
        "receipts": receipts,
        "verify": None,
    }
    if blocked_on_receipt and not result["applied_all"]:
        document["status"] = "blocked"
        document["reason_code"] = NO_RECEIPT
    if verify and result["applied_all"]:
        run_.enter("verify")
        document["verify"], output = await _run_verify(root, verify)
        if not document["verify"]["passed"]:
            # One repair call with the test output, then the tests run again.
            repair = await repair_with_test_output(root, tasks, complete, output)
            calls.extend(repair["llm_calls"])
            receipts.extend(run_.persist_receipts(repair["commands"]))
            retry = {"attempted": True, "applied": repair["applied"], "reason": repair["reason"], "passed": False}
            if repair["applied"]:
                document["verify"], _output = await _run_verify(root, verify)
                retry["passed"] = document["verify"]["passed"]
            document["verify_retry"] = retry
            if not retry["passed"]:
                document["status"] = "failed"
    billed = calls  # a hedge loser is cancelled and reports no usage
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
    return _conclude(run_, document, calls)
