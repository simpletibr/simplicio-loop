"""Exact ``base + overlay`` mapping of one worktree over the central default-branch base (#1574).

Product rule: the repository has ONE mapped base -- the default branch, built once, shared by every
linked worktree (``canonical_builder``: content-addressed under ``<git-common-dir>/simplicio``,
single-flight across processes). A worktree never remaps the tree and never writes the base; it
keeps only its own delta, here:

* ``<out>/overlay.json``                     what differs from the base and which base it names;
* ``<out>/project-map.json``, ``symbol-index.json``, ``precedent-index.json``
                                              the three artifacts ``orient`` and Dev CLI read,
                                              identical (canonical digest) to a fresh full mapping.

How it stays exact. The inventory is the mapper's own (``parse._build_file_inventory``): the file set
comes from the same walk, roles/importance/Brown-Hilbert addresses from the same functions. The only
difference is the per-file parse (language, hash, imports, exports): for a file the worktree did not
change relative to the base those facts come from the base's ``file-manifest.jsonl`` instead of being
recomputed. A file counts as unchanged only when git reports no delta for it, git is not told to ignore it (assume-unchanged,
skip-worktree) AND its size still matches the base entry; everything else -- modified, added, renamed,
untracked, ignored-but-walked, HEAD behind or ahead of the base -- is parsed from disk. Symbols follow the same rule. The assembly
below mirrors ``emit._build_artifacts_sync``; ``tests/python/test_central_overlay.py`` compares the
result with ``build_artifacts`` on random repositories so any drift fails a test.

Not materialized per worktree: ``call-graph``, ``architecture-inventory``, ``retrieval-index`` and
the artifact manifest (the heavy derived artifacts, 50-70 % of a full index). A previous generation of
them in the worktree is removed because it would describe another tree; ``simplicio-mapper index``
builds them on demand. C#/Razor sources are parsed fresh and run through the call graph's semantic
pass (global), so such trees stay exact, just not cheap.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import orjson

from ..language_capabilities import build_capability_coverage
from ..models import ProjectFile
from .canonical import CanonicalMapManifest
from .canonical_artifacts import attach_canonical_metadata, canonical_digest
from .canonical_builder import build_canonical_manifest_with_diagnostics
from .canonical_identity import resolve_repo_identity_bundle
from .canonical_overlay import compute_worktree_overlay
from .canonical_reuse import compute_config_fingerprint
from .canonical_storage import resolve_canonical_cache_root
from .emit import _build_agent_tree, _write_json_stable
from .file_lock import acquire_lock_at, release_lock_at
from .graph import (
    SEMANTIC_LANGUAGES,
    _build_symbol_index,
    _collect_architecture_signals,
    resolve_csharp_razor_semantics,
    semantic_input_key,
    semantic_not_required,
)
from .parse import (
    ARTIFACT_SCHEMA,
    ARTIFACT_VERSION,
    LLM_DIRECTIVES,
    PRECEDENT_SCHEMA,
    _build_brown_hilbert_map,
    _build_file_inventory,
    _build_precedent_items,
    _collect_entities,
    _collect_text_files,
    _detect_changed_files,
    _git_status_map,
    _group_modules,
    _now_iso,
    _parse_json_safe,
    _read_safe,
)

#: How long an overlay waits for another run on the same worktree (an overlay or an index).
LOCK_WAIT_SECONDS = 300.0
_LOCK_POLL_SECONDS = 0.2

OVERLAY_STATE_SCHEMA = "simplicio.worktree-overlay-state/v1"
OVERLAY_RECEIPT_SCHEMA = "simplicio.worktree-overlay-receipt/v1"
OVERLAY_STATE_FILE = "overlay.json"

#: Artifact name -> file name written into the worktree's own state directory.
OVERLAY_ARTIFACT_FILES = {
    "project_map": "project-map.json",
    "symbol_index": "symbol-index.json",
    "precedent_index": "precedent-index.json",
}
#: Derived artifacts a previous full index may have left; a stale generation must not survive.
SUPERSEDED_FILES = (
    "call-graph.json",
    "architecture-inventory.json",
    "retrieval-index.json",
    "artifact-manifest.json",
)
_PREVIEW_FILES = 80  # emit builds the architecture corpus from the first 80 files' previews



@dataclass
class OverlayOutcome:
    """``artifacts`` is ``None`` on every fallback; ``receipt`` is always populated."""

    receipt: dict
    artifacts: dict[str, dict] | None
    state: dict | None = None


def _read_json(path: str) -> Any:
    try:
        with open(path, "rb") as handle:
            return orjson.loads(handle.read())
    except (OSError, orjson.JSONDecodeError):
        return None


def _base_file_facts(manifest: CanonicalMapManifest) -> dict[str, dict] | None:
    relative = manifest.artifact_paths.get("file_manifest")
    if not relative:
        return None
    facts: dict[str, dict] = {}
    try:
        with open(os.path.join(manifest.storage_root, relative), "rb") as handle:
            for line in handle:
                if line.strip():
                    entry = orjson.loads(line)
                    facts[entry["path"]] = entry
    except (OSError, orjson.JSONDecodeError, KeyError):
        return None
    return facts


def _base_symbols(manifest: CanonicalMapManifest) -> tuple[dict[str, list[dict]], dict] | None:
    """The base's symbols grouped by file and its ``semantic_resolution`` (empty when it recorded none)."""
    relative = manifest.artifact_paths.get("symbol_index")
    document = _read_json(os.path.join(manifest.storage_root, relative)) if relative else None
    if not isinstance(document, dict):
        return None
    grouped: dict[str, list[dict]] = {}
    for symbol in document.get("symbols") or []:
        grouped.setdefault(symbol["defined_in"], []).append(symbol)
    resolution = document.get("semantic_resolution")
    return grouped, resolution if isinstance(resolution, dict) else {}


