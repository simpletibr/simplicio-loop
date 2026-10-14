"""Opt-in canonical-map reuse for ``index``/``scan`` (issue #269, ADR-008 step 6).

This module implements the **adapter** step of ADR-008's migration plan: an
explicitly opt-in path that lets ``index``/``scan`` reuse an already-built
:class:`~simplicio_mapper.mapper.canonical.CanonicalMapManifest` (Phase-0
schemas + step-3 builder + step-4 overlay + step-5 lazy composition, all
already merged) instead of re-running the full mapping pipeline for every
worktree.

Scope, deliberately narrow and documented (never silently over-promised):

- **Opt-in only.** Default behavior (no flag, no env var) is completely
  unchanged -- this module is never imported/called unless
  :func:`is_canonical_reuse_enabled` returns ``True``. See
  ``CANONICAL_REUSE_ENV_VAR`` / the ``--canonical-reuse`` CLI flag
  (``simplicio_mapper/cli/_args.py``).
- **Hit only for a *trivial* overlay.** A worktree qualifies for reuse only
  when its ``HEAD`` is exactly the canonical manifest's ``commit_sha`` *and*
  it has no staged/unstaged/untracked changes (see
  :func:`_overlay_is_trivial`). Merging a non-trivial
  :class:`~simplicio_mapper.mapper.canonical.WorktreeOverlay` (added/
  modified/renamed/removed files) into ``symbol-index.json``/
  ``call-graph.json`` would require re-deriving cross-file relationships
  (call edges, precedent ranking) from a partial patch -- a substantially
  larger, higher-risk change than this issue's wiring scope, and one this
  module refuses to attempt silently. Any non-trivial overlay is a
  documented, first-class fallback reason (``"overlay_not_trivial"``), never
  a silent miss -- this is the single biggest known limitation of this
  module and is exactly why the repo's "never serve stale data" invariant
  holds: an unsupported case always takes the legacy full-map path, never a
  best-effort (and therefore possibly wrong) merge.
- **Fail-closed everywhere else.** Any Git/identity/build/overlay/contract
  failure returns a fallback receipt (see :data:`RECEIPT_SCHEMA`) and
  ``None`` for the materialized result; the caller (``cli/_index_engine.py``)
  always falls back to the existing, unmodified full-map path in that case.

On a genuine hit, the four artifacts the canonical manifest tracks
(``project-map``, ``precedent-index``, ``symbol-index``, ``call-graph``) are
read verbatim from the canonical, content-addressed store (they were built
by the very same :func:`simplicio_mapper.mapper.emit.build_artifacts`
pipeline against the exact commit this worktree's ``HEAD`` also points to,
so they are provably identical to what a full local map would produce).
``architecture-inventory.json`` is not one of the four canonical artifacts
(see ``canonical_builder.py``'s docstring) so it is cheaply *recomputed*
locally from the reused ``project_map``/``symbol_index``/``call_graph``
dicts -- no source file is re-read or re-parsed to do this.
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass

import orjson

from ..models import ProjectFile
from .canonical import CanonicalMapManifest, WorktreeOverlay
from .canonical_builder import build_canonical_manifest_with_diagnostics
from .canonical_identity import resolve_repo_identity_bundle
from .canonical_overlay import compute_worktree_overlay
from .canonical_storage import resolve_canonical_cache_root
from .effective_view import compose_effective_view
from .graph import _build_architecture_inventory
from .parse import _JSON_WRITE_OPTIONS, _now_iso

#: Opt-in switch (env var). Mirrors the ``SIMPLICIO_MAPPER_NO_RUNTIME_*`` /
#: ``SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR`` naming convention already used in
#: this package. Truthy values: ``"1"``, ``"true"``, ``"yes"``, ``"on"``
#: (case-insensitive) -- same convention ``_run_scan``'s ``CI`` check uses.
CANONICAL_REUSE_ENV_VAR = "SIMPLICIO_MAPPER_CANONICAL_REUSE"

#: Reason codes from :func:`build_canonical_manifest_with_diagnostics` that
#: indicate this call waited for a concurrent builder (winner or loser of
#: the race) before getting a manifest. Anything else means it never had to
#: wait (cache hit before the lock, or acquired the lock uncontended).
_WAITED_REASON_CODES = frozenset({"reused_after_wait", "built_after_wait"})

RECEIPT_SCHEMA = "simplicio.canonical-reuse-receipt/v1"
RECEIPT_SCHEMA_VERSION = 1

#: Filename the receipt is additionally persisted under, inside the mapper's
#: own output dir (``.simplicio-loop/`` by default) -- alongside the artifacts it
#: describes, so an operator inspecting a worktree after the fact sees the
#: hit/miss/fallback evidence without needing to re-run anything.
RECEIPT_FILE_NAME = "canonical-reuse-receipt.json"

#: Canonical artifact logical names materialized verbatim from the manifest.
#: ``architecture_inventory`` is deliberately absent -- see module docstring.
_REUSED_ARTIFACT_NAMES = ("project_map", "precedent_index", "symbol_index", "call_graph")


def _truthy_env(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def is_canonical_reuse_enabled(opts: dict) -> bool:
    """Whether the opt-in canonical-reuse path should be attempted.

    Either the ``--canonical-reuse`` CLI flag (``opts["canonical_reuse"]``)
    or the ``SIMPLICIO_MAPPER_CANONICAL_REUSE`` env var -- either alone is
    enough to opt in. Default (neither set) is ``False``, so existing
    ``index``/``scan``/``map``/``update`` invocations are entirely
    unaffected unless a caller explicitly opts in.
    """
    if opts.get("canonical_reuse"):
        return True
    return _truthy_env(os.environ.get(CANONICAL_REUSE_ENV_VAR))


def compute_config_fingerprint(meta: dict | None, out: str) -> str:
    """Stable fingerprint of every mapping input outside git identity itself.

    Feeds :class:`~simplicio_mapper.mapper.canonical.CanonicalMapKey`'s
    ``config_fingerprint`` -- per that schema's contract, *any* difference
    here must produce a different digest so two worktrees with different
    ``--stack``/``--product-name`` overrides (or a different artifact
    output directory name) never share a canonical manifest.
    """
    import hashlib
    import json

    meta = meta or {}
    payload = {
        "stack": meta.get("stack") or "",
        "product_name": meta.get("product_name") or "",
        "project_mode": meta.get("project_mode") or "root",
        "out": out,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=24).hexdigest()


def _out_dir_prefix(out: str) -> str:
    """Normalize ``out`` (e.g. ``".simplicio-loop"``) to a ``"prefix/"`` match string."""
    rel = out.replace("\\", "/").strip("/")
    return f"{rel}/" if rel else ""


def _within_out_dir(path: str, out_prefix: str) -> bool:
    if not out_prefix:
        return False
    trimmed = out_prefix.rstrip("/")
    return path == trimmed or path.startswith(out_prefix)


def _overlay_is_trivial(overlay: WorktreeOverlay, canonical_commit_sha: str, out: str) -> bool:
    """Whether ``overlay`` represents "no delta at all" against the canonical base.

    Deliberately ignores changes confined entirely to the mapper's own
    ``out`` directory (e.g. a freshly created ``.simplicio-loop/index.lock`` or
    ``.simplicio-loop/cache/`` before this very run wrote anything) -- those are
    an artifact of running the mapper itself, not a real divergence from the
    canonical commit, and would otherwise make ``git status`` report the
    worktree as permanently "dirty" the very first time a caller opts in,
    starving the reuse path even on a genuinely clean checkout. Any change
    outside ``out`` -- including ``overlay.dirty`` uncommitted edits to real
    source files -- still makes the overlay non-trivial.

    See the module docstring's "Hit only for a trivial overlay" section for
    why a non-trivial overlay always falls back instead of being merged.
    """
    if overlay.worktree_commit_sha != canonical_commit_sha:
        return False
    out_prefix = _out_dir_prefix(out)
    for change in overlay.changed_files:
        if not _within_out_dir(change.path, out_prefix):
            return False
        if change.previous_path and not _within_out_dir(change.previous_path, out_prefix):
            return False
    for path in overlay.tombstones:
        if not _within_out_dir(path, out_prefix):
            return False
    return True


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "rb") as handle:
            return orjson.loads(handle.read())
    except (OSError, orjson.JSONDecodeError):
        return None


def _write_json_stable(path: str, data: object) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    # A unique temp name per writer: a shared "<file>.tmp" makes two writers of one file race on
    # os.replace (FileNotFoundError, issue #1574 review).
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(orjson.dumps(data, option=_JSON_WRITE_OPTIONS))
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _project_files_from_entries(entries: list[dict]) -> list[ProjectFile]:
    """Reconstruct :class:`ProjectFile` objects from ``project_map["files"]`` dicts.

    ``text_preview`` is intentionally left empty: it is never persisted to
    ``project-map.json`` in the first place (see ``ProjectFile.to_dict``) and
    is not read by :func:`~simplicio_mapper.mapper.graph._build_architecture_inventory`
    (only ``path``/``language``/``roles``/``imports``/``exports`` are).
    """
    files: list[ProjectFile] = []
    for entry in entries:
        files.append(
            ProjectFile(
                path=entry.get("path", ""),
                language=entry.get("language", ""),
                size_bytes=entry.get("size_bytes", 0),
                last_modified=entry.get("last_modified", ""),
                file_hash=entry.get("file_hash", ""),
                git_status=entry.get("git_status", ""),
                roles=list(entry.get("roles") or []),
                imports=list(entry.get("imports") or []),
                exports=list(entry.get("exports") or []),
                importance=entry.get("importance", 0.0),
                bh_address=entry.get("bh_address", ""),
                agent_id=entry.get("agent_id", ""),
            )
        )
    return files


@dataclass
class CanonicalReuseOutcome:
    """Result of one :func:`attempt_canonical_reuse` call.

    ``run_result`` mirrors the shape
    :func:`simplicio_mapper.mapper.emit.write_mapping_artifacts` returns
    (``*_path`` keys plus the parsed artifact dicts) so the caller can treat
    a hit exactly like a legacy full-map run downstream (retrieval-index
    build, history snapshot, docs). It is ``None`` on any miss/fallback.
    """

    receipt: dict
    run_result: dict | None


def _fallback(receipt_base: dict, reason: str) -> CanonicalReuseOutcome:
    receipt = dict(receipt_base)
    receipt["hit"] = False
    receipt["fallback_reason"] = reason
    receipt["duration_s"] = round(time.monotonic() - receipt.pop("_t0"), 4)
    return CanonicalReuseOutcome(receipt=receipt, run_result=None)


def attempt_canonical_reuse(root: str, out: str, meta: dict | None) -> CanonicalReuseOutcome:
    """Attempt the opt-in canonical-reuse path; never raises.

    Returns a :class:`CanonicalReuseOutcome` whose ``receipt`` is always
    populated (hit or fallback) and whose ``run_result`` is populated only
    on a genuine hit. Callers must treat ``run_result is None`` as "run the
    legacy full map instead" -- this function performs no destructive
    action and writes nothing on a miss.
    """
    t0 = time.monotonic()
    receipt_base: dict = {
        "schema": RECEIPT_SCHEMA,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "enabled": True,
        "single_flight_waited": False,
        "files_reused": 0,
        "files_remapped": 0,
        "canonical_commit_sha": None,
        "worktree_commit_sha": None,
        "canonical_key_digest": None,
        "_t0": t0,
    }
    try:
        abs_root = os.path.abspath(root)
        identity = resolve_repo_identity_bundle(abs_root)
        if identity is None:
            return _fallback(receipt_base, "identity_unresolved")

        config_fingerprint = compute_config_fingerprint(meta, out)
        receipt_base["config_fingerprint"] = config_fingerprint
        cache_root = resolve_canonical_cache_root(identity.common_git_dir)

        # `build_canonical_manifest_with_diagnostics` owns the single real
        # cross-worktree single-flight lock for this digest (see
        # `canonical_builder.py` / `canonical_storage.canonical_build_lock_path`
        # / `file_lock.py`). This module used to additionally wrap the call in
        # its own ad-hoc advisory lock at that exact same path -- a second,
        # incompatible lock implementation racing the first one for the same
        # file. Since both locks lived at an identical path, the outer
        # advisory lock (held for the whole duration of this call) made the
        # inner lock observe its *own* PID as a live, non-reclaimable "legacy"
        # owner and spin for the full `lock_wait_seconds` budget every single
        # time -- a guaranteed self-deadlock, not a real contention scenario.
        # Calling the real builder directly removes the redundant lock and
        # the collision with it; `build_canonical_manifest_with_diagnostics`'s
        # own reason codes already report whether this call had to wait.
        build_result = build_canonical_manifest_with_diagnostics(
            abs_root, cache_root, config_fingerprint
        )
        manifest = build_result.manifest
        receipt_base["single_flight_waited"] = build_result.reason_code in _WAITED_REASON_CODES
        if manifest is None:
            return _fallback(receipt_base, "canonical_build_failed")

        receipt_base["canonical_key_digest"] = manifest.key.digest()
        receipt_base["canonical_commit_sha"] = manifest.key.commit_sha

        overlay = compute_worktree_overlay(abs_root, manifest.key, config_fingerprint)
        if overlay is None:
            return _fallback(receipt_base, "overlay_computation_failed")
        receipt_base["worktree_commit_sha"] = overlay.worktree_commit_sha
        receipt_base["dirty"] = overlay.dirty

        if not overlay.is_compatible_with_base():
            return _fallback(receipt_base, "config_fingerprint_mismatch")

        if not _overlay_is_trivial(overlay, manifest.key.commit_sha, out):
            return _fallback(receipt_base, "overlay_not_trivial")

        try:
            compose_effective_view(manifest, overlay)
        except ValueError:
            return _fallback(receipt_base, "effective_view_composition_failed")

        run_result = _materialize_hit(abs_root, out, manifest)
        if run_result is None:
            return _fallback(receipt_base, "materialization_failed")

        receipt = dict(receipt_base)
        receipt.pop("_t0", None)
        receipt["hit"] = True
        receipt["fallback_reason"] = None
        # A trivial overlay (the only kind that reaches this point, see
        # `_overlay_is_trivial`) means every file was served verbatim from
        # the canonical manifest -- report that directly from
        # `manifest.counts` rather than from `EffectiveMapDiagnostics`,
        # which does not know about the out-dir-only noise
        # `_overlay_is_trivial` deliberately tolerates above.
        receipt["files_reused"] = manifest.counts.get("files", 0)
        receipt["files_remapped"] = 0
        receipt["duration_s"] = round(time.monotonic() - t0, 4)
        return CanonicalReuseOutcome(receipt=receipt, run_result=run_result)
    except Exception as error:  # noqa: BLE001 - reuse path must always fail closed
        receipt_base["_t0"] = t0
        return _fallback(receipt_base, f"unexpected_error:{type(error).__name__}:{error}")


def _materialize_hit(root: str, out: str, manifest: CanonicalMapManifest) -> dict | None:
    """Write the reused artifacts into ``<root>/<out>``; return the ``write_mapping_artifacts``-shaped dict.

    Reads the four canonical JSON artifacts verbatim (no reparse), rebuilds
    only the cheap, purely-derived ``architecture-inventory`` locally, and
    writes all five to disk exactly where the legacy full-map path would.
    Returns ``None`` (fail closed, caller falls back to the legacy path) if
    any canonical artifact cannot be read.
    """
    artifacts: dict[str, dict] = {}
    for name in _REUSED_ARTIFACT_NAMES:
        relative = manifest.artifact_paths.get(name)
        if not relative:
            return None
        data = _read_json(os.path.join(manifest.storage_root, relative))
        if data is None:
            return None
        artifacts[name] = data

    generated_at = _now_iso()
    project_map = dict(artifacts["project_map"])
    project_map["generated_at"] = generated_at
    precedent_index = dict(artifacts["precedent_index"])
    precedent_index["generated_at"] = generated_at
    symbol_index = dict(artifacts["symbol_index"])
    symbol_index["generated_at"] = generated_at
    call_graph = dict(artifacts["call_graph"])
    call_graph["generated_at"] = generated_at

    files = _project_files_from_entries(list(project_map.get("files") or []))
    architecture_inventory = _build_architecture_inventory(
        root, project_map, files, symbol_index, call_graph, generated_at
    )

    abs_out = os.path.abspath(os.path.join(root, out))
    project_map_path = os.path.join(abs_out, "project-map.json")
    precedent_path = os.path.join(abs_out, "precedent-index.json")
    architecture_inventory_path = os.path.join(abs_out, "architecture-inventory.json")
    symbol_index_path = os.path.join(abs_out, "symbol-index.json")
    call_graph_path = os.path.join(abs_out, "call-graph.json")

    _write_json_stable(project_map_path, project_map)
    _write_json_stable(precedent_path, precedent_index)
    _write_json_stable(architecture_inventory_path, architecture_inventory)
    _write_json_stable(symbol_index_path, symbol_index)
    _write_json_stable(call_graph_path, call_graph)
    try:  # a full set supersedes the worktree's overlay state (issue #1574)
        os.remove(os.path.join(abs_out, "overlay.json"))
    except OSError:
        pass

    return {
        "project_map_path": project_map_path,
        "precedent_path": precedent_path,
        "architecture_inventory_path": architecture_inventory_path,
        "symbol_index_path": symbol_index_path,
        "call_graph_path": call_graph_path,
        "project_map": project_map,
        "precedent_index": precedent_index,
        "architecture_inventory": architecture_inventory,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
    }


def write_receipt(root: str, out: str, receipt: dict) -> str:
    """Persist ``receipt`` under ``<root>/<out>/canonical-reuse-receipt.json``; return its path."""
    abs_out = os.path.abspath(os.path.join(root, out))
    path = os.path.join(abs_out, RECEIPT_FILE_NAME)
    _write_json_stable(path, receipt)
    return path
