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
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from . import plan_paths, plan_scope, turbo_window

if TYPE_CHECKING:
    from .turbo_run import TurboRun

SCHEMA = "simplicio.turbo-run/v1"
REQUEST_SCHEMA = "simplicio.turbo-request/v1"
PLAN_FORMAT = {"operations": [{"path": "<repo-relative>",
                               "find": "<exact text that occurs once; empty creates the file>",
                               "replace": "<new text>"}]}
RULES = ("Write the plan from the file contents above; do not open, list or read other files "
         '(a file shown in windows has more lines in `omitted`: answer {"operations": [], "need": [{"path", "start", "end"}]} '
         'to see them, e.g. {"operations": [], "need": [{"path": "tests/test_x.py", "start": 147, "end": 190}]}; '
         "the same lines come with `--window tests/test_x.py:147-190` on the turbo command); "
         "do not run tests yourself; run the command below once.")
STDIN_HINT = ("pipe the JSON plan on stdin: `simplicio-loop turbo --repo <path> --apply - <<'PLAN'`, the plan, "
              "then `PLAN`")
_EXCERPT_CHARS = 600
REQUEST_ARGS = "request-args.json"  # in the run directory
_CODE_EXTENSIONS = frozenset((
    "py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "html", "htm", "css", "scss", "md", "json", "yml",
    "yaml", "toml", "ini", "cfg", "txt", "go", "rs", "java", "kt", "rb", "php", "cs", "c", "h", "cpp",
    "hpp", "sh", "sql", "vue", "svelte", "swift", "dart", "lua", "xml",
))
_CRITERION = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*(.+)$", re.M)
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


def task_scope(root: Path, tasks: Sequence[Mapping[str, Any]]) -> plan_scope.TaskScope:
    """What these tasks may touch (issue #1612): their target and context (the Mapper focus), every path their text
    names (a file to create included), and their checklist criteria. A task that names no file is ``unbounded``."""
    texts = [str(task.get("text") or "") for task in tasks]
    return plan_scope.scope_from_tasks(
        tasks, named_paths=[p for text in texts for p in mentioned_paths(text, root)],
        criteria=[m.group(1).strip() for text in texts for m in _CRITERION.finditer(text)])


def _scope_summary(scope: plan_scope.TaskScope, widenings: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """The scope a run was held to, for the document: counts, not the paths, and every widening rule that was used."""
    return {"files": len(scope.paths), "dirs": len(scope.dirs), "criteria": len(scope.criteria),
            "unbounded": scope.unbounded, "max_lines": scope.max_lines, "widenings": list(widenings)}


def _emit(document: dict[str, Any]) -> None:
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))


VERIFY_TIMEOUT_S = 900


async def _run_verify(root: Path, command: str, run_: TurboRun) -> tuple[dict[str, Any], str]:
    """Run the verify command in the repo. Returns the report and the full output.

    The shell runs in its own process group under ``asyncio.wait_for``: the event loop stays free while it
    runs, and on timeout the whole group (the shell and what it started) is killed. The run's dashboard events
    bracket the command (``command_started`` / ``command_finished``) so the panel can show it while it runs.
    """
    from .exec_planner import _kill_process_tree

    sh_bin = shutil.which("sh") or "/bin/sh"
    with run_.command(command) as span:
        proc = await asyncio.create_subprocess_exec(
            sh_bin, "-c", command, cwd=root, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=VERIFY_TIMEOUT_S)
        except asyncio.TimeoutError:
            await _kill_process_tree(proc)
            span.reason = "timeout"
            return {"command": command, "passed": False, "returncode": None,
                    "output_tail": f"verify timed out after {VERIFY_TIMEOUT_S:g}s"}, ""
        except BaseException:
            await _kill_process_tree(proc)
            raise
        span.exit_code = proc.returncode
    output = (stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")).strip()
    return {"command": command, "passed": proc.returncode == 0, "returncode": proc.returncode,
            "output_tail": output[-1500:]}, output


def run(repo: str, texts: Sequence[str], target: str | None = None, context: Sequence[str] = (),
        tasks_file: str | None = None, verify: str | None = None, apply: str | None = None,
        provider: str | None = None, run_id: str | None = None, leave_open: bool = False,
        windows: Sequence[Any] = ()) -> int:
    """Host mode by default: ``apply`` applies the plan the host wrote (``-``: from stdin), otherwise print the request.

    ``provider="openrouter"`` is the headless engine, for automation only; only then is a key needed.
    ``run_id`` continues the run the request printed (host mode); without it an apply starts a new run. A request
    given a ``run_id`` opens (or continues) that run, so a caller can write its own stages first.
    ``leave_open`` leaves an ok apply's run open for the caller to close. ``windows`` (``PATH:START-END``) are extra
    lines of a big file for the request.
    """
    if provider == "openrouter":
        return _run_provider(repo, texts, target, context, tasks_file, verify, run_id)
    if apply:
        return _apply_plan(repo, apply, verify, run_id, leave_open)
    return _request_plan(repo, texts, target, context, tasks_file, verify, run_id, windows)


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
                  tasks_file: str | None, verify: str | None, run_id: str | None = None,
                  windows: Sequence[Any] = ()) -> int:
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
        asked = [turbo_window.parse_window_spec(w) if isinstance(w, str) else w for w in windows]
        files = current_files(root, tasks, asked)
    except ValueError as exc:  # a bad --window, or a bad input-token ceiling (reason_code of its own)
        _emit({"schema": SCHEMA, "repo": str(root), "mode": "host", "status": "blocked",
               "reason_code": getattr(exc, "reason_code", "turbo_window_invalid"), "detail": str(exc)})
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
    # What a later `need` (turbo --apply with no operations) rebuilds the request from: the same run, more windows.
    (run_.run_dir / REQUEST_ARGS).write_text(json.dumps({
        "texts": list(texts), "target": target, "context": list(context), "tasks_file": tasks_file, "verify": verify,
        "windows": asked, "truncated": turbo_window.truncated(files)}), encoding="utf-8")
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
        "files": files,
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


