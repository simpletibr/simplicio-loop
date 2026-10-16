"""`orient --brief` for several tasks: deduplicated targets and plan groups.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence
import json

from ._base import impl

from ..state_dir import ensure_state_dir
from .orient import (ORIENT_TARGET_MAX_FILES, TURBO_EXECUTE_RULE, _is_git_worktree, _mapper_index_budget_payload, _orient_provider_provenance, _orient_target_seed_candidates, turbo_command)
from .orient_mapper import (MapperIndexRunning, MapperIndexTimedOut, _orient_deadline)

ORIENT_BRIEF_SCHEMA = "simplicio.loop-orient-brief/v1"


ORIENT_BRIEF_TARGET_CAP_BYTES = 16 * 1024


def _brief_head_tail(text: str, cap_bytes: int = ORIENT_BRIEF_TARGET_CAP_BYTES) -> tuple[str, bool]:
    """Head+tail truncation to ``cap_bytes`` (issue #1310: 16 KB/file cap on
    the brief's target content, so `apply --brief` never needs a separate
    `cat` even for a file larger than the old 2 KB inline-content ceiling)."""
    encoded = text.encode("utf-8", "surrogateescape")
    if len(encoded) <= cap_bytes:
        return text, False
    half = cap_bytes // 2
    head = encoded[:half].decode("utf-8", "replace")
    tail = encoded[-half:].decode("utf-8", "replace")
    return head + "\n...<truncated>...\n" + tail, True


def _brief_suggest_checks(root: Path) -> list[str]:
    """Suggested checks from the toolchain already on disk (issue #1310);
    never invents a command the repo has no evidence of supporting."""
    checks: list[str] = []
    if any((root / name).is_file() for name in ("pyproject.toml", "pytest.ini", "setup.cfg")):
        checks.append("pytest -q")
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, Mapping) else None
        if isinstance(scripts, Mapping) and "test" in scripts:
            checks.append("npm test")
    if (root / "Makefile").is_file():
        checks.append("make check")
    return checks


ORIENT_BRIEF_TOTAL_BUDGET_BYTES = 24 * 1024


def _brief_order_candidates_named_first(task: str, candidates: Sequence[Path]) -> list[Path]:
    """A file the task text literally names sorts before any other candidate
    the same task's ranking surfaced (issue #1318: "targets put the files
    each task names first")."""
    task_lower = task.lower()
    named = [p for p in candidates if p.name.lower() in task_lower]
    rest = [p for p in candidates if p not in named]
    return named + rest


def _brief_clip_to_budget(text: str, budget_bytes: int) -> tuple[str, bool]:
    """Hard-clip ``text`` to at most ``budget_bytes`` UTF-8 bytes, on a line
    boundary where possible, marking it truncated whenever it clips."""
    encoded = text.encode("utf-8", "surrogateescape")
    if len(encoded) <= budget_bytes:
        return text, False
    out_lines: list[str] = []
    used = 0
    for line in text.splitlines():
        line_len = len(line.encode("utf-8", "surrogateescape")) + 1
        if used + line_len > budget_bytes:
            break
        out_lines.append(line)
        used += line_len
    return "\n".join(out_lines), True


def _brief_build_targets(root: Path, tasks: Sequence[str],
                         per_task_context: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Target files with content, deduped across tasks, capped per file and,
    combined, under a total size budget (issue #1310/#1318: "the target
    files with content, no separate cat" -- but bounded, and with the file
    a task names first).

    Verifier/check/test files get the SAME head+tail treatment as any other
    target (issue #1323): they ARE the acceptance spec, so a check file that
    fits the per-file/total budget comes back in full, not a fixed head.
    """
    seen: dict[str, dict[str, Any]] = {}
    remaining_budget = ORIENT_BRIEF_TOTAL_BUDGET_BYTES
    for task, context in zip(tasks, per_task_context):
        candidates = _orient_target_seed_candidates(root, task, context)
        ordered = _brief_order_candidates_named_first(task, candidates)[:ORIENT_TARGET_MAX_FILES]
        for path in ordered:
            rel = str(path.relative_to(root))
            if rel in seen:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            trimmed, truncated = _brief_head_tail(content)
            if remaining_budget <= 0:
                seen[rel] = {"path": rel, "content": "", "truncated": True}
                continue
            clipped, budget_truncated = _brief_clip_to_budget(trimmed, remaining_budget)
            entry_bytes = len(clipped.encode("utf-8", "surrogateescape"))
            remaining_budget -= entry_bytes
            seen[rel] = {"path": rel, "content": clipped, "truncated": truncated or budget_truncated}
    return list(seen.values())


def _brief_plan_groups(tasks: Sequence[str], per_task_targets: Sequence[Sequence[str]]) -> dict[str, Any]:
    """``parallel`` for tasks touching disjoint target files, ``ordered``
    groups (declared-order lists) for tasks that share one (issue #1310)."""
    n = len(tasks)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    path_owner: dict[str, int] = {}
    for i, paths in enumerate(per_task_targets):
        for path in paths:
            if path in path_owner:
                union(path_owner[path], i)
            else:
                path_owner[path] = i

    groups: dict[int, list[str]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(tasks[i])
    parallel = [group[0] for group in groups.values() if len(group) == 1]
    ordered = [group for group in groups.values() if len(group) > 1]
    return {"parallel": parallel, "ordered": ordered}


def _brief_annotate_route_next(route: Mapping[str, Any], root: Path,
                               status: str, task_count: int = 1,
                               tasks: Sequence[str] = ()) -> dict[str, Any]:
    """Point ``route["next"]`` at ``simplicio-loop turbo`` for these tasks.

    The host runs that one command; turbo plans with the model, applies with
    dev-cli and verifies with ``--verify``. A BLOCKED brief passes through unchanged.
    """
    from ..effort import PHASE_EFFORT

    if status == "BLOCKED":
        return dict(route)
    del task_count
    out = dict(route)
    out["mode"] = "deliver"
    out["execute"] = "turbo"
    out["execute_rule"] = TURBO_EXECUTE_RULE
    out["next"] = [
        {"step": turbo_command(root, tasks), "phase": "execute", "effort": PHASE_EFFORT["execute"]},
    ]
    return out


def _brief_apply_command(root: Path, repo_state_chain: Mapping[str, Any],
                         generations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """issue #1323: ``example`` is a concrete, valid ops.json -- a create
    (``find: ""``), a dependent edit (``depends_on``) and a ``check`` -- with
    ``repo_state_chain``/``brief_generations`` copied verbatim from this same
    brief, so the host never opens ``simplicio_loop/apply.py`` to learn the
    ops format."""
    example = {
        "tasks": [
            {
                "id": "example-create-notes",
                "operations": [{"path": "NOTES.md", "find": "", "replace": "# Notes\n"}],
                "check": None,
                "depends_on": [],
            },
            {
                "id": "example-extend-notes",
                "operations": [{"path": "NOTES.md", "find": "# Notes\n",
                                "replace": "# Notes\n\n## Details\n"}],
                "check": "python3 -c \"assert 'Details' in open('NOTES.md').read()\"",
                "depends_on": ["example-create-notes"],
            },
        ],
        "repo_state_chain": dict(repo_state_chain),
        "brief_generations": [dict(g) for g in generations],
    }
    return {
        "command": f"simplicio-loop apply .simplicio-loop/ops.json --repo {root} --json",
        "ops_format": {
            "tasks": [{
                "id": "<task-id>",
                "operations": [{"path": "<repo-relative>", "find": "<exact unique text>", "replace": "<new text>"}],
                "check": "<optional shell check command>",
                "depends_on": ["<other task id, optional>"],
            }],
            "repo_state_chain": "<copy verbatim from this brief's own repo_state_chain field>",
            "brief_generations": "<copy verbatim from this brief's own generations field (Mapper provenance)>",
        },
        "example": example,
    }


def _orient_brief_impl(root: Path, tasks: list[str], *,
                  targets: list[str] | None = None) -> dict[str, Any]:
    """Turn 1 of the plan-once/apply-once hot path (issue #1310): a compact
    rendering of the SAME Mapper survey ``orient`` always runs, for one or
    more tasks -- never a shortcut around it. Route first, then deduped
    target content, plan groups, suggested checks, the Mapper generation +
    context hash (so cache reuse stays measurable), and the exact ``apply``
    command.
    """
    task_list = [str(t) for t in tasks if str(t).strip()]
    if not task_list:
        return {
            "schema": ORIENT_BRIEF_SCHEMA, "status": "BLOCKED", "reason": "no_tasks",
            "route": {"mode": "converge", "justification": "no task given", "resolved_files": [], "next": []},
        }
    if not _is_git_worktree(root):
        return {
            "schema": ORIENT_BRIEF_SCHEMA, "status": "BLOCKED",
            "reason": "not_a_git_repo", "reason_code": "not_a_git_repo",
            "hint": f"{root} is not inside a git work tree; orient refuses to survey it",
            "route": {"mode": "converge", "justification": "not a git work tree",
                      "resolved_files": [], "next": []},
        }

    per_task: list[dict[str, Any]] = []
    deadline = _orient_deadline()
    for task in task_list:
        try:
            payload, code = impl()._orient_core(root, task, targets, verbose=True, deadline=deadline)
        except (MapperIndexTimedOut, MapperIndexRunning) as exc:
            blocked = _mapper_index_budget_payload(ORIENT_BRIEF_SCHEMA, exc, root)
            blocked["tasks"] = task_list
            blocked["route"] = {"mode": "converge", "justification": blocked["reason"],
                                 "resolved_files": [], "next": [blocked["next"]]}
            return blocked
        per_task.append({"task": task, "payload": payload, "exit_code": code})

    routes = [item["payload"].get("route") or {} for item in per_task]
    if len(task_list) == 1:
        overall_route = routes[0]
    else:
        overall_mode = "converge" if any(r.get("mode") == "converge" for r in routes) else "fast-path"
        overall_route = {
            "mode": overall_mode,
            "justification": f"{len(task_list)} tasks: " + "; ".join(
                f"{item['task']}={r.get('mode')}" for item, r in zip(per_task, routes)
            ),
            "resolved_files": sorted({f for r in routes for f in (r.get("resolved_files") or [])}),
            "per_task": [{"task": item["task"], "mode": r.get("mode")} for item, r in zip(per_task, routes)],
        }

    contexts = [item["payload"].get("context") or {} for item in per_task]
    per_task_target_lists = []
    for item, context in zip(per_task, contexts):
        entries = ((item["payload"].get("targets") or {}).get("files")) or []
        all_paths = [e["path"] for e in entries if isinstance(e, Mapping) and e.get("path")]
        # Plan grouping cares about which file(s) a task actually names, not
        # every candidate a tiny/ambiguous repo's ranking surfaced (a 2-file
        # repo returns both files as "candidates" for every task) -- prefer
        # the path(s) literally mentioned in the task text when any match.
        named = [p for p in all_paths if Path(p).name.lower() in item["task"].lower()]
        per_task_target_lists.append(named or all_paths[:1])

    statuses = [item["payload"].get("status") for item in per_task]
    overall_status = "BLOCKED" if all(s == "BLOCKED" for s in statuses) else (
        "READY" if all(s in {"READY", "FALLBACK"} for s in statuses) and any(s == "READY" for s in statuses)
        else "FALLBACK"
    )

    generations = []
    for item in per_task:
        provenance = _orient_provider_provenance(item["payload"])
        generations.append({
            "task": item["task"],
            "operator": provenance.get("operator"),
            "generation": provenance.get("generation"),
            "context_hash": provenance.get("context_hash"),
        })

    from ..runner import _repo_fingerprint
    repo_state_chain = _repo_fingerprint(root)

    from ..effort import PHASE_EFFORT
    overall_route = _brief_annotate_route_next(overall_route, root, overall_status, len(task_list),
                                               tasks=[str(t) for t in task_list])

    payload: dict[str, Any] = {}
    payload["route"] = overall_route
    payload["schema"] = ORIENT_BRIEF_SCHEMA
    payload["status"] = overall_status
    payload["tasks"] = task_list
    payload["targets"] = _brief_build_targets(root, task_list, contexts)
    payload["plan"] = _brief_plan_groups(task_list, per_task_target_lists)
    payload["checks"] = _brief_suggest_checks(root)
    payload["generations"] = generations
    payload["repo_state_chain"] = repo_state_chain
    payload["apply"] = _brief_apply_command(root, repo_state_chain, generations)
    execute_steps = [
        step.get("step") for step in overall_route.get("next") or []
        if isinstance(step, Mapping) and step.get("phase") == "execute"
    ]
    if execute_steps:
        payload["apply"]["command"] = execute_steps[0]
    payload["effort"] = dict(PHASE_EFFORT)
    if overall_status != "BLOCKED":
        # `apply` refuses to run without this Mapper survey (issue #1318).
        # The project-map/generation is already ensured per-task above (in
        # the `_orient_core` loop), so this is just the survey write.
        brief_path = ensure_state_dir(root) / "brief.json"
        brief_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        from ..survey import write_survey
        write_survey(root, generations)
    return payload


def orient_brief(root: Path, tasks: list[str], *,
                  targets: list[str] | None = None) -> dict[str, Any]:
    """Public entry point (issue #1339): always returns a JSON-serializable
    dict, never raises -- any unexpected exception inside ``_orient_brief_impl``
    becomes a typed BLOCKED payload instead of propagating to the caller."""
    try:
        return _orient_brief_impl(root, tasks, targets=targets)
    except Exception as exc:
        return {
            "schema": ORIENT_BRIEF_SCHEMA, "status": "BLOCKED",
            "reason": str(exc), "reason_code": "orient_internal_error",
            "tasks": [str(t) for t in (tasks or [])],
            "route": {"mode": "converge", "justification": str(exc),
                       "resolved_files": [], "next": []},
        }
