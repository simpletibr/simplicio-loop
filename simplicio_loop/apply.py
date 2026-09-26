"""``simplicio-loop apply`` — Turn 2 of the plan-once/apply-once hot path
(issue #1310).

Takes one ops.json describing every task's operations (as produced by
``orient --brief``'s exact ``apply`` command), validates every ``find``
in memory before touching disk, applies through ``simplicio-dev-cli`` (the
mutation owner — never the LLM hand-editing), runs each task's own check
with an isolated cache environment, and writes an immutable receipt.

Ordering: independent chains (disjoint files, no ``depends_on`` edge) run
concurrently via asyncio; within a chain, apply -> check -> next is always
serial. ``apply`` fails closed on a Mapper-generation-derived repo
fingerprint gone stale since ``orient`` produced it (reusing
``simplicio_loop.runner._repo_fingerprint`` / ``_repo_state_equivalent`` --
the same generation-identity check the wave already uses), never
substituting a fabricated pass.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .survey import MISSING_HINT as SURVEY_MISSING_HINT
from .survey import MISSING_REASON as SURVEY_MISSING_REASON
from .survey import provenance as survey_provenance
from .effort import next_effort_for_status
from .runner import _repo_fingerprint, _repo_state_equivalent

APPLY_SCHEMA = "simplicio.loop-apply/v1"
APPLY_RECEIPT_SCHEMA = "simplicio.loop-apply-receipt/v1"
CHECK_TIMEOUT_S = 300
DEV_CLI_TIMEOUT_S = 180


class ApplyValidationError(ValueError):
    pass


def load_ops(source: str) -> dict[str, Any]:
    """Read ops.json from a file path, or from stdin when ``source == "-"``."""
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    return json.loads(raw)


def _ops_sha(ops: Mapping[str, Any]) -> str:
    encoded = json.dumps(ops, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normalize_tasks(ops: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks = ops.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ApplyValidationError("ops.tasks must be a non-empty list")
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, Mapping):
            raise ApplyValidationError("each task must be an object")
        task_id = str(raw.get("id") or "").strip()
        if not task_id:
            raise ApplyValidationError("each task requires a non-empty id")
        if task_id in seen_ids:
            raise ApplyValidationError(f"duplicate task id: {task_id}")
        seen_ids.add(task_id)
        operations = raw.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ApplyValidationError(f"task {task_id!r} requires a non-empty operations list")
        normalized_ops = []
        for op in operations:
            if not isinstance(op, Mapping) or not all(k in op for k in ("path", "find", "replace")):
                raise ApplyValidationError(f"task {task_id!r} has a malformed operation")
            normalized_ops.append({"path": str(op["path"]), "find": str(op["find"]), "replace": str(op["replace"])})
        out.append({
            "id": task_id,
            "operations": normalized_ops,
            "check": raw.get("check") or None,
            "depends_on": [str(d) for d in (raw.get("depends_on") or [])],
        })
    ids = {t["id"] for t in out}
    for task in out:
        unknown = [d for d in task["depends_on"] if d not in ids]
        if unknown:
            raise ApplyValidationError(f"task {task['id']!r} depends on unknown task(s): {unknown}")
    return out


def _task_paths(task: Mapping[str, Any]) -> set[str]:
    return {str(op["path"]) for op in task["operations"]}


def build_chains(tasks: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """Group task ids into chains: union of shared-file and depends_on edges.

    Two tasks that touch the same file are forced into one chain even absent
    an explicit ``depends_on`` (never run concurrent writers on one path).
    Chains coming out of this function are therefore guaranteed
    file-disjoint from one another, so concurrent chains never race on disk.
    Order inside a chain follows a ``depends_on``-first topological walk.
    """
    by_id = {t["id"]: t for t in tasks}
    parent = {t["id"]: t["id"] for t in tasks}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    path_owner: dict[str, str] = {}
    for task in tasks:
        for path in _task_paths(task):
            if path in path_owner:
                union(path_owner[path], task["id"])
            else:
                path_owner[path] = task["id"]
        for dep in task["depends_on"]:
            union(dep, task["id"])

    groups: dict[str, list[str]] = {}
    for task in tasks:
        groups.setdefault(find(task["id"]), []).append(task["id"])

    ordered_chains: list[list[str]] = []
    for ids in groups.values():
        ordered_chains.append(_topo_order_chain(ids, by_id))
    return ordered_chains


def _topo_visit(tid: str, id_set: set[str], by_id: Mapping[str, Mapping[str, Any]],
                 seen: set[str], ordered: list[str]) -> None:
    if tid in seen:
        return
    seen.add(tid)
    for dep in by_id[tid]["depends_on"]:
        if dep in id_set:
            _topo_visit(dep, id_set, by_id, seen, ordered)
    ordered.append(tid)


def _topo_order_chain(ids: Sequence[str], by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """``depends_on``-first topological walk over one chain's task ids."""
    id_set = set(ids)
    ordered: list[str] = []
    seen: set[str] = set()
    for tid in ids:
        _topo_visit(tid, id_set, by_id, seen, ordered)
    return ordered


