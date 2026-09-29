"""`simplicio-loop turbo`: the benchmarked engine as the default way to run a task.

Survey with Mapper once, then send one model call per lane (`turbo_provider`: OpenRouter,
pinned session, reasoning off), then have simplicio-dev-cli apply each plan. `--verify`
optionally runs a test command afterwards. The output is one compact JSON document, and
the exit code is 0 ok / 1 failed / 2 blocked.
"""
from __future__ import annotations

import functools
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from . import turbo_provider
from .turbo import run_turbo

SCHEMA = "simplicio.turbo-run/v1"
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


def run(repo: str, texts: Sequence[str], target: str | None = None, context: Sequence[str] = (),
        tasks_file: str | None = None, verify: str | None = None) -> int:
    root = Path(repo).resolve()
    head = {"schema": SCHEMA, "repo": str(root), "model": turbo_provider.model_name(),
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
    calls = result["llm_calls"]
    totals = result["totals"]
    document: dict[str, Any] = {
        **head,
        "status": "ok" if result["applied_all"] else "failed",
        "tasks": len(tasks),
        "model_calls": len(calls),
        "retries": max(0, len(calls) - len(result["outcomes"])),
        "applied": [i for o in result["outcomes"] if o["applied"] for i in o["tasks"]],
        "failed": [o for o in result["outcomes"] if not o["applied"]],
        "tokens": {k: totals[k] for k in ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")},
        "cache_hit_pct": round(100 * totals["cached_tokens"] / totals["prompt_tokens"], 1)
        if totals["prompt_tokens"] else 0.0,
        "cost_usd": round(sum(c.get("cost_usd") or 0 for c in calls), 6),
        "calls": [{k: c.get(k) for k in ("latency_s", "provider", "prompt_tokens", "cached_tokens",
                                         "completion_tokens")} for c in calls],
        "verify": None,
    }
    if verify and result["applied_all"]:
        proc = subprocess.run(verify, shell=True, cwd=root, capture_output=True, text=True, timeout=900)  # noqa: S602
        output = (proc.stdout + proc.stderr).strip()
        document["verify"] = {"command": verify, "passed": proc.returncode == 0, "returncode": proc.returncode,
                              "output_tail": output[-1500:]}
        if proc.returncode != 0:
            document["status"] = "failed"
    document["wall_s"] = round(time.time() - started, 2)
    _emit(document)
    return 0 if document["status"] == "ok" else 1
