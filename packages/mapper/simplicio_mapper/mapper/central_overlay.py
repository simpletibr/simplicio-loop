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
recomputed. A file counts as unchanged only when git reports no delta for it AND its size still
matches the base entry; everything else -- modified, added, renamed, untracked, ignored-but-walked,
HEAD behind or ahead of the base -- is parsed from disk. Symbols follow the same rule. The assembly
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
from .graph import _build_call_graph, _build_symbol_index, _collect_architecture_signals
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
_SEMANTIC_LANGUAGES = frozenset({"csharp", "razor"})
_PREVIEW_FILES = 80  # emit builds the architecture corpus from the first 80 files' previews

_SEMANTIC_NOT_REQUIRED = {
    "schema": "simplicio.mapper-semantic-resolution/v1",
    "protocol": "v1",
    "status": "not_required",
    "languages": [],
    "providers": [],
    "provider_versions": [],
    "resolved_calls": 0,
    "symbols": 0,
    "reasons": ["no_csharp_or_razor_call_sites"],
}


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


def _base_symbols(manifest: CanonicalMapManifest) -> dict[str, list[dict]] | None:
    relative = manifest.artifact_paths.get("symbol_index")
    document = _read_json(os.path.join(manifest.storage_root, relative)) if relative else None
    if not isinstance(document, dict):
        return None
    grouped: dict[str, list[dict]] = {}
    for symbol in document.get("symbols") or []:
        grouped.setdefault(symbol["defined_in"], []).append(symbol)
    return grouped


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
    base_symbols = _base_symbols(manifest)
    if base_facts is None or base_symbols is None:
        return _fallback(receipt, "base_artifacts_unreadable", started)

    touched = _touched_paths(overlay)
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
    # C#/Razor symbols get their identities from the semantic pass of the call graph, which is
    # global: those files are parsed fresh and the call graph decides the resolution status.
    semantic = any(file.language in _SEMANTIC_LANGUAGES for file in files)
    if semantic:
        language = {file.path: file.language for file in files}
        reused = {rel for rel in reused if language[rel] not in _SEMANTIC_LANGUAGES}
    symbol_index = _symbol_index(abs_root, files, generated_at, base_symbols, reused, contents)
    if semantic:
        resolution = _build_call_graph(abs_root, files, symbol_index, generated_at, contents=contents)[
            "semantic_resolution"
        ]
        if resolution.get("status") in {"unavailable", "degraded"}:
            degraded["semantic_resolution"] = resolution
    else:
        resolution = _SEMANTIC_NOT_REQUIRED
        symbol_index["semantic_resolution"] = dict(resolution)
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


def apply_overlay(
    root: str,
    *,
    out: str = ".simplicio-loop",
    meta: dict | None = None,
) -> OverlayOutcome:
    """:func:`compute_overlay`, then persist the worktree's own state (never the base).

    Writes only inside ``<root>/<out>``; removes the heavy derived artifacts of an older
    generation. On a fallback nothing is written or removed.
    """
    outcome = compute_overlay(root, out=out, meta=meta)
    if outcome.artifacts is None or outcome.state is None:
        return outcome
    state_dir = os.path.join(os.path.abspath(root), out)
    os.makedirs(state_dir, exist_ok=True)
    for name, file_name in OVERLAY_ARTIFACT_FILES.items():
        _write_json_stable(os.path.join(state_dir, file_name), outcome.artifacts[name])
    _write_json_stable(os.path.join(state_dir, OVERLAY_STATE_FILE), outcome.state)
    for stale in SUPERSEDED_FILES:
        try:
            os.remove(os.path.join(state_dir, stale))
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return outcome


__all__ = [
    "OVERLAY_ARTIFACT_FILES", "OVERLAY_RECEIPT_SCHEMA", "OVERLAY_STATE_FILE", "OVERLAY_STATE_SCHEMA",
    "OverlayOutcome", "SUPERSEDED_FILES", "apply_overlay", "compute_overlay",
]