def validate_ops(root: Path, tasks: Sequence[Mapping[str, Any]], chains: Sequence[Sequence[str]]) -> list[dict[str, Any]]:
    """Simulate every operation, in chain order, against in-memory file
    content. Returns a list of blocking problems (empty means all clear).
    No file on disk is read past the initial snapshot, and none is written.
    """
    by_id = {t["id"]: t for t in tasks}
    problems: list[dict[str, Any]] = []
    file_cache: dict[str, str | None] = {}

    def read(path: str) -> str | None:
        if path in file_cache:
            return file_cache[path]
        full = root / path
        if full.is_file():
            try:
                file_cache[path] = full.read_text(encoding="utf-8")
            except OSError:
                file_cache[path] = None
        else:
            file_cache[path] = None
        return file_cache[path]

    for chain in chains:
        for task_id in chain:
            task = by_id[task_id]
            for idx, op in enumerate(task["operations"]):
                path = op["path"]
                find_text = op["find"]
                current = read(path)
                if find_text == "":
                    if (root / path).exists() and current:
                        problems.append({"task": task_id, "path": path, "op_index": idx,
                                          "reason": "create_target_exists"})
                        continue
                    file_cache[path] = op["replace"]
                    continue
                if current is None:
                    problems.append({"task": task_id, "path": path, "op_index": idx,
                                      "reason": "path_not_found"})
                    continue
                count = current.count(find_text)
                if count == 0:
                    problems.append({"task": task_id, "path": path, "op_index": idx,
                                      "reason": "find_not_found", "find": find_text[:200]})
                    continue
                if count > 1:
                    problems.append({"task": task_id, "path": path, "op_index": idx,
                                      "reason": "find_not_unique", "count": count})
                    continue
                file_cache[path] = current.replace(find_text, op["replace"], 1)
    return problems