def _plan_failures(root: Path, operations: list[dict], reason: str, violations: Sequence[str] = ()) -> list[dict[str, Any]]:
    """One entry per operation whose ``find`` no longer matches exactly once, else one entry with dev-cli's reason.

    ``violations`` (the answer was refused by ``plan_scope``) come first, one entry each: the reason is the violation
    itself (``out_of_scope:<path>``, ``extra_field:...``), the same text on every run, and the excerpt is empty."""
    if violations:
        return [{"path": plan_scope.violation_path(v), "reason": v, "excerpt": ""} for v in violations]
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
    """Wrapper to call async _apply_plan_async with asyncio.run. A plan that only asks for lines (``need``) comes back
    as the arguments of a new request, printed here outside the event loop."""
    done = asyncio.run(_apply_plan_async(repo, plan, verify, run_id, leave_open))
    return _request_plan(*done) if isinstance(done, tuple) else done


def _saved_request(run_: TurboRun) -> dict[str, Any]:
    """The arguments of the request this run printed (``request-args.json``), or ``{}``."""
    try:
        saved = json.loads((run_.run_dir / REQUEST_ARGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _saved_scope(root: Path, saved: Mapping[str, Any]) -> plan_scope.TaskScope | None:
    """The scope of the request this run printed, or None when the run has none (a bare ``--apply`` names no task)."""
    if "texts" not in saved:
        return None
    tasks = build_tasks(root, saved["texts"], saved.get("target"), saved.get("context") or (), saved.get("tasks_file"))
    return task_scope(root, tasks)


def _refusal_document(run_: TurboRun, head: dict[str, Any], root: Path, operations: list[dict],
                      violations: Sequence[str], scope: plan_scope.TaskScope) -> dict[str, Any]:
    """The plan broke the closed contract or the scope: nothing is applied. The first refusal of a run is a ``retry``
    (``retry_scheduled``; ``detail`` is what to tell the planner), the second is ``needs_human`` with the cause."""
    count = run_.count_refusal()
    action = plan_scope.next_action(count)
    run_.refused(violations, action, count)
    document: dict[str, Any] = {
        **head, "status": "failed", "reason_code": "turbo_plan_refused" if action == "retry" else "needs_human",
        "next_action": action, "detail": plan_scope.retry_message(violations), "applied": [],
        "failed": _plan_failures(root, operations, "plan_refused", violations),
        "rejected": plan_scope.counters(violations), "scope": _scope_summary(scope, []), "format": PLAN_FORMAT,
    }
    if action == "needs_human":
        document["cause"] = list(violations[:plan_scope.MAX_REPORTED])
    return document


async def _apply_plan_async(repo: str, plan: str, verify: str | None, run_id: str | None = None,
                            leave_open: bool = False) -> int | tuple[Any, ...]:
    from .turbo import NO_RECEIPT, EmptyPlanError, apply_plan, load_need, load_operations, plan_prompt
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
    saved = _saved_request(run_)
    try:
        text, missing = _plan_text(root, plan)
        need = load_need(text) if text is not None else []
        operations = load_operations(text) if text is not None and not need else []
    except EmptyPlanError as exc:  # no operations and no need: the planner was not shown the part it had to change
        if saved.get("truncated"):
            return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_context_truncated",
                                    "detail": f"{exc}; the request showed only windows of {saved['truncated']}: "
                                              "ask for lines with need", "format": PLAN_FORMAT})
        return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_plan_malformed",
                                "detail": str(exc), "format": PLAN_FORMAT})
    except ValueError as exc:  # not UTF-8, not JSON, or not a plan
        return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_plan_malformed",
                                "detail": str(exc), "format": PLAN_FORMAT})
    if need:  # nothing is applied: the same run prints its request again with these lines added
        if "texts" not in saved:
            return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_need_unavailable",
                                    "detail": f"run {run_.run_id} has no saved request; use turbo --task T --window PATH:START-END"})
        return (repo, saved["texts"], saved["target"], saved["context"], saved["tasks_file"],
                verify or saved["verify"], run_.run_id, [*saved["windows"], *need])
    if text is None:
        return _conclude(run_, {**head, "status": "failed", "reason_code": "turbo_plan_missing", "detail": missing})
    try:
        scope = _saved_scope(root, saved)
    except (OSError, ValueError) as exc:  # the request's own --tasks-file is gone or bad: no scope to hold the plan to
        return _conclude(run_, {**head, "status": "blocked", "reason_code": "turbo_scope_unavailable", "detail": str(exc)})
    checked = plan_scope.check_response(text, scope, root) if scope is not None else None
    if checked is not None and not checked.ok:
        return _conclude(run_, _refusal_document(run_, head, root, operations, checked.violations, scope))
    try:
        result = await apply_plan(root, operations, "host-1", scope=scope)
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
    if scope is not None:
        document["scope"] = _scope_summary(scope, checked.widenings)
    if verify and result["applied"]:
        run_.enter("verify")
        document["verify"], _output = await _run_verify(root, verify, run_)
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
    from . import structured_output, turbo_provider
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
    mode, why = structured_output.provider_receipt(turbo_provider.model_name())
    head = {**head, "run_id": run_.run_id, "structured_output": mode, "structured_reason": why, **plan_prompt()}
    complete = functools.partial(
        turbo_provider.complete, session_id=turbo_provider.session_id_for(root), repo_root=root,
        **structured_output.provider_fields(turbo_provider.model_name(), tasks, root))
    scope_for = functools.partial(task_scope, root)  # every answer is held to the scope of the tasks it answers
    # The saved survey marker belongs to one run. Ask Mapper again on every invocation: its own
    # tree-state cache keeps an unchanged tree free and byte-identical, and a changed tree gets a new map.
    (root / ".simplicio-loop" / "turbo-survey.json").unlink(missing_ok=True)
    started = time.time()
    run_.enter("orient")
    run_.enter("plan")
    try:
        # dev-cli applies run inside run_turbo, between the model calls of each wave; "apply" is entered once it returns.
        result = await run_turbo(root, tasks, complete, scope_for=scope_for)
    except RuntimeError as exc:
        return _conclude(run_, {**head, "status": "blocked", "reason_code": "turbo_engine_error",
                                "detail": str(exc), "tasks": len(tasks)})
    refusals: list[list[str]] = [v for o in result["outcomes"] for v in o.get("rejections", [])]
    for outcome in result["outcomes"]:  # an answer refused by the contract or the scope, then asked again or ended
        for number, retry in enumerate(outcome.get("retries", []), start=1):
            run_.refused(retry["violations"], "retry", number)
        if outcome.get("needs_human"):
            run_.refused(outcome["rejections"][-1], "needs_human", len(outcome["rejections"]))
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
        document["verify"], output = await _run_verify(root, verify, run_)
        if not document["verify"]["passed"]:
            # One repair call with the test output, then the tests run again.
            repair = await repair_with_test_output(root, tasks, complete, output, scope_for=scope_for)
            calls.extend(repair["llm_calls"])
            refusals.extend(repair["rejections"])
            receipts.extend(run_.persist_receipts(repair["commands"]))
            retry = {"attempted": True, "applied": repair["applied"], "reason": repair["reason"], "passed": False}
            if repair["applied"]:
                document["verify"], _output = await _run_verify(root, verify, run_)
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
        "structured_metrics": structured_output.output_metrics(calls, refusals),
    })
    document["wall_s"] = round(time.time() - started, 2)
    return _conclude(run_, document, calls)
