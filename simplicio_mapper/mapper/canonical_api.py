"""Public sync/async API for canonical map views (issue #236, ADR-008 step 8).

The CLI-oriented modules expose operational verbs (``canonical build/status``)
and an opt-in materialization adapter for ``index``/``scan``.  Loop Hub and
other in-process consumers need a smaller, stable API that resolves the same
canonical default-branch manifest, computes the current worktree overlay, and
returns the lazy :class:`EffectiveMapView` without printing CLI receipts or
writing per-worktree artifacts.

Both entry points fail closed: identity/build/overlay/compatibility failures
return ``None`` instead of a partially-composed or stale view.  Callers that
need richer diagnostics can still use the CLI receipts; this module is the
minimal library boundary for safe reuse.
"""

from __future__ import annotations

import asyncio
import os

from .canonical import EffectiveMapView
from .canonical_builder import build_canonical_manifest
from .canonical_identity import resolve_repo_identity_bundle
from .canonical_overlay import compute_worktree_overlay
from .canonical_reuse import compute_config_fingerprint
from .canonical_storage import resolve_canonical_cache_root
from .effective_view import compose_effective_view


def get_effective_map_view(
    root: str,
    *,
    out: str = ".simplicio",
    meta: dict | None = None,
    config_fingerprint: str | None = None,
    storage_root: str | None = None,
) -> EffectiveMapView | None:
    """Return a lazy canonical+overlay view for ``root``, or ``None`` on failure.

    ``config_fingerprint`` may be supplied by an embedding/config-aware caller.
    When omitted, the same deterministic fingerprint used by the opt-in
    ``index``/``scan`` adapter is derived from ``meta`` and ``out`` so the
    library API shares manifests with the CLI path instead of fragmenting the
    cache.
    """
    try:
        abs_root = os.path.abspath(root)
        identity = resolve_repo_identity_bundle(abs_root)
        if identity is None:
            return None
        fingerprint = config_fingerprint or compute_config_fingerprint(meta, out)
        cache_root = storage_root or resolve_canonical_cache_root(identity.common_git_dir)
        manifest = build_canonical_manifest(abs_root, cache_root, fingerprint)
        if manifest is None:
            return None
        overlay = compute_worktree_overlay(abs_root, manifest.key, fingerprint)
        if overlay is None or not overlay.is_compatible_with_base():
            return None
        return compose_effective_view(manifest, overlay)
    except Exception:  # noqa: BLE001 - public reuse API must never serve partial/stale data
        return None


async def get_effective_map_view_async(
    root: str,
    *,
    out: str = ".simplicio",
    meta: dict | None = None,
    config_fingerprint: str | None = None,
    storage_root: str | None = None,
) -> EffectiveMapView | None:
    """Async wrapper around :func:`get_effective_map_view` for Loop Hub users."""
    return await asyncio.to_thread(
        get_effective_map_view,
        root,
        out=out,
        meta=meta,
        config_fingerprint=config_fingerprint,
        storage_root=storage_root,
    )
