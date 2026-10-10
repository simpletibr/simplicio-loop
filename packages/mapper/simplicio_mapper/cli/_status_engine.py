from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Mapping

from ..context_cache import LAYER_RENDERED_PACK, ContextCache, ContextCacheKey
from ..context_contract import canonical_sha256
from ..context_pack import CONTEXT_PACK_SCHEMA, build_context_pack
from ..context_snapshot import build_context_snapshot
from ..execution_context import build_execution_context
from ..mapper import build_macro_map
from ..retrieval_index import (
    DEFAULT_TOKEN_BUDGET,
    TOKENIZER_POLICY,
    load_retrieval_index,
    select_context_targets,
    serialized_json_bytes,
)
from ..savings import estimate_tokens
from ..task_batch import build_task_batch
from ..task_context import enforce_serialized_budget
from ..task_intent import parse_task_intent
from ..task_traceability import build_task_traceability
from ..toon import encode_toon_with_report
from ._args import _read_json_safe
from ._background import _finalize_map_job, _spawn_background_index, _spawn_index_process
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
    _record_overlay_freshness,
    _state_path,
    _write_index_state,
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


def _partial_scan_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "partial-scan.json")


def _write_json_atomic(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp-{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _print_json_utf8(payload: object) -> None:
    """Write JSON to stdout as UTF-8 bytes, ignoring the console code page.

    Windows cp1252 cannot encode characters such as ``→``. ``handoff --json``
    must still succeed when the payload is valid (#580).
    """
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = (text + "\n").encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(encoded)
        buffer.flush()
        return
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="surrogateescape")
        except (OSError, ValueError, AttributeError):
            pass
    sys.stdout.write(text + "\n")


def _handoff_serialization(payload: Mapping[str, object], output_format: str) -> tuple[bytes, int]:
    if output_format == "toon":
        text, _fallbacks = encode_toon_with_report(payload)
        serialized = (text + "\n").encode("utf-8")
    else:
        serialized = serialized_json_bytes(payload) + b"\n"
    return serialized, estimate_tokens(serialized.decode("utf-8"))


def _default_handoff_output_format(payload: Mapping[str, object], token_budget: int) -> str:
    """Choose the economical format without adding a second fit pass."""
    toon_serialized, _ = _handoff_serialization(payload, "toon")
    json_serialized, _ = _handoff_serialization(payload, "json")
    toon_tokens = estimate_tokens(toon_serialized.decode("utf-8"))
    json_tokens = estimate_tokens(json_serialized.decode("utf-8"))
    if toon_tokens < json_tokens:
        return "toon"
    if toon_tokens > token_budget and json_tokens > token_budget and toon_tokens * 100 <= json_tokens * 125:
        return "toon"
    return "json"


def _handoff_reference(root: str, out: str, kind: str, payload: Mapping[str, object]) -> dict:
    serialized = serialized_json_bytes(payload)
    digest = hashlib.sha256(serialized).hexdigest()
    filename = f"{kind}-{digest}.json"
    path = os.path.abspath(os.path.join(root, out, "handoff-objects", filename))
    _write_json_atomic(path, dict(payload))
    relative = os.path.relpath(path, root).replace(os.sep, "/")
    summary_fields = {
        "selection": (
            "query_fingerprint",
            "target_resolution",
            "fidelity",
            "coverage",
            "token_budget_fit",
            "metrics",
            "needs_broader_context",
            "needs_broader_context_reason",
        ),
        "context_snapshot": (
            "snapshot_id",
            "revision",
            "root_hash",
            "fidelity",
            "needs_broader_context",
        ),
        "execution_context": (
            "envelope_hash",
            "task",
            "repository",
            "fidelity",
            "abstention",
            "needs_broader_context",
            "token_budget",
        ),
        "context_pack": (
            "pack_hash",
            "fidelity",
            "serialization_budget",
            "needs_broader_context",
            "needs_broader_context_reason",
        ),
    }
    summary = {field: payload[field] for field in summary_fields.get(kind, ()) if field in payload}
    return {
        "schema": "simplicio.context-reference/v1",
        "kind": kind,
        "referent_schema": str(payload.get("schema") or ""),
        "canonical_sha256": digest,
        "serialized_bytes": len(serialized),
        "serialized_tokens": estimate_tokens(serialized.decode("utf-8")),
        "summary": summary,
        "expansion_handle": {
            "kind": "artifact",
            "path": relative,
            "canonical_sha256": digest,
        },
    }


def _update_handoff_budget_receipt(
    payload: dict,
    *,
    output_format: str,
    token_budget: int,
    inline_tokens: int,
    referenced_fields: list[str],
    status: str,
) -> tuple[int, int]:
    previous: dict | None = None
    for _ in range(12):
        serialized, token_count = _handoff_serialization(payload, output_format)
        within_budget = token_count <= token_budget
        effective_status = status if within_budget else "required_context_exceeds_budget"
        receipt = {
            "scope": "handoff_envelope",
            "format": output_format,
            "token_budget": token_budget,
            "tokenizer_policy": TOKENIZER_POLICY,
            "measurement": "MEASURED",
            "inline_serialized_tokens": inline_tokens,
            "serialized_bytes": len(serialized),
            "serialized_tokens": token_count,
            "within_budget": within_budget,
            "compacted": bool(referenced_fields),
            "referenced_fields": list(referenced_fields),
            "status": effective_status,
            "budget_exceeded": not within_budget or status == "budget_exceeded",
            "required_minimum_token_budget": token_count if not within_budget else 0,
        }
        payload["serialization_budget"] = receipt
        if receipt == previous:
            return len(serialized), token_count
        previous = receipt
    serialized, token_count = _handoff_serialization(payload, output_format)
    return len(serialized), token_count


def _append_reason(payload: dict, reason: str) -> None:
    reasons = [piece.strip() for piece in str(payload.get("reason") or "").split(";") if piece.strip()]
    if reason not in reasons:
        reasons.append(reason)
    payload["reason"] = "; ".join(reasons)


def _fit_handoff_serialization(
    payload: dict,
    *,
    root: str,
    out: str,
    token_budget: int,
    output_format: str,
) -> dict:
    referenced_fields: list[str] = []
    _, inline_tokens = _update_handoff_budget_receipt(
        payload,
        output_format=output_format,
        token_budget=token_budget,
        inline_tokens=0,
        referenced_fields=referenced_fields,
        status="ready",
    )
    payload["serialization_budget"]["inline_serialized_tokens"] = inline_tokens
    _, token_count = _update_handoff_budget_receipt(
        payload,
        output_format=output_format,
        token_budget=token_budget,
        inline_tokens=inline_tokens,
        referenced_fields=referenced_fields,
        status="ready",
    )
    if token_count <= token_budget:
        return payload

    for field in ("selection", "context_snapshot", "execution_context", "traceability", "task_batch"):
        value = payload.get(field)
        if not isinstance(value, Mapping):
            continue
        payload[field] = _handoff_reference(root, out, field, value)
        referenced_fields.append(field)
        _, token_count = _update_handoff_budget_receipt(
            payload,
            output_format=output_format,
            token_budget=token_budget,
            inline_tokens=inline_tokens,
            referenced_fields=referenced_fields,
            status="compacted",
        )
        if token_count <= token_budget:
            return payload

    context_pack = payload.get("context_pack")
    if isinstance(context_pack, dict):
        placeholder = payload["context_pack"]
        payload["context_pack"] = {}
        _, envelope_overhead = _handoff_serialization(payload, output_format)
        payload["context_pack"] = placeholder
        allocated_budget = max(1, token_budget - envelope_overhead)
        pack_receipt = context_pack.get("serialization_budget", {})
        context_pack = enforce_serialized_budget(
            context_pack,
            token_budget=allocated_budget,
            estimated_tokens=int(pack_receipt.get("estimated_tokens", 0)),
        )
        payload["context_pack"] = context_pack
        _, token_count = _update_handoff_budget_receipt(
            payload,
            output_format=output_format,
            token_budget=token_budget,
            inline_tokens=inline_tokens,
            referenced_fields=referenced_fields,
            status="compacted",
        )
        if token_count <= token_budget and not context_pack["serialization_budget"]["budget_exceeded"]:
            return payload

        payload["context_pack"] = _handoff_reference(root, out, "context_pack", context_pack)
        referenced_fields.append("context_pack")
        payload["ready"] = False
        _append_reason(payload, "budget_exceeded")
        if isinstance(payload.get("gate_precedence"), dict):
            payload["gate_precedence"]["outcome"] = "blocked"
            payload["gate_precedence"]["gates"]["context_pack"]["gate"] = "budget_exceeded"
        _, token_count = _update_handoff_budget_receipt(
            payload,
            output_format=output_format,
            token_budget=token_budget,
            inline_tokens=inline_tokens,
            referenced_fields=referenced_fields,
            status="budget_exceeded",
        )
        if token_count <= token_budget:
            return payload

    payload["ready"] = False
    _append_reason(payload, "required_context_exceeds_budget")
    if isinstance(payload.get("gate_precedence"), dict):
        payload["gate_precedence"]["outcome"] = "blocked"
    _update_handoff_budget_receipt(
        payload,
        output_format=output_format,
        token_budget=token_budget,
        inline_tokens=inline_tokens,
        referenced_fields=referenced_fields,
        status="required_context_exceeds_budget",
    )
    return payload


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


def _handoff_context_cache_key(
    root: str,
    context_pack: Mapping[str, object],
    *,
    goal: str,
    task_intent: Mapping[str, object] | None,
    task_fingerprint: str,
    target: str,
    token_budget: int,
    task_batch: Mapping[str, object] | None,
) -> ContextCacheKey:
    """Build the local Mapper identity for one rendered handoff pack.

    The pack hash covers the selected artifacts and source content. Query and
    task inputs are included separately so two consumers of the same source
    tree cannot accidentally share context with different intent or budget.
    """
    files = [
        str(entry.get("path"))
        for entry in context_pack.get("files", [])
        if isinstance(entry, Mapping) and str(entry.get("path") or "").strip()
    ]
    source_snapshot = context_pack.get("source_snapshot")
    repository_id = ""
    if isinstance(source_snapshot, Mapping):
        repository_id = str(source_snapshot.get("snapshot_id") or "")
    if not repository_id:
        repository_id = (
            str(context_pack.get("repo", {}).get("root_hash") or "")
            if isinstance(context_pack.get("repo"), Mapping)
            else ""
        )
    query_identity = {
        "goal": goal,
        "task_intent": dict(task_intent or {}),
        "task_fingerprint": task_fingerprint,
        "target": target,
        "task_batch": dict(task_batch or {}),
        "pack_hash": str(context_pack.get("pack_hash") or ""),
    }
    return ContextCacheKey.for_files(
        root,
        sorted(set(files)),
        repo_identity=repository_id or os.path.basename(root.rstrip(os.sep)) or ".",
        mapper_schema_version=str(context_pack.get("schema") or CONTEXT_PACK_SCHEMA),
        parser_version="handoff-v1",
        query_task_hash=json.dumps(query_identity, ensure_ascii=False, sort_keys=True),
        retrieval_policy_version="mapper-handoff-context-v1",
        token_budget=token_budget,
        renderer="context-pack",
        output_format=CONTEXT_PACK_SCHEMA,
    )


#: What the worktree overlay (#1574) serves, and what it leaves to an on-demand query (#1673).
OVERLAY_SERVED_ARTIFACTS = ("project_map", "symbol_index", "precedent_index")
OVERLAY_UNSERVED_ARTIFACTS = ("call_graph", "architecture_inventory", "retrieval_index")
OVERLAY_ON_DEMAND_VERBS = ("callers", "callees", "reaches", "impact")


def _overlay_state(root: str, out: str) -> dict | None:
    """The worktree's ``overlay.json`` when it and the three artifacts it serves are on disk."""
    abs_out = os.path.abspath(os.path.join(root, out))
    if not os.path.exists(os.path.join(abs_out, "overlay.json")):
        return None
    from ..mapper.central_overlay import OVERLAY_ARTIFACT_FILES, OVERLAY_STATE_FILE, OVERLAY_STATE_SCHEMA

    state = _read_json_safe(os.path.join(abs_out, OVERLAY_STATE_FILE))
    if state.get("schema") != OVERLAY_STATE_SCHEMA:
        return None
    if not all(os.path.exists(os.path.join(abs_out, name)) for name in OVERLAY_ARTIFACT_FILES.values()):
        return None
    return state


def _overlay_base_present(root: str, state: Mapping[str, object]) -> bool:
    """True when the central base that ``overlay.json`` names is still in the cache."""
    digest = state.get("base_digest")
    if not isinstance(digest, str) or not digest or digest != os.path.basename(digest) or digest == "..":
        return False
    try:
        from ..mapper.canonical_identity import resolve_common_git_dir
        from ..mapper.canonical_storage import canonical_manifest_dir, resolve_canonical_cache_root

        common_git_dir = resolve_common_git_dir(root)
        if not common_git_dir:
            return False
        return os.path.isdir(canonical_manifest_dir(resolve_canonical_cache_root(common_git_dir), digest))
    except Exception:  # noqa: BLE001 - an unreadable base is "not present", never a crash
        return False


def _overlay_serves(root: str, out: str) -> dict | None:
    """The overlay state when it is valid: well-formed, with its central base still in the cache."""
    state = _overlay_state(root, out)
    if state is None or not _overlay_base_present(root, state):
        return None
    return state


def _artifacts_available(root: str, out: str) -> bool:
    """A full set is on disk, or a valid overlay serves the artifacts it can serve."""
    return _artifacts_exist(_artifact_paths(root, out)) or _overlay_serves(root, out) is not None


def _artifact_service(root: str, out: str) -> dict:
    """Which artifacts the worktree has, and which it leaves to an on-demand query."""
    state = _overlay_state(root, out)
    if state is None:
        return {"mode": "full" if _artifacts_exist(_artifact_paths(root, out)) else "none"}
    return {
        "mode": "overlay",
        "base_digest": state.get("base_digest"),
        "base_present": _overlay_base_present(root, state),
        "served_by_overlay": list(OVERLAY_SERVED_ARTIFACTS),
        "not_served_by_overlay": list(OVERLAY_UNSERVED_ARTIFACTS),
        "on_demand": {
            "verbs": [f"ask {verb}" for verb in OVERLAY_ON_DEMAND_VERBS],
            "never_built_by": ["scan", "inspect", "handoff"],
            "cost": "an in-memory build of the full artifact set, declared in the answer (on_demand_cost)",
        },
    }


def _index_is_fresh(root: str, out: str) -> bool:
    """True when the on-disk artifacts match the current freshness signature.

    A valid overlay (#1673) counts as the artifacts: it serves project-map, symbol-index and
    precedent-index, and ``not_served_by_overlay`` is not a reason for ``fresh=false``.
    """
    state = _read_index_state(root, out)
    if state.get("schema") != INDEX_STATE_SCHEMA:
        return False
    if state.get("completeness", "complete") != "complete":
        return False
    if not _artifacts_available(root, out):
        return False
    return state.get("signature") == _freshness_signature(root, out)


def _refresh_overlay(root: str, out: str) -> dict | None:
    """Bring the worktree's overlay up to date over the central base; ``None`` when it cannot serve."""
    from ..mapper.central_overlay import apply_overlay

    outcome = apply_overlay(root, out=out)
    if outcome.artifacts is None:
        return None
    _record_overlay_freshness(root, out, outcome.receipt)
    return outcome.receipt


def _job_process_is_owner(deep: dict, lock_status: dict) -> bool:
    pid = deep.get("pid")
    if not isinstance(pid, int) or not _process_is_alive(pid):
        return False
    expected_start = deep.get("process_start")
    actual_start = _process_start_token(pid)
    owner_token = deep.get("owner_token")
    if (
        not isinstance(expected_start, str)
        or not expected_start
        or expected_start == "unknown"
        or not actual_start
        or expected_start != actual_start
        or not isinstance(owner_token, str)
        or not owner_token
    ):
        return False
    if lock_status.get("active"):
        owner = lock_status.get("owner") if isinstance(lock_status.get("owner"), dict) else {}
        owner_start = owner.get("process_start_identity", owner.get("process_start"))
        if (
            owner.get("pid") != pid
            or owner_start != expected_start
            or owner.get("map_job_owner_token") != owner_token
        ):
            return False
    return True


def _reconcile_nonterminal_job(root: str, out: str, job: dict) -> str:
    deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
    identity = {key: deep.get(key) for key in ("pid", "process_start", "owner_token")}
    complete = _index_is_fresh(root, out)
    existing_exit = deep.get("exit_code")
    exit_code = existing_exit if isinstance(existing_exit, int) else (0 if complete else -1)
    failure_reason = None if complete else str(deep.get("failure_reason") or "worker_died_before_terminal")
    finalized = _finalize_map_job(
        root,
        out,
        identity,
        exit_code=exit_code,
        phase="complete" if complete else "failed",
        failure_reason=failure_reason,
        wait_for_job=False,
    )
    if finalized:
        reconciled = _read_json_safe(_map_job_path(root, out))
        if reconciled.get("phase") in ("complete", "failed", "timeout"):
            return str(reconciled["phase"])
    return "complete" if complete else "failed"


def _deep_phase(root: str, out: str) -> str:
    """Derive one authoritative phase for status, inspect and handoff."""
    lock_status = _inspect_index_lock(root, out, recover=True)
    job = _read_json_safe(_map_job_path(root, out))
    if job.get("schema") == MAP_JOB_SCHEMA:
        deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
        job_phase = job.get("phase")
        if job_phase in ("complete", "failed", "timeout"):
            if lock_status.get("active") and not _job_process_is_owner(deep, lock_status):
                return "deep_running"
            return "failed" if job_phase == "timeout" else str(job_phase)
        if job_phase in ("macro_done", "deep_running"):
            if _job_process_is_owner(deep, lock_status):
                return "deep_running"
            return _reconcile_nonterminal_job(root, out, job)
        if not _artifacts_available(root, out):
            return "failed"
    if lock_status.get("active"):
        return "deep_running"
    if _index_is_fresh(root, out):
        return "complete"
    return "unknown"


def _worker_failure_reason(root: str, out: str) -> str | None:
    """Return the failure recorded by the same job classified by ``_deep_phase``."""
    job = _read_json_safe(_map_job_path(root, out))
    if job.get("schema") != MAP_JOB_SCHEMA:
        return None
    deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
    if job.get("phase") == "timeout":
        return str(deep.get("failure_reason") or "scan_timeout")
    if job.get("phase") == "failed":
        return str(deep.get("failure_reason") or "worker_died_before_terminal")
    if job.get("phase") in ("macro_done", "deep_running"):
        lock_status = _inspect_index_lock(root, out, recover=False)
        if not _job_process_is_owner(deep, lock_status):
            return str(deep.get("failure_reason") or "worker_died_before_terminal")
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
        "finished_at": deep.get("finished_at"),
        "owner_token": deep.get("owner_token"),
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
    evidence = {key: _path_evidence(path) for key, path in paths.items()}
    if _overlay_serves(root, out) is not None:
        abs_out = os.path.abspath(os.path.join(root, out))
        evidence["retrieval_index"] = _path_evidence(os.path.join(abs_out, "retrieval-index.json"))
        for key in OVERLAY_SERVED_ARTIFACTS:
            evidence[key]["state"] = "served_by_overlay"
        for key in OVERLAY_UNSERVED_ARTIFACTS:
            evidence[key]["state"] = "not_served_by_overlay"
    return evidence


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
    elif not fresh and artifacts_present:
        warnings.append("artifacts_not_fresh")
    return warnings


def _status_payload(root: str, out: str, *, phase: str | None = None) -> dict:
    lock_status = _inspect_index_lock(root, out, recover=True)
    current_phase = phase or _deep_phase(root, out)
    worker_failure = _worker_failure_reason(root, out)
    state = _read_index_state(root, out)
    counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
    artifacts_present = _artifacts_available(root, out)
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
        "artifact_service": _artifact_service(root, out),
        "state_path": _state_path(root, out).replace(os.sep, "/"),
        "updated_at": state.get("updated_at"),
        "lock_path": _lock_path(root, out).replace(os.sep, "/"),
        "map_job_path": _map_job_path(root, out).replace(os.sep, "/"),
        "project_map_path": _project_map_path(root, out).replace(os.sep, "/"),
        "counts": counts,
        "completeness": state.get("completeness", "unknown"),
        "progress": state.get("progress") if isinstance(state.get("progress"), dict) else {},
        "resume": state.get("resume") if isinstance(state.get("resume"), dict) else None,
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


def _task_aware(opts: dict) -> bool:
    return bool(
        str(opts.get("goal") or "").strip()
        or str(opts.get("target") or "").strip()
        or str(opts.get("task_file") or "").strip()
        or str(opts.get("task_json") or "").strip()
        or str(opts.get("task_batch_file") or "").strip()
        or str(opts.get("task_fingerprint") or "").strip()
    )


def _attach_fast_route(opts: dict, envelope: dict, *, artifacts_fresh: bool) -> dict:
    """Foreground corridor + background deep: the default fast route."""
    if artifacts_fresh and _task_aware(opts):
        envelope["route"] = "reuse_then_target"
    elif artifacts_fresh:
        envelope["route"] = "reuse"
    elif _task_aware(opts):
        envelope["route"] = "macro_then_target_then_background"
    else:
        envelope["route"] = "macro_then_background"
    if not _task_aware(opts):
        return envelope
    if artifacts_fresh:
        envelope["handoff"] = _build_handoff_payload(opts)
        return envelope
    target = str(opts.get("target") or "").strip()
    if not target:
        envelope["corridor"] = {
            "schema": "simplicio.mapper-scoped-context/v1",
            "ready": False,
            "reason_code": "TARGET_REQUIRED_FOR_COLD_CORRIDOR",
            "detail": "cold scan needs --target for a foreground corridor; deep continues in background",
        }
        return envelope
    from ..scoped_context import ScopedContextError, build_scoped_context

    try:
        envelope["corridor"] = build_scoped_context(
            opts["root"],
            target_hints=[target],
            task_fingerprint=str(opts.get("task_fingerprint") or ""),
            context_budget=int(opts.get("token_budget") or 8000),
            out=opts["out"],
            start_background=False,
        )
    except ScopedContextError as error:
        envelope["corridor"] = {
            "schema": "simplicio.mapper-scoped-context/v1",
            "ready": False,
            "reason_code": error.reason_code,
            "detail": str(error),
        }
    return envelope


def _build_handoff_payload(opts: dict) -> dict:
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
        selection_policy="deterministic",
        budget_tokens=token_budget if task_aware else 0,
        priority_paths=targets if task_aware else None,
    )
    # `handoff` is the only public verb a downstream consumer can rely on
    # (it never calls the internal `snapshot build`), so it must guarantee the
    # canonical, unscoped `.simplicio-loop/context-snapshot.json` actually
    # exists and is current — otherwise `handoff --json` reports `ready: true`
    # while the snapshot is missing. At the same time it must never overwrite
    # that canonical file with a task-aware/budget-pruned graph — on large
    # repos that starves symbol lookup (mapper_id_missing). So a task-aware
    # call always rebuilds a second, unbounded/task-agnostic snapshot for the
    # canonical path (byte-identical to what `snapshot build` would emit from
    # the same artifacts) and keeps its own bounded snapshot scoped to
    # `context-snapshot.task.json`; a non-task-aware call already built the
    # canonical shape above and reuses it directly.
    canonical_snapshot = (
        context_snapshot
        if not task_aware
        else build_context_snapshot(
            root,
            project_map=project_map,
            symbol_index=symbol_index,
            call_graph=call_graph,
            architecture_inventory=artifacts["architecture_inventory"],
            task_query="",
            selection_policy="deterministic",
            budget_tokens=0,
            priority_paths=None,
        )
    )
    canonical_dest = os.path.join(
        os.path.abspath(os.path.join(root, out)), "context-snapshot.json"
    )
    existing_canonical_id = None
    try:
        with open(canonical_dest, encoding="utf-8") as handle:
            existing_canonical_id = json.load(handle).get("snapshot_id")
    except (OSError, ValueError):
        existing_canonical_id = None
    # `snapshot_id` is content-addressed (excludes the `generated_at`
    # timestamp), so a matching id means the artifacts on disk have not
    # changed since the canonical file was last written — skip the rewrite
    # to keep it byte-stable rather than touching its timestamp on every
    # `handoff` call for no content change.
    if existing_canonical_id != canonical_snapshot.get("snapshot_id"):
        _write_json_atomic(canonical_dest, canonical_snapshot)
    if task_aware:
        snapshot_dest = os.path.join(
            os.path.abspath(os.path.join(root, out)), "context-snapshot.task.json"
        )
        os.makedirs(os.path.dirname(snapshot_dest), exist_ok=True)
        with open(snapshot_dest, "w", encoding="utf-8") as handle:
            json.dump(context_snapshot, handle, sort_keys=True, indent=2)
            handle.write("\n")
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
    pack_cache_key_hash = ""
    pack_cache_receipt: dict[str, object] = {}
    pack_cache_hit = False
    try:
        pack_cache_key = _handoff_context_cache_key(
            root,
            context_pack,
            goal=goal,
            task_intent=task_intent,
            task_fingerprint=task_fingerprint,
            target=requested_target,
            token_budget=token_budget,
            task_batch=task_batch,
        )
        pack_cache_key_hash = pack_cache_key.content_hash()
        cached_pack, lookup_receipt = cache.get_entry(
            LAYER_RENDERED_PACK,
            pack_cache_key,
            expected_generation=str(context_snapshot.get("snapshot_id") or ""),
            expected_digest=str(pack_hash or ""),
        )
        if cached_pack is not None:
            context_pack = dict(cached_pack)
            context_pack["source_snapshot"] = {
                "snapshot_id": context_snapshot["snapshot_id"],
                "revision": context_snapshot["revision"],
                "source_digest": canonical_sha256(context_snapshot),
                "root_hash": context_snapshot["root_hash"],
            }
            pack_hash = context_pack.get("pack_hash")
            pack_cache_hit = True
            pack_cache_receipt = lookup_receipt.to_dict()
        else:
            cache.put(
                LAYER_RENDERED_PACK,
                pack_cache_key,
                context_pack,
                bytes_avoided=len(serialized_json_bytes(context_pack)),
                generation=str(context_snapshot.get("snapshot_id") or ""),
                digest=str(pack_hash or ""),
            )
            receipts = cache.receipts()
            pack_cache_receipt = receipts[-1] if receipts else lookup_receipt.to_dict()
    except (OSError, TypeError, ValueError):
        # Context caching is best-effort. The handoff remains valid when the
        # local cache cannot be read or written, but must not claim a hit.
        pack_cache_key_hash = ""
        pack_cache_receipt = {}
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
    if selection is not None and selection.get("token_budget_fit", {}).get("budget_exceeded"):
        reasons.append("budget_exceeded")
    if context_pack.get("serialization_budget", {}).get("budget_exceeded"):
        reasons.append("budget_exceeded")
    payload = {
        "schema": MAP_HANDOFF_SCHEMA,
        "ready": not reasons,
        "reason": "; ".join(reasons),
        "targets": targets,
        "status": {
            "schema": status_payload.get("schema"),
            "phase": status_payload.get("phase"),
            "fresh": status_payload.get("fresh"),
            "artifacts_present": status_payload.get("artifacts_present"),
            "completeness": status_payload.get("completeness"),
            "counts": status_payload.get("counts") or {},
            "warnings": status_payload.get("warnings") or [],
            "cache": status_payload.get("cache") or {},
            "failure_reason": status_payload.get("failure_reason"),
            "job": status_payload.get("job") or {},
        },
        "context_pack": context_pack,
        "evidence": {
            "pack_hash": pack_hash,
            "target_count": len(targets),
        },
        "cache": {
            "pack_cached": pack_cache_hit,
            "pack_cache_key_hash": pack_cache_key_hash,
            "pack_cache_receipt": pack_cache_receipt,
            "pack_diagnostics": {
                "present": bool(pack_cache_key_hash),
                "layer": LAYER_RENDERED_PACK,
            },
        },
    }
    if selection is not None:
        payload["selection"] = selection
        payload["metrics"] = {
            **selection["metrics"],
            "selection_latency_ms": selection_latency_ms,
            "estimated_tokens": selection["token_budget_fit"]["estimated_tokens"],
            "tokens_estimation_method": selection["token_budget_fit"]["tokenizer_policy"],
            "token_scope": "selected_source_content",
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
            acceptance_criteria=list(query_plan.get("ac_ids", [])) if isinstance(query_plan, dict) else [],
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
        execution_context = payload["execution_context"]
        if execution_context.get("needs_broader_context"):
            reasons.append("needs_broader_context")
        if not execution_context.get("token_budget", {}).get("within_budget", True):
            reasons.append("budget_exceeded")

    reasons = list(dict.fromkeys(reasons))
    payload["ready"] = not reasons
    payload["reason"] = "; ".join(reasons)
    selection_gate = (
        "not_applicable"
        if selection is None
        else "budget_exceeded"
        if selection.get("token_budget_fit", {}).get("budget_exceeded")
        else "needs_broader_context"
        if selection.get("needs_broader_context")
        else "ready"
    )
    pack_gate = (
        "required_context_exceeds_budget"
        if context_pack.get("serialization_budget", {}).get("budget_exceeded")
        else "needs_broader_context"
        if context_pack.get("needs_broader_context")
        else "ready"
    )
    execution_value = payload.get("execution_context")
    execution_gate = (
        "not_requested"
        if not isinstance(execution_value, Mapping)
        else "budget_exceeded"
        if not execution_value.get("token_budget", {}).get("within_budget", True)
        else "needs_broader_context"
        if execution_value.get("needs_broader_context")
        else "ready"
    )
    payload["gate_precedence"] = {
        "schema": "simplicio.handoff-gate-matrix/v1",
        "version": 1,
        "mandatory_order": ["status", "selection", "context_pack", "execution_context"],
        "gates": {
            "status": {
                "mandatory": True,
                "gate": "ready"
                if status_payload["artifacts_present"] and status_payload["fresh"]
                else "artifacts_unavailable",
            },
            "selection": {"mandatory": selection is not None, "gate": selection_gate},
            "context_pack": {"mandatory": True, "gate": pack_gate},
            "execution_context": {
                "mandatory": bool(opts.get("execution_context")),
                "gate": execution_gate,
            },
            "context_snapshot": {
                "mandatory": False,
                "gate": str(context_snapshot.get("fidelity", {}).get("gate") or "unknown"),
            },
        },
        "outcome": "ready" if payload["ready"] else "blocked",
    }
    output_format = "toon" if opts.get("for_llm") == "toon" else "json"
    if opts.get("_default_for_llm"):
        output_format = _default_handoff_output_format(payload, token_budget)
    return _fit_handoff_serialization(
        payload,
        root=root,
        out=out,
        token_budget=token_budget,
        output_format=output_format,
    )


def _run_handoff(opts: dict) -> int:
    payload = _build_handoff_payload(opts)
    output_format = "toon" if opts.get("for_llm") == "toon" else "json"
    if opts.get("_default_for_llm"):
        output_format = _default_handoff_output_format(
            payload, int(opts.get("token_budget", DEFAULT_TOKEN_BUDGET) or DEFAULT_TOKEN_BUDGET)
        )
    if output_format == "toon":
        _print_toon(payload)
    elif opts["json"] or opts.get("_default_for_llm"):
        _print_json_utf8(payload)
    else:
        status_payload = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        print(
            f"handoff phase={status_payload.get('phase')} targets={len(payload.get('targets') or [])} "
            f"pack_cached={payload.get('cache', {}).get('pack_cached')}"
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
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # A worktree that already holds an overlay over the central base (#1574) stays on it: refresh the
    # overlay and answer fresh. The full index (call-graph, architecture-inventory, retrieval-index)
    # is never started here; `ask` builds those on demand (#1673).
    overlay_receipt = None
    fresh = _index_is_fresh(root, out)
    on_overlay = _overlay_state(root, out) is not None
    if not fresh and on_overlay:
        overlay_receipt = _refresh_overlay(root, out)
        fresh = overlay_receipt is not None
    if fresh:
        envelope = {
            "schema": MAP_JOB_SCHEMA,
            "phase": "complete",
            "sync": bool(opts["sync"]),
            "created_at": created_at,
            "macro": macro,
            "deep": {
                "skipped_reason": "served_by_overlay" if on_overlay else "already_fresh",
                "poll": "simplicio-mapper status " + root,
                "exit_code": 0,
                "failure_reason": None,
                "finished_at": created_at,
            },
        }
        if on_overlay:
            envelope["artifact_service"] = _artifact_service(root, out)
            if overlay_receipt is not None:
                envelope["overlay"] = {
                    key: overlay_receipt.get(key)
                    for key in ("status", "base_digest", "files_total", "files_reused", "files_remapped", "duration_s")
                }
        _write_map_job(root, out, envelope)
        envelope = _attach_fast_route(opts, envelope, artifacts_fresh=True)
        if opts["json"]:
            print(json.dumps(envelope, sort_keys=True))
        else:
            counts = macro["counts"]
            print(
                f"scan phase=complete route={envelope['route']} files={counts['files']} "
                f"modules={counts['modules']} stack={macro['product']['stack']} reused"
            )
        return 0

    ci = os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on")
    synchronous = ci or opts["sync"]
    previous_state = _read_index_state(root, out)
    resuming = previous_state.get("completeness") == "partial"
    spawn_opts = dict(opts)
    if resuming:
        spawn_opts["incremental"] = True
    started = time.monotonic()
    macro_counts = dict(macro.get("counts") or {})
    progress = {
        "phase": "deep_running",
        "files_discovered": int(macro_counts.get("files", 0) or 0),
        "files_processed": 0,
        "elapsed_seconds": 0.0,
        "eta_seconds": None,
        "eta_reason": "insufficient_samples",
    }
    partial = {
        "schema": "simplicio.partial-scan/v1",
        "root": root.replace(os.sep, "/"),
        "signature": _freshness_signature(root, out),
        "completeness": "partial",
        "macro": macro,
        "progress": progress,
        "resume": {
            "mode": "incremental",
            "continuation": f"simplicio-mapper scan {root} --sync --update --json",
            "reuses_unchanged_files": True,
        },
    }
    _write_json_atomic(_partial_scan_path(root, out), partial)

    deep: dict = {
        "state_path": _state_path(root, out).replace(os.sep, "/"),
        "lock_path": _lock_path(root, out).replace(os.sep, "/"),
        "poll": "simplicio-mapper status " + root,
        "resuming": resuming,
    }
    if synchronous:
        spawn_opts["timeout"] = max(0, int(opts["timeout"]) - 1)
        deep["timeout_seconds"] = max(0, int(opts["timeout"]))
        try:
            spawned, child = _spawn_index_process(spawn_opts)
        except OSError as error:
            # Spawn failed before any worker/lock existed (historical WinError 6
            # on invalid stdin inheritance). Emit a terminal receipt with
            # reason_code; do not leave a live owner lock (issue #231).
            deep["failure_reason"] = "worker_spawn_failed"
            deep["reason_code"] = "worker_spawn_failed"
            deep["error"] = str(error)
            deep["winerror"] = getattr(error, "winerror", None)
            deep["exit_code"] = None
            deep["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            phase = "failed"
            progress.update(
                {
                    "phase": phase,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            )
            partial["progress"] = progress
            partial["failure_reason"] = deep["failure_reason"]
            _write_json_atomic(_partial_scan_path(root, out), partial)
            envelope = {
                "schema": MAP_JOB_SCHEMA,
                "phase": phase,
                "sync": True,
                "created_at": created_at,
                "macro": macro,
                "deep": deep,
            }
            _write_map_job(root, out, envelope)
            if opts["json"]:
                print(json.dumps(envelope, sort_keys=True))
            else:
                print(f"scan phase={phase} spawn failed: {error}", file=sys.stderr)
            return 1
        deep.update({key: spawned[key] for key in ("pid", "process_start", "log")})
        initial_envelope = {
            "schema": MAP_JOB_SCHEMA,
            "phase": "deep_running",
            "sync": True,
            "created_at": created_at,
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
        deep["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if phase == "complete":
            deep["failure_reason"] = None

        if phase != "complete":
            deep["lock_status"] = _inspect_index_lock(root, out, recover=True)
            if phase == "failed" and deep.get("failure_reason") is None:
                deep["failure_reason"] = "worker_failed_before_terminal"
            progress.update(
                {
                    "phase": phase,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            )
            partial["progress"] = progress
            partial["failure_reason"] = deep.get("failure_reason")
            partial["worker"] = {
                "pid": deep.get("pid"),
                "process_start": deep.get("process_start"),
                "exit_code": deep.get("exit_code"),
            }
            _write_json_atomic(_partial_scan_path(root, out), partial)
            _write_index_state(
                root,
                out,
                partial["signature"],
                {"files": progress["files_discovered"], "processed": progress["files_processed"]},
                completeness="partial",
                progress=progress,
                resume=partial["resume"],
            )
        else:
            try:
                os.remove(_partial_scan_path(root, out))
            except FileNotFoundError:
                pass
        envelope = {
            "schema": MAP_JOB_SCHEMA,
            "phase": phase,
            "sync": True,
            "created_at": created_at,
            "macro": macro,
            "deep": deep,
        }
        _write_map_job(root, out, envelope)
    else:
        spawn_opts["_map_job_owner_token"] = secrets.token_hex(16)
        try:
            spawned = _spawn_background_index(spawn_opts)
        except OSError as error:
            deep["failure_reason"] = "worker_spawn_failed"
            deep["reason_code"] = "worker_spawn_failed"
            deep["error"] = str(error)
            deep["winerror"] = getattr(error, "winerror", None)
            deep["exit_code"] = None
            deep["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            phase = "failed"
            progress.update(
                {
                    "phase": phase,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            )
            partial["progress"] = progress
            partial["failure_reason"] = deep["failure_reason"]
            _write_json_atomic(_partial_scan_path(root, out), partial)
            envelope = {
                "schema": MAP_JOB_SCHEMA,
                "phase": phase,
                "sync": False,
                "created_at": created_at,
                "macro": macro,
                "deep": deep,
            }
            _write_map_job(root, out, envelope)
            if opts["json"]:
                print(json.dumps(envelope, sort_keys=True))
            else:
                print(f"scan phase={phase} spawn failed: {error}", file=sys.stderr)
            return 1
        deep.update({key: spawned[key] for key in ("pid", "process_start", "owner_token", "log")})
        phase = "macro_done"
        envelope = {
            "schema": MAP_JOB_SCHEMA,
            "phase": phase,
            "sync": False,
            "created_at": created_at,
            "macro": macro,
            "deep": deep,
        }
        _write_map_job(root, out, envelope)
        if opts["await"]:
            phase = _await_terminal(root, out, opts["timeout"])
            persisted = _read_json_safe(_map_job_path(root, out))
            persisted_deep = persisted.get("deep") if isinstance(persisted.get("deep"), dict) else {}
            same_job = all(
                persisted_deep.get(key) == deep[key] for key in ("pid", "process_start", "owner_token")
            )
            if (
                persisted.get("schema") == MAP_JOB_SCHEMA
                and same_job
                and persisted.get("phase") in ("complete", "failed", "timeout")
            ):
                envelope = persisted
                phase = str(persisted["phase"])
            else:
                envelope = {**envelope, "phase": phase}

    envelope = _attach_fast_route(opts, envelope, artifacts_fresh=envelope.get("phase") == "complete")
    if opts["json"]:
        print(json.dumps(envelope, sort_keys=True))
    else:
        counts = macro["counts"]
        suffix = f" pid={deep.get('pid')}" if "pid" in deep else ""
        print(
            f"scan phase={envelope['phase']} route={envelope.get('route')} "
            f"files={counts['files']} modules={counts['modules']} "
            f"stack={macro['product']['stack']}{suffix}"
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
