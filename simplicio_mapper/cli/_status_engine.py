from __future__ import annotations

import contextlib
import io
import json
import os
import time

from ..context_cache import ContextCache
from ..context_pack import build_context_pack
from ..mapper import build_macro_map
from ._args import _read_json_safe
from ._background import _run_index, _spawn_background_index
from ._index_engine import (
    _artifact_paths,
    _artifacts_exist,
    _freshness_signature,
    _lock_path,
    _print_toon,
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
    if os.path.exists(_lock_path(root, out)):
        return "deep_running"
    if _index_is_fresh(root, out):
        return "complete"
    job = _read_json_safe(_map_job_path(root, out))
    if job.get("schema") == MAP_JOB_SCHEMA and not _artifacts_exist(_artifact_paths(root, out)):
        # A deep pass was requested but produced no fresh artifacts and no lock
        # is held: the background run is gone without finishing.
        return "failed"
    return "unknown"


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
    return phase


def _cache_summary(root: str, out: str, sample_limit: int = 5) -> dict:
    path = _context_cache_path(root, out)
    cache = ContextCache(path)
    return {
        "path": path.replace(os.sep, "/"),
        "exists": os.path.exists(path),
        "entries": len(cache),
        "sample_keys": cache.keys(limit=sample_limit),
    }


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
        "log": deep.get("log"),
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
    current_phase = phase or _deep_phase(root, out)
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
        "lock": os.path.exists(_lock_path(root, out)),
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
        "root": root.replace(os.sep, "/"),
        "out": os.path.abspath(os.path.join(root, out)).replace(os.sep, "/"),
        "status": status_payload,
        "evidence": status_payload["evidence"],
        "artifacts": {key: path.replace(os.sep, "/") for key, path in _artifact_paths(root, out).items()},
    }
    if opts.get("for_llm") == "toon":
        _print_toon(payload)
    elif opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"inspect phase={status_payload['phase']} fresh={status_payload['fresh']} "
            f"cache_entries={status_payload['cache']['entries']}"
        )
    return 0


def _run_handoff(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    phase = _await_terminal(root, out, opts["timeout"]) if opts["await"] else _deep_phase(root, out)
    status_payload = _status_payload(root, out, phase=phase)
    targets = _handoff_targets(root, out)
    context_pack = build_context_pack(
        root=root,
        targets=[{"path": path} for path in targets],
    )
    cache = ContextCache(_context_cache_path(root, out))
    pack_hash = context_pack.get("pack_hash")
    reasons: list[str] = []
    if not targets:
        reasons.append("no_handoff_targets")
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
        },
    }
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
        pre_locked = os.path.exists(_lock_path(root, out))
        with contextlib.redirect_stdout(io.StringIO()):
            _run_index({**opts, "json": False})
        phase = "complete" if _index_is_fresh(root, out) else "failed"
        if phase == "failed" and pre_locked:
            # Deep pass was skipped because another run holds the lock; record
            # the reason so the envelope is not a bare, unexplained "failed".
            deep["skipped_reason"] = "locked"
    else:
        spawned = _spawn_background_index(opts)
        deep["pid"] = spawned["pid"]
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
    abs_out = os.path.abspath(os.path.join(root, out))
    os.makedirs(abs_out, exist_ok=True)
    with open(_map_job_path(root, out), "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, indent=2, sort_keys=True)
        handle.write("\n")

    if opts["json"]:
        print(json.dumps(envelope, sort_keys=True))
    else:
        counts = macro["counts"]
        suffix = f" pid={deep.get('pid')}" if "pid" in deep else ""
        print(
            f"scan phase={envelope['phase']} files={counts['files']} "
            f"modules={counts['modules']} stack={macro['product']['stack']}{suffix}"
        )
    return 0


def _run_status(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    if opts["await"]:
        phase = _await_terminal(root, out, opts["timeout"])
    else:
        phase = _deep_phase(root, out)
    payload = _status_payload(root, out, phase=phase)
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"status phase={phase} lock={payload['lock']} fresh={payload['fresh']}")
    return 0
