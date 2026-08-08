from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

from ..history import append_changelog, create_snapshot
from ..mapper import (
    _is_internal_worktree_dir,
    _is_managed_capability_dir,
    write_mapping_artifacts,
)
from ..mapper.canonical_reuse import (
    attempt_canonical_reuse,
    is_canonical_reuse_enabled,
)
from ..mapper.canonical_reuse import (
    write_receipt as _write_canonical_reuse_receipt,
)

# The lock schema/TTL constants and `_IndexLockHandle` are re-exported here
# under their original pre-extraction names purely for backward
# compatibility -- `_background.py`/`_status_engine.py`/
# `tests/python/test_lock_recovery.py` still import them from this module
# (see the comment further below, next to `_inspect_index_lock`). They are
# genuinely unused *within this file* now that the lock logic itself lives in
# `simplicio_mapper.mapper.file_lock`; listed in `__all__` below instead of an
# unused-import suppression comment on each, so `ruff --fix` never silently
# drops them again.
from ..mapper.file_lock import (
    DEFAULT_LOCK_TTL_SECONDS as DEFAULT_INDEX_LOCK_TTL_SECONDS,
)
from ..mapper.file_lock import (
    LEGACY_LOCK_SCHEMA as LEGACY_INDEX_LOCK_SCHEMA,
)
from ..mapper.file_lock import (
    LOCK_SCHEMA as INDEX_LOCK_SCHEMA,
)
from ..mapper.file_lock import (
    LOCK_TTL_ENV as INDEX_LOCK_TTL_ENV,
)
from ..mapper.file_lock import (
    MALFORMED_LOCK_GRACE_SECONDS,
)
from ..mapper.file_lock import (
    LockHandle as _IndexLockHandle,
)
from ..mapper.file_lock import (
    acquire_lock_at as _acquire_lock_at,
)
from ..mapper.file_lock import (
    inspect_lock_at as _inspect_lock_at,
)
from ..mapper.file_lock import (
    release_lock_at as _release_lock_at,
)

# Same re-export rationale as above: `_status_engine.py` imports
# `_process_is_alive`/`_process_start_token` from this module.
from ..mapper.process_liveness import process_is_alive as _process_is_alive
from ..mapper.process_liveness import process_start_token as _process_start_token
from ..retrieval_index import build_retrieval_index, write_retrieval_index
from ..savings import estimate_tokens
from ..toon import encode_toon_with_report
from ._args import _read_json_safe
from ._shared import (
    CONFIDENCE_RANK,
    CONFIDENCE_TAG_ORDER,
    FRESHNESS_SKIP_DIRS,
    INDEX_RESULT_SCHEMA,
    INDEX_STATE_SCHEMA,
)

# Names re-exported for backward compatibility only (genuinely unused within
# this file after the file_lock.py extraction) -- listed explicitly so
# `ruff`'s unused-import check (F401) never flags, and never silently
# removes, a name another module still imports from here.
__all__ = [
    "DEFAULT_INDEX_LOCK_TTL_SECONDS",
    "LEGACY_INDEX_LOCK_SCHEMA",
    "INDEX_LOCK_SCHEMA",
    "INDEX_LOCK_TTL_ENV",
    "MALFORMED_LOCK_GRACE_SECONDS",
    "_process_is_alive",
    "_process_start_token",
]


