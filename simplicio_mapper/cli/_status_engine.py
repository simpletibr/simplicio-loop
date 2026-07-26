from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Mapping

from ..context_cache import ContextCache
from ..context_pack import build_context_pack
from ..context_snapshot import build_context_snapshot
from ..execution_context import build_execution_context
from ..mapper import build_macro_map
from ..retrieval_index import DEFAULT_TOKEN_BUDGET, load_retrieval_index, select_context_targets
from ..task_batch import build_task_batch
from ..task_intent import parse_task_intent
from ..task_traceability import build_task_traceability
from ._args import _read_json_safe
from ._background import _spawn_background_index, _spawn_index_process
from ._index_engine import (
    _artifact_paths,
    _artifacts_exist,
    _freshness_signature,
    _inspect_index_lock,
    _lock_path,
    _print_toon,
    _process_is_alive,
    _process_start_token,
    _read_index_state,
    _state_path,
)
from ._shared import (
    INDEX_STATE_SCHEMA,
    MAP_HANDOFF_SCHEMA,
    MAP_INSPECTION_SCHEMA,
    MAP_JOB_SCHEMA,
    MAP_STATUS_SCHEMA,
)


def _map_job_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "map-job.json")


def _inspection_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "map-inspection.json")


def _write_json_atomic(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp-{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _write_map_job(root: str, out: str, envelope: dict) -> None:
    _write_json_atomic(_map_job_path(root, out), envelope)


def _terminate_index_worker(child: subprocess.Popen) -> None:
    """Stop an index worker and its descendants after a bounded timeout."""
    if child.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            child.kill()
    else:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def _project_map_path(root: str, out: str) -> str:
    return _artifact_paths(root, out)["project_map"]


def _context_cache_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "context-cache.json")


def _index_is_fresh(root: str, out: str) -> bool:
    """True when the on-disk artifacts match the current freshness signature."""
    state = _read_index_state(root, out)
    if state.get("schema") != INDEX_STATE_SCHEMA:
        return False
    if not _artifacts_exist(_artifact_paths(root, out)):
        return False
    return state.get("signature") == _freshness_signature(root, out)


def _deep_phase(root: str, out: str) -> str:
    """Derive the deep-pass phase: ``deep_running|complete|failed|unknown``."""
    lock_status = _inspect_index_lock(root, out, recover=True)
    if lock_status["active"]:
        return "deep_running"
    if _index_is_fresh(root, out):
        return "complete"
    job = _read_json_safe(_map_job_path(root, out))
    if job.get("schema") == MAP_JOB_SCHEMA:
        deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
        pid = deep.get("pid")
        if job.get("phase") in ("macro_done", "deep_running") and isinstance(pid, int) and _process_is_alive(pid):
            expected_start = deep.get("process_start")
            actual_start = _process_start_token(pid)
            if (
                not expected_start
                or expected_start == "unknown"
                or not actual_start
                or expected_start == actual_start
            ):
                # Covers the short spawn -> lock creation window.
                return "deep_running"
        if job.get("phase") in ("macro_done", "deep_running", "failed", "timeout") or not _artifacts_exist(
            _artifact_paths(root, out)
        ):
            # The background owner is gone (or its PID was reused) without a
            # fresh index, so status must become terminal rather than hang.
            return "failed"
    return "unknown"


def _worker_failure_reason(root: str, out: str) -> str | None:
    """Return a terminal reason when a recorded deep worker disappeared."""
    job = _read_json_safe(_map_job_path(root, out))
    if job.get("schema") != MAP_JOB_SCHEMA:
        return None
    deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
    pid = deep.get("pid")
    if not isinstance(pid, int) or _process_is_alive(pid):
        return None
    if job.get("phase") == "timeout":
        return str(deep.get("failure_reason") or "scan_timeout")
    if job.get("phase") == "failed" and deep.get("failure_reason"):
        return str(deep["failure_reason"])
    if job.get("phase") in ("macro_done", "deep_running"):
        return "worker_died_before_terminal"
    return None


def _await_terminal(root: str, out: str, timeout: int, poll: float = 0.2) -> str:
    """Block until the deep phase leaves ``deep_running`` or the timeout fires.

    ``timeout=0`` is a non-blocking single poll: it returns the current phase
    without waiting.
    """
    deadline = time.monotonic() + max(0, timeout)
    phase = _deep_phase(root, out)
    while phase == "deep_running" and time.monotonic() < deadline:
        time.sleep(poll)
        phase = _deep_phase(root, out)
    if phase == "deep_running":
        # This is the terminal result of the bounded *await operation*, not a
        # claim that the worker stopped.  The live-owner lock remains intact
        # and a later status call may still observe ``deep_running`` or
        # ``complete``.
        return "timeout"
    return phase


def _cache_summary(root: str, out: str, sample_limit: int = 5) -> dict:
    path = _context_cache_path(root, out)
    cache = ContextCache(path)
    return {
        "path": path.replace(os.sep, "/"),
        "exists": os.path.exists(path),
        "entries": len(cache),
        "sample_keys": cache.keys(limit=sample_limit),
        "stats": cache.stats(),
    }


def _load_mapper_artifacts(root: str, out: str) -> dict[str, dict]:
    paths = _artifact_paths(root, out)
    return {
        "project_map": _read_json_safe(paths["project_map"]),
        "symbol_index": _read_json_safe(paths["symbol_index"]),
        "call_graph": _read_json_safe(paths["call_graph"]),
        "architecture_inventory": _read_json_safe(paths["architecture_inventory"]),
        "precedent_index": _read_json_safe(paths["precedent_index"]),
    }


def _target_rows_from_selection(selection: Mapping[str, object]) -> list[dict]:
    spans_by_path: dict[str, list[tuple[int, int]]] = {}
    for row in selection.get("expanded_spans", []):
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "").replace(os.sep, "/")
        if not path:
            continue
        spans: list[tuple[int, int]] = []
        for span in row.get("spans", []):
            if not isinstance(span, Mapping):
                continue
            start = span.get("start_line")
            end = span.get("end_line")
            if isinstance(start, int) and isinstance(end, int) and start > 0 and end >= start:
                spans.append((start, end))
        spans_by_path[path] = spans
    target_rows: list[dict] = []
    for row in selection.get("targets", []):
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "").replace(os.sep, "/")
        if not path:
            continue
        target_rows.append(
            {
                **dict(row),
                "path": path,
                "ranges": spans_by_path.get(path, []),
            }
        )
    return target_rows