def _isolated_check_env(*, base_env: Mapping[str, str] | None, run_id: str, task_id: str) -> dict[str, str]:
    """Environment for a task's check subprocess, isolated from siblings so
    concurrent checks never collide on cache byproducts."""
    env = dict(base_env if base_env is not None else os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_addopts = env.get("PYTEST_ADDOPTS", "")
    if "no:cacheprovider" not in existing_addopts:
        env["PYTEST_ADDOPTS"] = (existing_addopts + " -p no:cacheprovider").strip()
    env["COVERAGE_FILE"] = f".simplicio-loop/apply/{run_id}/{task_id}.coverage"
    return env


def _resolve_dev_cli() -> str:
    return shutil.which("simplicio-dev-cli") or "simplicio-dev-cli"


def _apply_task_devcli(root: Path, task: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    """Apply one task's operations through simplicio-dev-cli's 2-step
    contract (compile pins hashes without mutating; apply mutates)."""
    dev_cli = _resolve_dev_cli()
    minimal_path = run_dir / f"{task['id']}.ops.json"
    compiled_path = run_dir / f"{task['id']}.plan.json"
    minimal_path.write_text(json.dumps({"operations": task["operations"]}, ensure_ascii=False), encoding="utf-8")
    steps: list[dict[str, Any]] = []
    for args, label in (
        ([dev_cli, "edit", "--root", str(root), "--plan", str(minimal_path),
          "--compile", str(compiled_path), "--json"], "compile"),
        ([dev_cli, "edit", "--root", str(root), "--plan", str(compiled_path),
          "--apply", "--json"], "apply"),
    ):
        try:
            proc = subprocess.run(
                args, cwd=str(root), stdin=subprocess.DEVNULL, capture_output=True,
                text=True, close_fds=True, timeout=DEV_CLI_TIMEOUT_S, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            steps.append({"step": label, "ok": False, "error": str(exc)})
            return {"ok": False, "steps": steps, "reason_code": "dev_cli_unavailable"}
        raw = (proc.stdout or "").strip()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw_tail": raw[-2000:]}
        step_ok = proc.returncode == 0
        steps.append({"step": label, "ok": step_ok, "returncode": proc.returncode,
                      "result": parsed, "stderr": (proc.stderr or "")[-2000:]})
        if not step_ok:
            return {"ok": False, "steps": steps, "reason_code": f"dev_cli_{label}_failed"}
    return {"ok": True, "steps": steps, "reason_code": None}


async def _run_check(root: Path, check: str, *, run_id: str, task_id: str) -> dict[str, Any]:
    env = _isolated_check_env(base_env=os.environ, run_id=run_id, task_id=task_id)
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            check, cwd=str(root), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CHECK_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"ok": False, "reason_code": "check_timeout", "duration_s": time.monotonic() - started}
        ok = proc.returncode == 0
        return {
            "ok": ok, "returncode": proc.returncode,
            "stdout_tail": stdout.decode("utf-8", "replace")[-2000:],
            "stderr_tail": stderr.decode("utf-8", "replace")[-2000:],
            "duration_s": time.monotonic() - started,
        }
    except OSError as exc:
        return {"ok": False, "reason_code": "check_spawn_failed", "error": str(exc),
                "duration_s": time.monotonic() - started}


async def _run_chain(root: Path, chain: Sequence[str], by_id: Mapping[str, Mapping[str, Any]],
                      run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    loop = asyncio.get_event_loop()
    for task_id in chain:
        task = by_id[task_id]
        started = time.monotonic()
        apply_result = await loop.run_in_executor(None, _apply_task_devcli, root, task, run_dir)
        record: dict[str, Any] = {
            "id": task_id, "apply": apply_result,
            "apply_duration_s": time.monotonic() - started,
        }
        if not apply_result["ok"]:
            record["status"] = "FAIL"
            results.append(record)
            # Stop the chain: a dependent task's find would now be checked
            # against a tree that never received the change it depends on.
            for remaining_id in chain[len(results):]:
                results.append({"id": remaining_id, "status": "SKIPPED",
                                 "reason_code": "upstream_task_failed"})
            break
        check = task.get("check")
        if check:
            check_result = await _run_check(root, check, run_id=run_id, task_id=task_id)
            record["check"] = check_result
            record["status"] = "PASS" if check_result["ok"] else "FAIL"
        else:
            record["status"] = "PASS"
        results.append(record)
        if record["status"] == "FAIL":
            for remaining_id in chain[len(results):]:
                results.append({"id": remaining_id, "status": "SKIPPED",
                                 "reason_code": "upstream_task_failed"})
            break
    return results


def _diff_escalation_module():
    spec = importlib.util.spec_from_file_location(
        "_simplicio_diff_escalation",
        Path(__file__).parent / "_bundle" / "scripts" / "diff_escalation.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _measure_diff(root: Path, before: Mapping[str, str]) -> dict[str, Any]:
    try:
        mod = _diff_escalation_module()
        numstat = subprocess.run(
            ["git", "diff", "--numstat", before.get("head", "") or "HEAD"],
            cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, close_fds=True, timeout=30, check=False,
        )
        rows = mod.parse_numstat(numstat.stdout or "") if numstat.returncode == 0 else []
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=str(root), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            close_fds=True, timeout=30, check=False,
        )
        new_files = [line[3:].strip() for line in (status.stdout or "").splitlines() if line.startswith("??")]
        changed = [row["path"] for row in rows]
        added = sum(row["added"] for row in rows)
        deleted = sum(row["deleted"] for row in rows)
        sensitive = [p for p in changed if mod._sensitive(p)]
        return mod.evaluate("fast-path", changed, added, deleted, new_files, sensitive)
    except (OSError, subprocess.SubprocessError, Exception):  # noqa: BLE001 — measurement is best-effort evidence
        return {"schema": "simplicio.diff-escalation/v1", "measured": False}


def _ops_ignore_paths(root: Path, ops_path: str | Path | None) -> set[str]:
    """The ops source file's own repo-relative path, so it never counts as a
    drift when `apply` re-checks the repo state it was planned against
    (issue #1318): an ops.json written at the repo root -- not just under
    `.simplicio-loop/`, which `_repo_fingerprint` already excludes -- must
    never itself make the stale-state check fail."""
    if not ops_path or ops_path == "-":
        return set()
    try:
        resolved = Path(ops_path).resolve()
    except OSError:
        return set()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return set()
    return {rel.as_posix()}


def run(ops: Mapping[str, Any], *, repo: str | Path = ".", ops_path: str | Path | None = None) -> dict[str, Any]:
    """Execute one ops.json against ``repo``. Never raises for input errors;
    those come back as a BLOCKED payload. ``ops_path`` (the file `ops` was
    loaded from, when any) is excluded from the repo-state freshness check --
    see `_ops_ignore_paths`."""
    root = Path(repo).resolve()
    run_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    ops_sha = _ops_sha(ops)
    ignore_paths = _ops_ignore_paths(root, ops_path)

    provenance = survey_provenance(root, ops.get("brief_generations"))
    if provenance is None:
        return {
            "schema": APPLY_SCHEMA, "status": "BLOCKED", "reason_code": SURVEY_MISSING_REASON,
            "run_id": run_id, "ops_sha": ops_sha, "hint": SURVEY_MISSING_HINT,
            "next_effort": next_effort_for_status("BLOCKED"),
        }

    expected_state = ops.get("repo_state_chain") if isinstance(ops.get("repo_state_chain"), Mapping) else None
    current_state: dict[str, str] | None = None
    if expected_state is not None:
        current_state = _repo_fingerprint(root, ignore_paths=ignore_paths)
        if not _repo_state_equivalent(dict(expected_state), current_state):
            return {
                "schema": APPLY_SCHEMA, "status": "BLOCKED", "reason_code": "stale_mapper_generation",
                "run_id": run_id, "ops_sha": ops_sha,
                "expected_repo_state_chain": dict(expected_state), "current_repo_state_chain": current_state,
                "next_effort": next_effort_for_status("BLOCKED"),
            }

    try:
        tasks = _normalize_tasks(ops)
    except ApplyValidationError as exc:
        return {"schema": APPLY_SCHEMA, "status": "BLOCKED", "reason_code": "ops_invalid",
                "run_id": run_id, "ops_sha": ops_sha, "hint": str(exc),
                "next_effort": next_effort_for_status("BLOCKED")}

    chains = build_chains(tasks)
    problems = validate_ops(root, tasks, chains)
    if problems:
        return {
            "schema": APPLY_SCHEMA, "status": "BLOCKED", "reason_code": "validation_failed",
            "run_id": run_id, "ops_sha": ops_sha, "blocked": problems,
            "hint": "fix the listed find/path before retrying; nothing was written",
            "next_effort": next_effort_for_status("BLOCKED"),
        }

    run_dir = root / ".simplicio-loop" / "apply" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    before_state = current_state if current_state is not None else _repo_fingerprint(root, ignore_paths=ignore_paths)
    by_id = {t["id"]: t for t in tasks}

    async def _run_all() -> list[list[dict[str, Any]]]:
        return await asyncio.gather(*(_run_chain(root, chain, by_id, run_dir, run_id) for chain in chains))

    chain_results = asyncio.run(_run_all())
    task_results: list[dict[str, Any]] = [item for chain in chain_results for item in chain]
    overall = "PASS" if all(r.get("status") == "PASS" for r in task_results) else "FAIL"

    after_state = _repo_fingerprint(root, ignore_paths=ignore_paths)
    diff = _measure_diff(root, before_state)

    receipt = {
        "schema": APPLY_RECEIPT_SCHEMA,
        "run_id": run_id,
        "ops_sha": ops_sha,
        "chains": chains,
        "tasks": task_results,
        "status": overall,
        "repo_state_before": before_state,
        "repo_state_after": after_state,
        "diff": diff,
        "mapper_fast": provenance,
        "created_at": time.time(),
    }
    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "schema": APPLY_SCHEMA,
        "status": overall,
        "run_id": run_id,
        "ops_sha": ops_sha,
        "tasks": task_results,
        "receipt_path": str(receipt_path),
        "diff": diff,
        "next_effort": next_effort_for_status(overall),
    }


def _slim_task_view(task_result: Mapping[str, Any]) -> dict[str, Any]:
    """Per-task view for the default (non-``--pretty``) CLI result (issue
    #1336): ``id``/``status`` always; a short failing-check tail (last 20
    lines) and a ``reason_code`` only on ``FAIL``/``SKIPPED``. Full detail
    (every apply step, full stdout/stderr, the diff) stays in the receipt
    file ``run()`` already writes at ``receipt_path`` -- this view never
    drops information, it moves it behind a path."""
    status = task_result.get("status")
    view: dict[str, Any] = {"id": task_result.get("id"), "status": status}
    if status == "SKIPPED":
        view["reason_code"] = task_result.get("reason_code")
        return view
    if status != "FAIL":
        return view
    apply_result = task_result.get("apply") or {}
    if not apply_result.get("ok", True) and apply_result.get("reason_code"):
        view["reason_code"] = apply_result["reason_code"]
    check = task_result.get("check")
    if isinstance(check, Mapping):
        if check.get("reason_code"):
            view["reason_code"] = check["reason_code"]
        tail = check.get("stderr_tail") or check.get("stdout_tail") or ""
        if tail:
            view["check_tail"] = "\n".join(tail.splitlines()[-20:])
    return view


def _slim_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """The default ``apply`` stdout payload (issue #1336): a short summary
    instead of every task's full apply/check detail and the diff -- both
    already persisted in full at ``receipt_path``. A ``BLOCKED`` result
    (validation/staleness/missing-survey; no ``tasks`` key) is already small
    and every field on it is load-bearing, so it passes through unchanged."""
    if result.get("status") == "BLOCKED":
        return dict(result)
    return {
        "schema": result.get("schema"),
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "ops_sha": result.get("ops_sha"),
        "tasks": [_slim_task_view(t) for t in result.get("tasks") or []],
        "receipt_path": result.get("receipt_path"),
        "next_effort": result.get("next_effort"),
    }


def _dump(payload: Mapping[str, Any], *, pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main(source: str, repo: str = ".", as_json: bool = True, pretty: bool = False) -> int:
    try:
        ops = load_ops(source)
    except (OSError, json.JSONDecodeError) as exc:
        print(_dump({"schema": APPLY_SCHEMA, "status": "BLOCKED",
                     "reason_code": "ops_unreadable", "hint": str(exc)}, pretty=pretty))
        return 2
    result = run(ops, repo=repo, ops_path=source)
    rendered = result if pretty else _slim_result(result)
    print(_dump(rendered, pretty=pretty))
    return 0 if result.get("status") == "PASS" else (2 if result.get("status") == "BLOCKED" else 1)