def _semantic_mode(semantic_files: list[ProjectFile], base_resolution: dict) -> str:
    """How the C#/Razor semantic pass is satisfied: ``not_required``, ``reused_from_base`` or ``recomputed:<why>``.

    The pass is a function of the C#/Razor sources alone (``semantic_input_key``): when the key the base
    recorded equals the worktree's, the base's resolved symbols and resolution are exactly what a full
    mapping would produce, so nothing needs to run.
    """
    if not semantic_files:
        return "not_required"
    key = semantic_input_key(semantic_files)
    if key is None:
        return "recomputed:input_key_unprovable"
    recorded = base_resolution.get("input_key")
    if not recorded:
        return "recomputed:base_without_input_key"
    return "reused_from_base" if recorded == key else "recomputed:semantic_input_changed"


def _delta(overlay) -> dict[str, list[str]]:
    delta: dict[str, list[str]] = {"added": [], "modified": [], "removed": [], "renamed": []}
    for change in overlay.changed_files:
        delta[change.change_type].append(
            change.path if change.change_type != "renamed" else f"{change.previous_path} -> {change.path}"
        )
    return {key: sorted(value) for key, value in delta.items()}


def _touched_paths(overlay) -> set[str]:
    touched = set(overlay.tombstones)
    for change in overlay.changed_files:
        touched.add(change.path)
        if change.previous_path:
            touched.add(change.previous_path)
    return touched