def _run_once(opts: dict) -> dict:
    root = os.path.abspath(opts["root"])
    meta = dict(_read_json_safe(os.path.join(root, ".starter-meta.json")))
    if opts["stack"]:
        meta["stack"] = opts["stack"]
    if opts["product_name"]:
        meta["product_name"] = opts["product_name"]
    log = (lambda _line: None) if opts["silent"] else print
    canonical_reuse_receipt: dict | None = None
    result: dict | None = None
    # Opt-in only (issue #269): default behavior below (write_mapping_artifacts)
    # is completely unchanged unless a caller explicitly enables reuse via
    # --canonical-reuse or SIMPLICIO_MAPPER_CANONICAL_REUSE=1.
    if is_canonical_reuse_enabled(opts):
        outcome = attempt_canonical_reuse(root, opts["out"], meta)
        canonical_reuse_receipt = outcome.receipt
        result = outcome.run_result
        if result is not None:
            log(
                "-> canonical-reuse hit: reused "
                f"{canonical_reuse_receipt.get('files_reused', 0)} file(s), "
                f"remapped {canonical_reuse_receipt.get('files_remapped', 0)}"
            )
        else:
            log(
                "-> canonical-reuse fallback: "
                f"{canonical_reuse_receipt.get('fallback_reason')} (running full map)"
            )
        _write_canonical_reuse_receipt(root, opts["out"], canonical_reuse_receipt)
    if result is None:
        result = write_mapping_artifacts(
            cwd=root,
            meta=meta,
            incremental=opts["incremental"],
            output_dir=opts["out"],
            log=log,
        )
    if canonical_reuse_receipt is not None:
        result = {**result, "canonical_reuse": canonical_reuse_receipt}
    # Build the retrieval index during the normal scan/index pass so warm
    # task-aware queries never scan candidate bodies. Keep it as a first-class
    # artifact with the same source hashes used by incremental updates.
    artifact_root = os.path.join(root, opts["out"])
    project_map = _read_json_safe(os.path.join(artifact_root, "project-map.json"))
    symbol_index = _read_json_safe(os.path.join(artifact_root, "symbol-index.json"))
    call_graph = _read_json_safe(os.path.join(artifact_root, "call-graph.json"))
    retrieval_index = build_retrieval_index(
        project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        root=root,
    )
    write_retrieval_index(root, opts["out"], retrieval_index)
    # History snapshots (.simplicio/history/*.json) are always cheap JSON and
    # never create a docs/ directory on their own. The changelog markdown is
    # only appended when docs are actually being rendered for this run, so
    # --json-only/--no-docs flows stay JSON-only as documented.
    snapshot = create_snapshot(
        root, out_dir=opts["out"], trigger=opts["command"], retention=opts["retention"], artifacts=result
    )
    if snapshot is not None and opts.get("docs"):
        append_changelog(root, opts["out"], snapshot)
    return result


def _signature(root: str, out: str) -> tuple:
    abs_out = os.path.abspath(os.path.join(root, out))
    entries = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in FRESHNESS_SKIP_DIRS
            and os.path.abspath(os.path.join(current, d)) != abs_out
            and not _is_internal_worktree_dir(current, d)
            and not _is_managed_capability_dir(current, d)
        ]
        for name in files:
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((path, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


def _state_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "index-state.json")


def _lock_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "index.lock")


# The lock's schema/TTL constants, ``_IndexLockHandle``, and its
# acquire/inspect/release logic used to be defined inline here. They now live
# in ``simplicio_mapper.mapper.file_lock`` (issue #236, ADR-008 section 4) so
# ``canonical_builder.py`` can reuse the exact same PID-reuse-safe,
# TTL-aware, dead-owner-reclaiming lock for the cross-worktree
# ``canonical-build`` operation instead of a second lock implementation --
# see that module's docstring. Every name below is re-exported unchanged so
# every existing call site in this repo (``_background.py``,
# ``_status_engine.py``, ``tests/python/test_lock_recovery.py``, etc.) keeps
# working without modification; only ``_inspect_index_lock``/
# ``_acquire_index_lock`` below became thin ``operation="index"`` wrappers
# around the generalized ``inspect_lock_at``/``acquire_lock_at``.


def _root_fingerprint(root: str) -> str:
    return hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:24]


def _inspect_index_lock(root: str, out: str, *, recover: bool = False) -> dict:
    """Classify the per-worktree index lock and optionally reclaim an orphan.

    Thin ``operation="index"`` wrapper around
    :func:`simplicio_mapper.mapper.file_lock.inspect_lock_at` -- no behavior
    change versus the pre-extraction inline implementation.
    """
    return _inspect_lock_at(_lock_path(root, out), recover=recover)


def _acquire_index_lock(root: str, out: str) -> _IndexLockHandle | None:
    """Acquire the per-worktree index lock (``operation="index"``).

    Thin wrapper around
    :func:`simplicio_mapper.mapper.file_lock.acquire_lock_at` -- no behavior
    change versus the pre-extraction inline implementation.
    """
    return _acquire_lock_at(
        _lock_path(root, out),
        operation="index",
        extra_fields={"root_fingerprint": _root_fingerprint(root)},
    )


