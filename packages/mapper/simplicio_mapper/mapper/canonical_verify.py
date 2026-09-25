"""Independent parity proof: ``EffectiveMapView`` vs. a full remap (issue #267).

This module implements *only* migration-plan step 7's ``verify`` half from
``.specs/architecture/ADR-008-canonical-map-overlays.md`` (``canonical
status/build/verify/gc``) -- specifically the ``verify`` verb. ``build`` is
tracked separately (issue #266, implemented in parallel); this module does
**not** depend on that command existing -- it calls the already-merged
canonical-map model modules directly:
:func:`simplicio_mapper.mapper.canonical_identity.resolve_repo_identity_bundle`,
:func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest`,
:func:`simplicio_mapper.mapper.canonical_overlay.compute_worktree_overlay`,
and :func:`simplicio_mapper.mapper.effective_view.compose_effective_view`.

Two genuinely independent computations are compared -- never a structure
compared with itself:

1. **Effective view** -- ``CanonicalMapManifest`` (built/reused via
   ``build_canonical_manifest``, itself materialized via a detached
   ``git worktree add`` checkout of the default-branch commit) composed with
   a real ``WorktreeOverlay`` (computed via ``compute_worktree_overlay``,
   itself two real ``git`` passes: ``git diff --name-status`` for the
   committed delta, ``git status --porcelain`` for staged/unstaged/untracked)
   into an ``EffectiveMapView``, resolved path-by-path via
   ``LazyFileResolver``.
2. **Full remap** -- :func:`simplicio_mapper.mapper.emit.build_artifacts` run
   directly against the worktree's current (possibly dirty) state -- the
   same single mapping pipeline every other command uses, with no awareness
   of the canonical/overlay machinery at all.

Per-file comparison uses ``file_hash`` (sha256 of decoded file text, computed
identically to :func:`simplicio_mapper.mapper.parse._sha256` -- imported
directly, not reimplemented, so the two sides can never silently drift by
using two different hash functions) for paths the canonical file-manifest
already carries a ``file_hash`` for, and a live re-read of the file (via
:func:`simplicio_mapper.mapper.parse._content_for` + ``_sha256``) for paths
the overlay shadows (added/modified/renamed) -- the overlay's own
``content_digest`` uses a different hash family (blake2b, matching
``FileProcessingCache``) and is intentionally not reused here to keep both
sides of the comparison on the exact same hash function.

Fails closed: any failure to resolve identity, build the canonical manifest,
compute the overlay, compose the view, or run the full remap returns a
``"fail"`` receipt with a precise ``failure_reason`` -- never a ``"match"``
result built from partial/missing data.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass

from .canonical_builder import build_canonical_manifest
from .canonical_identity import is_git_repository, resolve_repo_identity_bundle
from .canonical_overlay import compute_worktree_overlay
from .canonical_storage import resolve_canonical_cache_root
from .effective_view import REMOVED, LazyFileResolver, compose_effective_view
from .emit import build_artifacts
from .parse import SKIP_DIRS, _content_for, _sha256

CANONICAL_VERIFY_SCHEMA = "simplicio.canonical-verify/v1"
CANONICAL_VERIFY_SCHEMA_VERSION = 1

#: Comparison method identifier recorded on every receipt -- names the two
#: independent computations being reconciled (audit trail: proves this
#: was never a self-comparison).
_COMPARISON_METHOD = "effective-view-lazy-resolve-vs-independent-full-remap"

#: Deterministic default cap on how many files a single verify run inspects,
#: applied to the *sorted* path set so two runs against the same state always
#: bound to the exact same subset -- a scale guard for accidentally running
#: ``verify`` against a huge repo, not a correctness shortcut (the fixtures
#: this module is tested against are always small and fully within this
#: bound; see ``tests/python/test_canonical_verify*.py``).
DEFAULT_FILE_LIMIT = 20000

#: Cap on how many individual mismatch entries the receipt embeds -- avoids
#: an unbounded receipt on a large divergence while `counts.mismatches`
#: still reports the true total.
_MAX_EMBEDDED_MISMATCHES = 200


def _is_out_of_scope(path: str) -> bool:
    """Whether ``path`` falls under a directory the full remap structurally skips.

    ``compute_worktree_overlay`` reports every git-visible change, including
    the mapper's own output/cache directory (``.simplicio/``, part of
    ``simplicio_mapper.mapper.parse.SKIP_DIRS``) when it happens to be
    untracked rather than gitignored. The full remap side of this
    comparison (:func:`simplicio_mapper.mapper.emit.build_artifacts`) never
    walks into any ``SKIP_DIRS`` entry at all -- so a path under one of them
    must be excluded from *both* sides of the comparison here too, or a
    perfectly consistent worktree would spuriously "diverge" over a
    directory neither side actually considers part of the map.
    """
    return any(segment in SKIP_DIRS for segment in path.split("/"))


@dataclass(frozen=True)
class CanonicalVerifyOptions:
    """Inputs for :func:`verify_canonical_parity`, all optional but ``root``."""

    root: str
    storage_root: str | None = None
    config_fingerprint: str = "default"
    file_limit: int = DEFAULT_FILE_LIMIT


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _receipt(
    *,
    result: str,
    failure_reason: str | None,
    comparison_method: str = _COMPARISON_METHOD,
    counts: dict[str, int] | None = None,
    digest: str | None = None,
    duration_seconds: float = 0.0,
    mismatches: list[dict[str, str]] | None = None,
) -> dict:
    """Build the versioned receipt envelope.

    Never carries an absolute path or raw file content -- only relative
    paths (already repo-relative from git output), content-addressed
    digests, and counts.
    """
    return {
        "schema": CANONICAL_VERIFY_SCHEMA,
        "schema_version": CANONICAL_VERIFY_SCHEMA_VERSION,
        "result": result,
        "failure_reason": failure_reason,
        "comparison_method": comparison_method,
        "counts": counts or {},
        "digest": digest,
        "duration_seconds": round(duration_seconds, 6),
        "mismatches": mismatches or [],
        "generated_at": _now_iso(),
    }


def _receipt_digest(
    canonical_key_digest: str | None, effective: dict[str, str | None], remap: dict[str, str | None]
) -> str:
    """Stable content-address of the comparison inputs -- no path/content leak.

    Built only from relative paths (already the shape every hash source in
    this module carries) and their digests -- never an absolute path, never
    raw file content.
    """
    parts = [canonical_key_digest or ""]
    for path in sorted(effective):
        parts.append(f"e:{path}:{effective[path] or ''}")
    for path in sorted(remap):
        parts.append(f"r:{path}:{remap[path] or ''}")
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=24).hexdigest()


def _effective_digest_map(
    manifest, overlay, file_limit: int
) -> tuple[dict[str, str | None], str | None]:
    """Resolve every live path reachable through the composed view to a digest.

    Returns ``(path -> digest_or_None, error_reason)``. A non-``None`` error
    means the manifest/overlay's own contract was invalid (missing
    ``file_manifest`` artifact key) and the caller must fail closed instead
    of treating an empty/partial result as parity.
    """
    if "file_manifest" not in (manifest.artifact_paths or {}):
        return {}, "canonical_manifest_missing_file_manifest_artifact"

    view = compose_effective_view(manifest, overlay)
    resolver = LazyFileResolver(view)

    # Canonical-side candidate paths: every path in the JSON Lines
    # file-manifest artifact, streamed lazily (never materializing the
    # whole file as one JSON document) -- mirrors
    # `effective_view._iter_canonical_file_entries`'s own streaming
    # contract, reused here rather than duplicated with a different shape.
    from .effective_view import _iter_canonical_file_entries

    canonical_paths = {path for path, _entry in _iter_canonical_file_entries(manifest)}

    overlay_paths: set[str] = set()
    tombstoned: set[str] = set()
    if overlay is not None:
        tombstoned.update(overlay.tombstones)
        for change in overlay.changed_files:
            if change.change_type == "removed":
                tombstoned.add(change.path)
            else:
                overlay_paths.add(change.path)
                if change.change_type == "renamed" and change.previous_path:
                    tombstoned.add(change.previous_path)

    candidate_paths = sorted(
        path
        for path in (canonical_paths | overlay_paths) - tombstoned
        if not _is_out_of_scope(path)
    )
    if file_limit > 0:
        candidate_paths = candidate_paths[:file_limit]

    digests: dict[str, str | None] = {}
    worktree_root = overlay.worktree_path if overlay is not None else None

    for path in candidate_paths:
        resolved = resolver.resolve(path)
        if resolved is REMOVED or resolved is None:
            # Contract violation (path advertised by the manifest/overlay but
            # not actually resolvable) -- recorded as a missing digest so the
            # comparison step below flags it as a mismatch rather than
            # silently dropping it from the file set.
            digests[path] = None
            continue
        if isinstance(resolved, dict):
            digests[path] = resolved.get("file_hash")
        else:
            # Overlay-shadowed (added/modified/renamed): re-hash the live
            # file with the exact same function the full remap uses, so
            # both sides of the comparison agree on what "the same content"
            # means. `worktree_root` is only ever the overlay's own
            # worktree_path (never a foreign path) -- an overlay always
            # carries the root it was computed against.
            if worktree_root is None:
                digests[path] = None
                continue
            text = _content_for(worktree_root, path, None)
            digests[path] = _sha256(text)

    return digests, None


def _remap_digest_map(root: str, file_limit: int) -> tuple[dict[str, str | None], str | None]:
    """Independently run the full mapping pipeline and extract per-file digests."""
    try:
        artifacts = build_artifacts(root, meta=None, incremental=False)
    except Exception as error:  # noqa: BLE001 - any pipeline failure must fail closed
        return {}, f"full_remap_raised:{type(error).__name__}"
    files = (artifacts.get("project_map") or {}).get("files") or []
    paths = sorted(
        entry.get("path")
        for entry in files
        if entry.get("path") and not _is_out_of_scope(entry["path"])
    )
    if file_limit > 0:
        paths = paths[:file_limit]
    allowed = set(paths)
    return {
        entry["path"]: entry.get("file_hash")
        for entry in files
        if entry.get("path") in allowed
    }, None


def verify_canonical_parity(
    root: str,
    *,
    storage_root: str | None = None,
    config_fingerprint: str = "default",
    file_limit: int = DEFAULT_FILE_LIMIT,
) -> dict:
    """Prove (or disprove) semantic parity between ``EffectiveMapView`` and a full remap.

    Fails closed at every step: a ``None``/exception result from any
    upstream helper (identity resolution, canonical build, overlay
    computation, view composition, full remap) returns a ``"fail"`` receipt
    with a precise ``failure_reason`` -- this function never returns
    ``"result": "match"`` from partial or missing data.
    """
    started = time.monotonic()
    root_abs = os.path.abspath(root)

    if not is_git_repository(root_abs):
        return _receipt(
            result="fail",
            failure_reason="not_a_git_repository",
            duration_seconds=time.monotonic() - started,
        )

    identity = resolve_repo_identity_bundle(root_abs)
    if identity is None:
        return _receipt(
            result="fail",
            failure_reason="repo_identity_unresolved",
            duration_seconds=time.monotonic() - started,
        )

    effective_storage_root = storage_root or resolve_canonical_cache_root(identity.common_git_dir)

    try:
        manifest = build_canonical_manifest(root_abs, effective_storage_root, config_fingerprint)
    except Exception as error:  # noqa: BLE001 - CLI-adjacent boundary must fail closed
        return _receipt(
            result="fail",
            failure_reason=f"canonical_build_raised:{type(error).__name__}",
            duration_seconds=time.monotonic() - started,
        )
    if manifest is None:
        return _receipt(
            result="fail",
            failure_reason="canonical_manifest_unavailable",
            duration_seconds=time.monotonic() - started,
        )

    try:
        overlay = compute_worktree_overlay(root_abs, manifest.key, config_fingerprint)
    except Exception as error:  # noqa: BLE001 - CLI-adjacent boundary must fail closed
        return _receipt(
            result="fail",
            failure_reason=f"overlay_computation_raised:{type(error).__name__}",
            duration_seconds=time.monotonic() - started,
        )
    if overlay is None:
        return _receipt(
            result="fail",
            failure_reason="overlay_computation_failed",
            duration_seconds=time.monotonic() - started,
        )

    try:
        compose_effective_view(manifest, overlay)
    except ValueError as error:
        return _receipt(
            result="fail",
            failure_reason=f"effective_view_invalid:{error}",
            duration_seconds=time.monotonic() - started,
        )

    effective_digests, effective_error = _effective_digest_map(manifest, overlay, file_limit)
    if effective_error is not None:
        return _receipt(
            result="fail",
            failure_reason=effective_error,
            duration_seconds=time.monotonic() - started,
        )

    remap_digests, remap_error = _remap_digest_map(root_abs, file_limit)
    if remap_error is not None:
        return _receipt(
            result="fail",
            failure_reason=remap_error,
            duration_seconds=time.monotonic() - started,
        )

    mismatches: list[dict[str, str]] = []
    effective_paths = set(effective_digests)
    remap_paths = set(remap_digests)

    for path in sorted(remap_paths - effective_paths):
        mismatches.append({"path": path, "reason": "missing_in_effective_view"})
    for path in sorted(effective_paths - remap_paths):
        mismatches.append({"path": path, "reason": "missing_in_full_remap"})
    for path in sorted(effective_paths & remap_paths):
        if effective_digests[path] != remap_digests[path]:
            mismatches.append({"path": path, "reason": "digest_mismatch"})

    result = "match" if not mismatches else "mismatch"
    failure_reason = None
    if mismatches:
        reasons = sorted({item["reason"] for item in mismatches})
        failure_reason = "+".join(reasons)

    digest = _receipt_digest(manifest.key.digest(), effective_digests, remap_digests)
    counts = {
        "canonical_files": manifest.counts.get("files", 0),
        "effective_files": len(effective_digests),
        "remap_files": len(remap_digests),
        "matched": len(effective_paths & remap_paths) - sum(
            1 for item in mismatches if item["reason"] == "digest_mismatch"
        ),
        "mismatches": len(mismatches),
        "overlay_changed_files": len(overlay.changed_files),
        "overlay_tombstones": len(overlay.tombstones),
    }

    return _receipt(
        result=result,
        failure_reason=failure_reason,
        counts=counts,
        digest=digest,
        duration_seconds=time.monotonic() - started,
        mismatches=mismatches[:_MAX_EMBEDDED_MISMATCHES],
    )


__all__ = [
    "CANONICAL_VERIFY_SCHEMA",
    "CANONICAL_VERIFY_SCHEMA_VERSION",
    "CanonicalVerifyOptions",
    "DEFAULT_FILE_LIMIT",
    "verify_canonical_parity",
]