def _hidden_from_git(abs_root: str) -> set[str] | None:
    """Tracked paths whose changes git is told not to look at (assume-unchanged, skip-worktree).

    ``git status`` and ``git diff`` never report an edit of these, so the delta cannot be trusted
    for them: they are re-parsed from disk. ``None`` when the index cannot be read.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-v", "-z"], cwd=abs_root, capture_output=True, text=True,
            timeout=30, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    hidden: set[str] = set()
    for record in result.stdout.split("\0"):
        # "<tag> <path>": a lowercase tag is assume-unchanged, "S" is skip-worktree.
        if len(record) > 2 and (record[0].islower() or record[0] == "S"):
            hidden.add(record[2:])
    return hidden


def _fallback(receipt: dict, reason: str, started: float) -> OverlayOutcome:
    receipt = dict(receipt)
    receipt["status"] = "fallback"
    receipt["fallback_reason"] = reason
    receipt["duration_s"] = round(time.monotonic() - started, 4)
    return OverlayOutcome(receipt=receipt, artifacts=None)


def compute_overlay(
    root: str,
    *,
    out: str = ".simplicio-loop",
    meta: dict | None = None,
) -> OverlayOutcome:
    """Compute ``base + overlay`` for ``root`` without writing anything into ``root``.

    Builds the central base first when it does not exist yet (once, across processes and
    worktrees). Never raises: every problem becomes a ``fallback`` receipt and the caller runs the
    full index instead.
    """
    started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema": OVERLAY_RECEIPT_SCHEMA, "status": "ok", "fallback_reason": None,
        "files_total": 0, "files_reused": 0, "files_remapped": 0,
    }
    try:
        return _compute(os.path.abspath(root), out, meta, receipt, started)
    except Exception as error:  # noqa: BLE001 - the overlay must fail closed, never serve partial data
        return _fallback(receipt, f"unexpected_error:{type(error).__name__}", started)


def _compute(
    abs_root: str, out: str, meta: dict | None, receipt: dict, started: float
) -> OverlayOutcome:
    meta = meta or {}
    identity = resolve_repo_identity_bundle(abs_root)
    if identity is None:
        return _fallback(receipt, "identity_unresolved", started)
    fingerprint = compute_config_fingerprint(meta, out)
    cache_root = resolve_canonical_cache_root(identity.common_git_dir)
    build = build_canonical_manifest_with_diagnostics(abs_root, cache_root, fingerprint)
    manifest = build.manifest
    if manifest is None:
        return _fallback(receipt, "canonical_build_failed", started)
    receipt.update(
        base_digest=manifest.key.digest(), base_commit=manifest.key.commit_sha,
        base_tree=manifest.key.tree_sha, base_build=build.reason_code,
    )
    overlay = compute_worktree_overlay(abs_root, manifest.key, fingerprint)
    if overlay is None:
        return _fallback(receipt, "overlay_computation_failed", started)
    if not overlay.is_compatible_with_base():
        return _fallback(receipt, "config_fingerprint_mismatch", started)
    base_facts = _base_file_facts(manifest)
    base_symbol_state = _base_symbols(manifest)
    if base_facts is None or base_symbol_state is None:
        return _fallback(receipt, "base_artifacts_unreadable", started)
    base_symbols, base_resolution = base_symbol_state

    touched = _touched_paths(overlay)
    hidden = _hidden_from_git(abs_root)
    if hidden is None:
        return _fallback(receipt, "git_index_unreadable", started)
    touched |= hidden
    preview_paths = {
        os.path.relpath(path, abs_root).replace(os.sep, "/")
        for path in _collect_text_files(abs_root)[:_PREVIEW_FILES]
    }
    reused: set[str] = set()

    def facts(rel: str, stat: os.stat_result) -> dict | None:
        entry = base_facts.get(rel)
        if entry is None or rel in touched or entry.get("size_bytes") != stat.st_size:
            return None
        reused.add(rel)
        preview = _read_safe(os.path.join(abs_root, rel))[:3000] if rel in preview_paths else ""
        return {
            "language": entry.get("language"), "file_hash": entry.get("file_hash"),
            "imports": list(entry.get("imports") or []), "exports": list(entry.get("exports") or []),
            "text_preview": preview,
        }

    pkg = _parse_json_safe(os.path.join(abs_root, "package.json"))
    degraded: dict[str, Any] = {
        "git_timeout": False, "git_status_unavailable": False,
        "skipped_large_files": [], "large_file_limit_bytes": 250000,
    }
    skipped: list[str] = []
    status_map = _git_status_map(abs_root, degraded=degraded)
    contents: dict[str, str] = {}
    files = _build_file_inventory(
        abs_root, pkg, status_map, None, contents=contents, skipped_large_files=skipped, facts=facts,
    )
    degraded["skipped_large_files"] = sorted(skipped)

    generated_at = _now_iso()
    # C#/Razor symbols get their identities from the semantic pass, which reads those files alone. When
    # their key equals the base's, the base's resolved symbols are reused (even for a touched-but-identical
    # file); otherwise those files are parsed fresh and only they go through the service.
    semantic_files = [file for file in files if file.language in SEMANTIC_LANGUAGES]
    semantic_paths = {file.path for file in semantic_files}
    semantic_mode = _semantic_mode(semantic_files, base_resolution)
    if semantic_mode == "reused_from_base":
        reused |= semantic_paths
    else:
        reused -= semantic_paths
    symbol_index = _symbol_index(abs_root, files, generated_at, base_symbols, reused, contents)
    if semantic_mode == "reused_from_base":
        resolution = dict(base_resolution)
    elif semantic_mode == "not_required":
        resolution = semantic_not_required()
    else:
        resolution, _by_site = resolve_csharp_razor_semantics(abs_root, files, symbol_index["symbols"], contents)
    symbol_index["semantic_resolution"] = resolution
    if resolution.get("status") in {"unavailable", "degraded"}:
        degraded["semantic_resolution"] = resolution
    project_map = _project_map(abs_root, meta, pkg, files, status_map, degraded, generated_at)
    project_map["capability_coverage"] = build_capability_coverage(files, semantic_resolution=resolution)
    project_map["agent_tree"] = _build_agent_tree(files, _build_brown_hilbert_map(files))
    precedent_index = {
        "schema": PRECEDENT_SCHEMA, "version": ARTIFACT_VERSION, "generated_at": generated_at,
        "source_project_map": ".simplicio-loop/project-map.json",
        "items": _build_precedent_items(abs_root, files, contents=contents),
    }
    contents.clear()
    artifacts = {
        "project_map": project_map, "symbol_index": symbol_index, "precedent_index": precedent_index,
    }
    attach_canonical_metadata(abs_root, artifacts, degraded=degraded)

    delta = _delta(overlay)
    receipt.update(
        files_total=len(files), files_reused=len(reused), files_remapped=len(files) - len(reused),
        semantic=semantic_mode,
        delta=delta, worktree_head=overlay.worktree_commit_sha, dirty=overlay.dirty,
        default_branch=manifest.key.default_branch, config_fingerprint=fingerprint,
        single_flight_waited=build.reason_code in ("reused_after_wait", "built_after_wait"),
        artifacts={name: canonical_digest(value) for name, value in artifacts.items()},
        not_materialized=[name.replace(".json", "") for name in SUPERSEDED_FILES],
    )
    receipt["duration_s"] = round(time.monotonic() - started, 4)
    state = {
        "schema": OVERLAY_STATE_SCHEMA, "base_digest": receipt["base_digest"],
        "base_commit": receipt["base_commit"], "base_tree": receipt["base_tree"],
        "default_branch": receipt["default_branch"], "worktree_head": receipt["worktree_head"],
        "config_fingerprint": fingerprint, "delta": delta, "generated_at": generated_at,
        "counts": {
            "files": receipt["files_total"], "reused": receipt["files_reused"],
            "remapped": receipt["files_remapped"],
        },
        "artifacts": receipt["artifacts"], "not_materialized": receipt["not_materialized"],
    }
    return OverlayOutcome(receipt=receipt, artifacts=artifacts, state=state)


def _symbol_index(
    abs_root: str,
    files: list[ProjectFile],
    generated_at: str,
    reusable: dict[str, list[dict]],
    reused: set[str],
    contents: dict[str, str],
) -> dict:
    """``graph._build_symbol_index`` with the definitions of unchanged files taken from the base."""
    changed = [file for file in files if file.path not in reused]
    fresh = _build_symbol_index(abs_root, changed, generated_at, contents=contents)
    fresh_by_file: dict[str, list[dict]] = {}
    for symbol in fresh["symbols"]:
        fresh_by_file.setdefault(symbol["defined_in"], []).append(symbol)
    symbols: list[dict] = []
    for file in files:
        symbols.extend(reusable.get(file.path, []) if file.path in reused else fresh_by_file.get(file.path, []))
    document = dict(fresh)
    document["symbols"] = symbols
    document["counts"] = {
        "symbols": len(symbols), "files": len({item["defined_in"] for item in symbols}),
    }
    return document


def _project_map(
    abs_root: str,
    meta: dict,
    pkg: dict,
    files: list[ProjectFile],
    status_map: dict,
    degraded: dict,
    generated_at: str,
) -> dict:
    """The project-map assembly of ``emit._build_artifacts_sync`` (kept in lockstep by the oracle test)."""
    corpus = "\n".join(file.text_preview for file in files[:_PREVIEW_FILES])
    changed_files = _detect_changed_files(files, {}, status_map, False)
    stack = meta.get("stack") or pkg.get("type") or "unknown"
    product_name = meta.get("product_name") or pkg.get("name") or os.path.basename(abs_root)
    signals = _collect_architecture_signals(pkg, corpus, stack)
    if os.path.exists(os.path.join(abs_root, "pnpm-lock.yaml")):
        package_manager = "pnpm"
    elif os.path.exists(os.path.join(abs_root, "yarn.lock")):
        package_manager = "yarn"
    else:
        package_manager = "npm"
    web_signal = "react" in signals or "nextjs" in signals
    if meta.get("project_mode") == "monorepo":
        system_type = "monorepo"
    else:
        system_type = "web" if web_signal else "library-or-service"
    return {
        "schema": ARTIFACT_SCHEMA, "version": ARTIFACT_VERSION, "generated_at": generated_at,
        "update_mode": "full",
        "product": {"name": product_name, "stack": stack, "project_mode": meta.get("project_mode", "root")},
        "files": [file.to_dict() for file in files],
        "entry_points": [f.path for f in files if "entrypoint" in f.roles],
        "test_files": [f.path for f in files if "test" in f.roles],
        "config_files": [f.path for f in files if "config" in f.roles],
        "modules": _group_modules(files),
        "entities": _collect_entities(files),
        "architecture": {"signals": signals, "system_type": system_type},
        "dependencies": {
            "package_manager": package_manager,
            "manifest": "package.json" if pkg.get("name") else None,
            "runtime": sorted((pkg.get("dependencies") or {}).keys()),
            "dev": sorted((pkg.get("devDependencies") or {}).keys()),
        },
        "recent_changes": [
            {"path": file, "status": status_map.get(file, "modified")} for file in changed_files
        ],
        "changed_files": changed_files,
        "integration": {
            "dev_cli_mapper": "read .simplicio-loop/project-map.json, then use .simplicio-loop/precedent-index.json for task-specific examples",
            "contract": "SIMPLICIO_INTEGRATION.md",
            "llm_directives": LLM_DIRECTIVES,
        },
        "degraded": degraded,
    }


def _lock_worktree(state_dir: str):
    """The per-worktree index lock: an overlay, an index and a second overlay never write together."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    path = os.path.join(state_dir, "index.lock")
    while True:
        lock = acquire_lock_at(path, operation="overlay")
        if lock is not None or time.monotonic() >= deadline:
            return lock
        time.sleep(_LOCK_POLL_SECONDS)