def _release_index_lock(lock: _IndexLockHandle | None) -> None:
    _release_lock_at(lock)


def _artifact_paths(root: str, out: str) -> dict[str, str]:
    abs_out = os.path.abspath(os.path.join(root, out))
    return {
        "project_map": os.path.join(abs_out, "project-map.json"),
        "precedent_index": os.path.join(abs_out, "precedent-index.json"),
        "architecture_inventory": os.path.join(abs_out, "architecture-inventory.json"),
        "symbol_index": os.path.join(abs_out, "symbol-index.json"),
        "call_graph": os.path.join(abs_out, "call-graph.json"),
    }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_signature(root: str, out: str) -> dict | None:
    ignored_out = os.path.relpath(os.path.abspath(os.path.join(root, out)), root)
    ignored_out = ignored_out.replace(os.sep, "/").rstrip("/") or ".simplicio"
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            stdin=subprocess.DEVNULL,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            stdin=subprocess.DEVNULL,
        )
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                ".",
                f":!{ignored_out}",
                ":(exclude).skills/_generated/**",
                ":(exclude).agents/_generated/**",
                ":(exclude).catalog/**",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if head.returncode != 0 or status.returncode != 0:
        return None
    tree = _tree_signature(root, out)
    return {
        "kind": "git",
        "head": head.stdout.strip(),
        "status_hash": _hash_text(status.stdout),
        "tree_hash": tree.get("hash"),
    }


def _tree_signature(root: str, out: str) -> dict:
    digest = hashlib.sha256()
    abs_out = os.path.abspath(os.path.join(root, out))
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in FRESHNESS_SKIP_DIRS
            and os.path.abspath(os.path.join(current, d)) != abs_out
            and not _is_internal_worktree_dir(current, d)
            and not _is_managed_capability_dir(current, d)
        ]
        for name in sorted(files):
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return {"kind": "tree", "hash": digest.hexdigest()}


def _freshness_signature(root: str, out: str) -> dict:
    return _git_signature(root, out) or _tree_signature(root, out)


def _read_index_state(root: str, out: str) -> dict:
    return _read_json_safe(_state_path(root, out))