def _selection_inputs(goal: str, task_intent: dict | None) -> tuple[str, dict | None]:
    if goal.strip() or not isinstance(task_intent, dict):
        return goal, task_intent
    story = task_intent.get("story") if isinstance(task_intent.get("story"), dict) else {}
    parts = [
        str(task_intent.get("system") or "").strip(),
        str(task_intent.get("functionality") or "").strip(),
        str(story.get("actor") or "").strip(),
        str(story.get("desire") or "").strip(),
        str(story.get("benefit") or "").strip(),
    ]
    derived_goal = " ".join(part for part in parts if part)
    return derived_goal, None


def _job_summary(root: str, out: str) -> dict | None:
    job = _read_json_safe(_map_job_path(root, out))
    if job.get("schema") != MAP_JOB_SCHEMA:
        return None
    deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
    return {
        "phase": job.get("phase"),
        "sync": bool(job.get("sync")),
        "created_at": job.get("created_at"),
        "pid": deep.get("pid"),
        "process_start": deep.get("process_start"),
        "log": deep.get("log"),
        "exit_code": deep.get("exit_code"),
        "failure_reason": deep.get("failure_reason"),
        "timeout_seconds": deep.get("timeout_seconds"),
        "poll": deep.get("poll"),
    }


def _path_evidence(path: str) -> dict:
    normalized = path.replace(os.sep, "/")
    payload = {
        "path": normalized,
        "exists": os.path.exists(path),
    }
    if not payload["exists"]:
        return payload
    try:
        stat = os.stat(path)
    except OSError as error:
        payload["stat_error"] = str(error)
        return payload
    payload["size_bytes"] = stat.st_size
    payload["modified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime))
    return payload


def _artifact_evidence(root: str, out: str) -> dict[str, dict]:
    paths = {
        **_artifact_paths(root, out),
        "index_state": _state_path(root, out),
        "map_job": _map_job_path(root, out),
        "context_cache": _context_cache_path(root, out),
    }
    return {key: _path_evidence(path) for key, path in paths.items()}


def _status_warnings(
    *,
    phase: str,
    fresh: bool,
    artifacts_present: bool,
) -> list[str]:
    warnings: list[str] = []
    if not artifacts_present:
        warnings.append("artifacts_missing")
    if phase == "deep_running":
        warnings.append("deep_pass_in_progress")
    elif phase == "failed":
        warnings.append("deep_pass_failed")
    elif phase == "unknown" and not fresh:
        warnings.append("artifacts_not_fresh")
    return warnings


def _status_payload(root: str, out: str, *, phase: str | None = None) -> dict:
    lock_status = _inspect_index_lock(root, out, recover=True)
    current_phase = phase or _deep_phase(root, out)
    worker_failure = _worker_failure_reason(root, out)
    state = _read_index_state(root, out)
    counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
    artifacts_present = _artifacts_exist(_artifact_paths(root, out))
    fresh = _index_is_fresh(root, out)
    return {
        "schema": MAP_STATUS_SCHEMA,
        "root": root.replace(os.sep, "/"),
        "out": os.path.abspath(os.path.join(root, out)).replace(os.sep, "/"),
        "phase": current_phase,
        "terminal": current_phase != "deep_running",
        "lock": lock_status["active"],
        "lock_status": lock_status,
        "failure_reason": (
            "scan_timeout"
            if current_phase == "timeout"
            else worker_failure
            if current_phase == "failed"
            else None
        ),
        "retry_guidance": (
            "rerun status --await with a larger timeout; worker is still active"
            if current_phase == "timeout" and lock_status.get("reason_code") == "lock_live_owner"
            else "rerun scan; lock is owned by a live process"
            if lock_status.get("reason_code") == "lock_live_owner"
            else "rerun scan to recover and rebuild"
            if current_phase == "failed"
            else None
        ),
        "fresh": fresh,
        "artifacts_present": artifacts_present,
        "state_path": _state_path(root, out).replace(os.sep, "/"),
        "updated_at": state.get("updated_at"),
        "lock_path": _lock_path(root, out).replace(os.sep, "/"),
        "map_job_path": _map_job_path(root, out).replace(os.sep, "/"),
        "project_map_path": _project_map_path(root, out).replace(os.sep, "/"),
        "counts": counts,
        "job": _job_summary(root, out),
        "cache": _cache_summary(root, out),
        "evidence": {
            "artifacts": _artifact_evidence(root, out),
        },
        "warnings": _status_warnings(
            phase=current_phase,
            fresh=fresh,
            artifacts_present=artifacts_present,
        ),
        "commands": {
            "poll": f"simplicio-mapper status {root} --json",
            "refresh": f"simplicio-mapper index {root} --json",
            "inspect": f"simplicio-mapper inspect {root} --json",
            "handoff": f"simplicio-mapper handoff {root} --json",
        },
    }


def _handoff_targets(root: str, out: str, limit: int = 8) -> list[str]:
    project_map = _read_json_safe(_project_map_path(root, out))
    candidates: list[str] = []
    for key in ("recent_changes", "changed_files", "entry_points", "test_files"):
        values = project_map.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            path = value.get("path") if isinstance(value, dict) else value
            if not isinstance(path, str) or not path:
                continue
            normalized = path.replace(os.sep, "/")
            if normalized in candidates:
                continue
            if os.path.exists(os.path.join(root, normalized)):
                candidates.append(normalized)
            if len(candidates) >= limit:
                return candidates
    return candidates


def _run_inspect(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    phase = _await_terminal(root, out, opts["timeout"]) if opts["await"] else _deep_phase(root, out)
    status_payload = _status_payload(root, out, phase=phase)
    payload = {
        "schema": MAP_INSPECTION_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": root.replace(os.sep, "/"),
        "out": os.path.abspath(os.path.join(root, out)).replace(os.sep, "/"),
        "status": status_payload,
        "evidence": status_payload["evidence"],
        "artifacts": {key: path.replace(os.sep, "/") for key, path in _artifact_paths(root, out).items()},
    }
    if status_payload["terminal"]:
        receipt_path = _inspection_path(root, out)
        payload["receipt_path"] = receipt_path.replace(os.sep, "/")
        _write_json_atomic(receipt_path, payload)
    if opts.get("for_llm") == "toon":
        _print_toon(payload)
    elif opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"inspect phase={status_payload['phase']} fresh={status_payload['fresh']} "
            f"cache_entries={status_payload['cache']['entries']}"
        )
    return 1 if phase == "timeout" else 0


def _run_handoff(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    phase = _await_terminal(root, out, opts["timeout"]) if opts["await"] else _deep_phase(root, out)
    status_payload = _status_payload(root, out, phase=phase)
    artifacts = _load_mapper_artifacts(root, out)
    project_map = artifacts["project_map"]
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    goal = str(opts.get("goal") or "")
    task_intent = opts.get("task_intent") if isinstance(opts.get("task_intent"), dict) else None
    task_file = str(opts.get("task_file") or "")
    task_batch_file = str(opts.get("task_batch_file") or "")
    task_batch = None
    task_file_error = ""
    if task_file and task_intent is None:
        try:
            with open(task_file, encoding="utf-8") as handle:
                task_intent = parse_task_intent(handle.read())
        except (OSError, ValueError, TypeError) as error:
            task_file_error = f"task_file_error:{error}"
    if task_batch_file:
        try:
            with open(task_batch_file, encoding="utf-8") as handle:
                task_batch = build_task_batch(root, json.load(handle), project_map)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            task_file_error = f"task_batch_file_error:{error}"
    task_fingerprint = str(opts.get("task_fingerprint") or "")
    if not task_fingerprint and task_intent:
        task_fingerprint = str(task_intent.get("fingerprint") or "")
    requested_target = str(opts.get("target") or "")
    minimum_coverage = float(opts.get("minimum_query_coverage", 0.2))
    token_budget = int(opts.get("token_budget", DEFAULT_TOKEN_BUDGET) or DEFAULT_TOKEN_BUDGET)
    selection_goal, selection_task_intent = _selection_inputs(goal, task_intent)
    task_aware = bool(
        goal.strip() or task_intent or task_file or task_fingerprint.strip() or requested_target.strip()
    )

    selection_started = time.perf_counter()
    selection = None
    if task_aware:
        persisted_retrieval_index = load_retrieval_index(root, out)
        selection = select_context_targets(
            root,
            project_map,
            goal=selection_goal,
            task_intent=selection_task_intent,
            task_fingerprint=task_fingerprint,
            target=requested_target,
            limit=int(opts.get("limit", 8) or 8),
            symbol_index=symbol_index,
            call_graph=call_graph,
            token_budget=token_budget,
            minimum_query_coverage=minimum_coverage,
            retrieval_index=persisted_retrieval_index,
        )
        target_rows = _target_rows_from_selection(selection)
        targets = [row["path"] for row in target_rows]
    else:
        targets = _handoff_targets(root, out)
        target_rows = [{"path": path} for path in targets]
    selection_latency_ms = round((time.perf_counter() - selection_started) * 1000, 3)

    context_snapshot = build_context_snapshot(
        root,
        project_map=project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        architecture_inventory=artifacts["architecture_inventory"],
        task_query=goal,
        budget_tokens=token_budget if task_aware else 0,
    )
    context_pack = build_context_pack(
        root=root,
        targets=target_rows,
        project_map=project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=requested_target,
        query_terms=selection["query_terms"] if selection else None,
        minimum_query_coverage=minimum_coverage,
        token_budget=token_budget if task_aware else None,
        context_snapshot=context_snapshot,
    )
    explicit_target_override = bool(
        selection
        and requested_target
        and selection.get("target_resolution", {}).get("status") == "included"
        and target_rows
    )
    if selection is not None and isinstance(selection.get("query_fingerprint"), str):
        context_pack["query_fingerprint"] = selection["query_fingerprint"]
    if explicit_target_override and str(context_pack.get("needs_broader_context_reason", "")).startswith(
        "query coverage"
    ):
        context_pack["needs_broader_context"] = False
        context_pack["needs_broader_context_reason"] = ""
    cache = ContextCache(_context_cache_path(root, out))
    pack_hash = context_pack.get("pack_hash")
    reasons: list[str] = []
    if task_file_error:
        reasons.append(task_file_error)
    if not targets:
        reasons.append("task_context_insufficient" if task_aware else "no_handoff_targets")
    if not status_payload["artifacts_present"]:
        reasons.append("artifacts_missing")
    if not status_payload["fresh"]:
        reasons.append("artifacts_not_fresh")
    if context_pack.get("needs_broader_context"):
        reasons.append("needs_broader_context")
    payload = {
        "schema": MAP_HANDOFF_SCHEMA,
        "ready": not reasons,
        "reason": "; ".join(reasons),
        "targets": targets,
        "status": status_payload,
        "context_pack": context_pack,
        "evidence": {
            **status_payload["evidence"],
            "pack_hash": pack_hash,
            "target_count": len(targets),
        },
        "cache": {
            **status_payload["cache"],
            "pack_cached": isinstance(pack_hash, str) and pack_hash in cache,
            "pack_diagnostics": cache.explain(pack_hash)
            if isinstance(pack_hash, str)
            else {"present": False},
        },
    }
    if selection is not None:
        payload["selection"] = selection
        payload["metrics"] = {
            **selection["metrics"],
            "selection_latency_ms": selection_latency_ms,
            "estimated_tokens": selection["token_budget_fit"]["estimated_tokens"],
            "tokens_estimation_method": selection["token_budget_fit"]["tokenizer_policy"],
            "coverage_ratio": selection["coverage"]["ratio"],
        }
        payload["evidence"]["query_fingerprint"] = selection["query_fingerprint"]
    if task_batch is not None:
        payload["task_batch"] = task_batch
    if task_intent is not None:
        payload["traceability"] = build_task_traceability(
            root,
            task_intent,
            context_pack=context_pack,
            project_map=project_map,
            task_id=task_fingerprint,
        )
    if opts.get("execution_context"):
        payload["context_snapshot"] = context_snapshot
        effective_selection = selection or {
            "targets": target_rows,
            "expanded_spans": [
                {
                    "path": file_entry["path"],
                    "spans": [
                        {
                            "start_line": selected["start_line"],
                            "end_line": selected["end_line"],
                            "kind": "source",
                        }
                        for selected in file_entry.get("ranges", [])
                    ],
                    "tests": file_entry.get("tests", []),
                    "expand_handle": next(
                        (
                            handle.get("expand_handle", "")
                            for handle in file_entry.get("drilldown", {}).get("handles", [])
                            if isinstance(handle, dict)
                        ),
                        "",
                    ),
                }
                for file_entry in context_pack.get("files", [])
            ],
            "fidelity": {"sufficient": bool(target_rows), "dimensions": {}, "reasons": []},
            "abstained": not target_rows,
        }
        query_plan = effective_selection.get("query_plan", {})
        payload["execution_context"] = build_execution_context(
            root,
            goal=goal,
            task_fingerprint=task_fingerprint,
            acceptance_criteria=list(query_plan.get("ac_ids", []))
            if isinstance(query_plan, dict)
            else [],
            task_intent=task_intent,
            project_map=project_map,
            symbol_index=symbol_index,
            call_graph=call_graph,
            architecture_inventory=artifacts["architecture_inventory"],
            precedent_index=artifacts["precedent_index"],
            selection=effective_selection,
            context_pack=context_pack,
            context_snapshot=context_snapshot,
            token_budget=token_budget,
        )
    if opts.get("for_llm") == "toon":
        _print_toon(payload)
    elif opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"handoff phase={status_payload['phase']} targets={len(targets)} "
            f"pack_cached={payload['cache']['pack_cached']}"
        )
    return 0


def _run_macro(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    meta = dict(_read_json_safe(os.path.join(root, ".starter-meta.json")))
    if opts["stack"]:
        meta["stack"] = opts["stack"]
    if opts["product_name"]:
        meta["product_name"] = opts["product_name"]
    payload = build_macro_map(root, meta)
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        counts = payload["counts"]
        print(
            f"macro files={counts['files']} modules={counts['modules']} "
            f"screens={counts['screens']} tests={counts['tests']} "
            f"stack={payload['product']['stack']} confidence={payload['confidence']}"
        )
    return 0


def _run_scan(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    meta = dict(_read_json_safe(os.path.join(root, ".starter-meta.json")))
    if opts["stack"]:
        meta["stack"] = opts["stack"]
    if opts["product_name"]:
        meta["product_name"] = opts["product_name"]
    macro = build_macro_map(root, meta)

    ci = os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on")
    synchronous = ci or opts["sync"]

    deep: dict = {
        "state_path": _state_path(root, out).replace(os.sep, "/"),
        "lock_path": _lock_path(root, out).replace(os.sep, "/"),
        "poll": "simplicio-mapper status " + root,
    }
    if synchronous:
        spawned, child = _spawn_index_process(opts)
        deep.update({key: spawned[key] for key in ("pid", "process_start", "log")})
        deep["timeout_seconds"] = max(0, int(opts["timeout"]))
        initial_envelope = {
            "schema": MAP_JOB_SCHEMA,
            "phase": "deep_running",
            "sync": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "macro": macro,
            "deep": deep,
        }
        _write_map_job(root, out, initial_envelope)
        try:
            exit_code = child.wait(timeout=max(0, int(opts["timeout"])))
        except subprocess.TimeoutExpired:
            _terminate_index_worker(child)
            deep["failure_reason"] = "scan_timeout"
            deep["exit_code"] = child.poll()
            phase = "timeout"
        else:
            deep["exit_code"] = exit_code
            phase = "complete" if exit_code == 0 and _index_is_fresh(root, out) else "failed"

        if phase != "complete":
            # A killed worker cannot execute its finally block reliably on all
            # platforms. Recover only a lock proven to belong to the dead
            # worker; never remove a live owner's lock.
            deep["lock_status"] = _inspect_index_lock(root, out, recover=True)
            if phase == "failed" and deep.get("failure_reason") is None:
                deep["failure_reason"] = "worker_failed_before_terminal"
    else:
        spawned = _spawn_background_index(opts)
        deep["pid"] = spawned["pid"]
        deep["process_start"] = spawned["process_start"]
        deep["log"] = spawned["log"]
        phase = "macro_done"

    if opts["await"] and not synchronous:
        phase = _await_terminal(root, out, opts["timeout"])

    envelope = {
        "schema": MAP_JOB_SCHEMA,
        "phase": phase,
        "sync": synchronous,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "macro": macro,
        "deep": deep,
    }
    _write_map_job(root, out, envelope)

    if opts["json"]:
        print(json.dumps(envelope, sort_keys=True))
    else:
        counts = macro["counts"]
        suffix = f" pid={deep.get('pid')}" if "pid" in deep else ""
        print(
            f"scan phase={envelope['phase']} files={counts['files']} "
            f"modules={counts['modules']} stack={macro['product']['stack']}{suffix}"
        )
    return 1 if phase == "timeout" else 0


def _run_status(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    if opts["await"]:
        phase = _await_terminal(root, out, opts["timeout"])
        payload = _status_payload(root, out, phase=phase)
    else:
        payload = _status_payload(root, out)
        phase = payload["phase"]
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"status phase={phase} lock={payload['lock']} fresh={payload['fresh']}")
    return 1 if phase == "timeout" else 0