def apply_overlay(
    root: str,
    *,
    out: str = ".simplicio-loop",
    meta: dict | None = None,
) -> OverlayOutcome:
    """:func:`compute_overlay`, then persist the worktree's own state (never the base).

    Writes only inside ``<root>/<out>``; removes the heavy derived artifacts of an older
    generation. On a fallback nothing is written or removed. Runs under the worktree's index lock,
    so concurrent runs on one worktree (or an overlay racing an index) take turns.
    """
    abs_root = os.path.abspath(root)
    state_dir = os.path.join(abs_root, out)
    if resolve_repo_identity_bundle(abs_root) is None:
        return compute_overlay(root, out=out, meta=meta)  # nothing to lock, nothing to write
    lock = _lock_worktree(state_dir)
    if lock is None:
        return _fallback({"schema": OVERLAY_RECEIPT_SCHEMA, "status": "ok"}, "lock_wait_timeout", time.monotonic())
    try:
        outcome = compute_overlay(root, out=out, meta=meta)
        if outcome.artifacts is None or outcome.state is None:
            return outcome
        for name, file_name in OVERLAY_ARTIFACT_FILES.items():
            _write_json_stable(os.path.join(state_dir, file_name), outcome.artifacts[name])
        _write_json_stable(os.path.join(state_dir, OVERLAY_STATE_FILE), outcome.state)
        for stale in SUPERSEDED_FILES:
            try:
                os.remove(os.path.join(state_dir, stale))
            except OSError:
                pass
        return outcome
    finally:
        release_lock_at(lock)


__all__ = [
    "OVERLAY_ARTIFACT_FILES", "OVERLAY_RECEIPT_SCHEMA", "OVERLAY_STATE_FILE", "OVERLAY_STATE_SCHEMA",
    "OverlayOutcome", "SUPERSEDED_FILES", "apply_overlay", "compute_overlay",
]