def _write_index_state(
    root: str,
    out: str,
    signature: dict,
    counts: dict | None = None,
    *,
    completeness: str = "complete",
    progress: dict | None = None,
    resume: dict | None = None,
) -> None:
    path = _state_path(root, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "schema": INDEX_STATE_SCHEMA,
        "signature": signature,
        "counts": counts or {},
        "completeness": completeness,
        "progress": progress or {},
        "resume": resume,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _artifacts_exist(paths: dict[str, str]) -> bool:
    return all(os.path.exists(path) for path in paths.values())


def _index_result(
    root: str,
    out: str,
    *,
    status: str,
    skipped_reason: str | None = None,
    run_result: dict | None = None,
    counts: dict | None = None,
    error: str | None = None,
) -> dict:
    paths = _artifact_paths(root, out)
    project_map = run_result.get("project_map", {}) if run_result else {}
    precedent_index = run_result.get("precedent_index", {}) if run_result else {}
    architecture_inventory = run_result.get("architecture_inventory", {}) if run_result else {}
    symbol_index = run_result.get("symbol_index", {}) if run_result else {}
    call_graph = run_result.get("call_graph", {}) if run_result else {}
    changed_files = list(project_map.get("changed_files") or [])
    counts = counts or {
        "files": len(project_map.get("files", []) or []),
        "precedents": len(precedent_index.get("items", []) or []),
        "changed_files": len(changed_files),
        "modules": len(architecture_inventory.get("modules", []) or []),
        "layers": len(architecture_inventory.get("layers", []) or []),
        "symbols": len(symbol_index.get("symbols", []) or []),
        "relationships": len(call_graph.get("edges", []) or []),
    }
    payload = {
        "schema": INDEX_RESULT_SCHEMA,
        "status": status,
        "skipped_reason": skipped_reason,
        "paths": {key: path.replace(os.sep, "/") for key, path in paths.items()},
        "counts": counts,
        "changed_files": changed_files,
        "error": error,
    }
    # Only ever present when the caller opted in to canonical reuse (issue
    # #269) -- default `index`/`scan` output is unaffected, byte-for-byte.
    if run_result is not None and "canonical_reuse" in run_result:
        payload["canonical_reuse"] = run_result["canonical_reuse"]
    if run_result is not None and isinstance(run_result.get("execution_plan"), dict):
        payload["execution_plan"] = run_result["execution_plan"]
        execution_plan_path = run_result.get("execution_plan_path")
        if isinstance(execution_plan_path, str):
            payload["paths"]["execution_plan"] = execution_plan_path.replace(os.sep, "/")
    return payload


_INDEX_COUNT_TAGS = {
    "files": "MEASURED",
    "precedents": "MEASURED",
    "changed_files": "MEASURED",
    "symbols": "MEASURED",
    "relationships": "MEASURED",
    "docs": "MEASURED",
    "modules": "CANON",
    "layers": "CANON",
}

_CONFIDENCE_TAG_LEGEND = {
    "MEASURED": "Read directly off the code on disk this run (AST/regex over real source files).",
    "OPERATOR": "Human/operator supplied the exact number out-of-band; not emitted by this CLI on its own.",
    "CANON": "Derived from doc/README/architecture-convention claims, not a direct code read.",
    "UNVERIFIED": "Not cross-checked against a live run of the mapped system.",
}


def _apply_tagging(payload: dict) -> dict:
    """Attach Asolaria confidence tags to ``payload["counts"]`` (``--tagged``).

    See ``_INDEX_COUNT_TAGS``/``_CONFIDENCE_TAG_LEGEND`` above for the
    MEASURED/OPERATOR/CANON/UNVERIFIED discipline this mirrors from
    Algorithms of Asolaria (issue #150, P0).
    """
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        return payload
    payload = dict(payload)
    payload["confidence_tags"] = {key: _INDEX_COUNT_TAGS.get(key, "UNVERIFIED") for key in counts}
    payload["confidence_tag_legend"] = dict(_CONFIDENCE_TAG_LEGEND)
    return payload


def _apply_confidence_filter(payload: dict, min_tag: str) -> dict:
    """Keep only ``counts`` entries at least as strong as ``min_tag`` (``--confidence``).

    Never silently drops a weaker entry — "no deflate-gate": every filtered
    key is still recorded, with its tag, under ``confidence_filtered_out``.
    """
    tags = payload.get("confidence_tags")
    if not isinstance(tags, dict):
        return payload
    threshold = CONFIDENCE_RANK[min_tag]
    counts = payload.get("counts") or {}
    kept = {}
    dropped = []
    for key, value in counts.items():
        tag = tags.get(key, "UNVERIFIED")
        if CONFIDENCE_RANK.get(tag, len(CONFIDENCE_TAG_ORDER)) <= threshold:
            kept[key] = value
        else:
            dropped.append({"key": key, "tag": tag})
    payload = dict(payload)
    payload["counts"] = kept
    payload["confidence_threshold"] = min_tag
    payload["confidence_filtered_out"] = dropped
    return payload


_FNV_OFFSET_BASIS_64 = 0xCBF29CE484222325

_FNV_PRIME_64 = 0x100000001B3

_FNV_MASK_64 = 0xFFFFFFFFFFFFFFFF


def _fnv1a64_hex(text: str) -> str:
    """FNV-1a, 64-bit variant, as a 16-hex-char string (non-cryptographic hash)."""
    digest = _FNV_OFFSET_BASIS_64
    for byte in text.encode("utf-8"):
        digest ^= byte
        digest = (digest * _FNV_PRIME_64) & _FNV_MASK_64
    return f"{digest:016x}"


def _sha16_hex(text: str) -> str:
    """sha256 truncated to 16 hex chars (8 bytes) — same convention already
    used for this repo's own precedent-index item ids."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _citizen_identity(root: str, key: str) -> str:
    """Stable identity for ``key`` within the federation of mapped repos."""
    repo_name = os.path.basename(os.path.abspath(root or os.getcwd())) or "repo"
    return f"{repo_name}::{key}"


def _apply_geometry(payload: dict, root: str) -> dict:
    """Attach REALMATHPOS/FNV-1a64/sha16/citizenIdentity addressing (``--geometry``).

    Applied per entry in ``payload["paths"]`` (each mapper artifact file).
    ``realmathpos`` degenerates to the artifact file's root position
    (line 1, col 1) rather than a specific symbol position — this CLI's
    `index`/`ask` commands do carry true file:line:col positions for
    individual symbols/routes elsewhere (see the `ask`/`endpoints`
    payloads), which is out of scope for this top-level artifact-address
    pass; see #150 P1 for a per-symbol geometry follow-up.
    """
    paths = payload.get("paths")
    if not isinstance(paths, dict):
        return payload
    geometry = {}
    for key, path in paths.items():
        geometry[key] = {
            "realmathpos": {"file": path, "line": 1, "col": 1},
            "fnv1a64": _fnv1a64_hex(path),
            "sha16": _sha16_hex(path),
            "citizen_identity": _citizen_identity(root, key),
        }
    payload = dict(payload)
    payload["addressing_geometry"] = geometry
    return payload


def _reconcile_toon_token_estimate(payload: dict, fallbacks: list[dict]) -> dict:
    """Make ``payload["metrics"]["estimated_tokens"]`` honest when some
    container fell back to embedded JSON instead of the compact TOON shape.

    ``estimated_tokens`` (see ``retrieval_index.fit_token_budget`` /
    ``cli/_status_engine.py``) is computed *before* ``--for-llm toon``
    serialization happens, on the assumption that every array takes the
    token-lean tabular/inline path. When ``encode_toon_with_report`` reports
    one or more ``toon_fallbacks`` (issue #308), that assumption is false for
    this payload — the real emitted text is bigger than the pre-serialization
    estimate accounted for. Recompute the figure from the actual serialized
    text (TOON + any embedded-JSON fallbacks, exactly as printed) so the
    reported estimate never understates what is really on the wire.
    """
    if not fallbacks:
        return payload
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or "estimated_tokens" not in metrics:
        return payload
    if metrics.get("token_scope") and metrics.get("token_scope") != "serialized_output":
        return payload
    text, _fallbacks = encode_toon_with_report(payload)
    real_tokens = estimate_tokens(text)
    if real_tokens <= metrics["estimated_tokens"]:
        return payload
    payload = dict(payload)
    metrics = dict(metrics)
    metrics["estimated_tokens"] = real_tokens
    previous_method = str(metrics.get("tokens_estimation_method", ""))
    metrics["tokens_estimation_method"] = (
        f"{previous_method}+toon_fallback_actual" if previous_method else "toon_fallback_actual"
    )
    payload["metrics"] = metrics
    return payload


def _print_toon(payload: dict) -> None:
    """Print ``payload`` as TOON on stdout; log any fallbacks to stderr.

    A silent fallback means an operator has no way to tell how much of the
    payload actually took the token-lean tabular/inline path versus the
    embedded-JSON fallback — issue #148's "log do motivo" requirement.
    ``toon_fallbacks`` mirrors the machine-readable shape used elsewhere in
    the ecosystem (see TOON-CONTRACT.md).

    When fallbacks occur and the payload carries a ``metrics.estimated_tokens``
    figure, that figure is reconciled against the real serialized size before
    printing (issue #308) — otherwise the reported estimate silently assumes
    full TOON compression even though part of the payload fell back to JSON.
    """
    text, fallbacks = encode_toon_with_report(payload)
    if fallbacks:
        reconciled = _reconcile_toon_token_estimate(payload, fallbacks)
        if reconciled is not payload:
            text, fallbacks = encode_toon_with_report(reconciled)
    print(text)
    if fallbacks:
        print(json.dumps({"toon_fallbacks": fallbacks}, sort_keys=True), file=sys.stderr)


def _emit_index_json(opts: dict, payload: dict) -> None:
    if opts.get("tagged"):
        payload = _apply_tagging(payload)
        if opts.get("confidence"):
            payload = _apply_confidence_filter(payload, opts["confidence"])
    if opts.get("geometry"):
        payload = _apply_geometry(payload, opts.get("root"))
    if opts.get("for_llm") == "toon":
        _print_toon(payload)
    elif opts["json"]:
        print(json.dumps(payload, sort_keys=True))
