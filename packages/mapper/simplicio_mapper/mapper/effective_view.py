"""Lazy composition of ``EffectiveMapView`` (ADR-008 migration-plan step 5, issue #236).

This module implements *only* the composition step from
``.specs/architecture/ADR-008-canonical-map-overlays.md``: given an
already-built :class:`~simplicio_mapper.mapper.canonical.CanonicalMapManifest`
and an optional already-computed
:class:`~simplicio_mapper.mapper.canonical.WorktreeOverlay`, produce the
:class:`~simplicio_mapper.mapper.canonical.EffectiveMapView` that later
consumers (query/ask/status, once wired -- out of scope here) will read.

Building the canonical manifest itself (migration-plan step 3) and computing
the overlay delta (step 4) are **not** implemented here -- this module only
composes objects that already exist, matching the ADR's explicit "no
full-copy" requirement:

- Composition (:func:`compose_effective_view`) never opens, reads, or
  iterates the canonical manifest's file inventory. It uses only the fields
  already resident on ``CanonicalMapManifest`` (in particular
  ``counts["files"]``) plus whatever is already resident on the (typically
  tiny) ``WorktreeOverlay`` to populate ``EffectiveMapDiagnostics``. Building
  the diagnostics is therefore O(size of overlay), never O(size of
  canonical base).
- Per-path resolution (:class:`LazyFileResolver`) is a thin read-only
  accessor: for a path shadowed by the overlay (added/modified/renamed-into)
  it returns the overlay's own :class:`OverlayFileChange` -- no canonical I/O
  at all. For a path in ``overlay.tombstones`` (or the source path of a
  rename, or an explicit ``"removed"`` entry) it returns the :data:`REMOVED`
  sentinel -- again no canonical I/O. Only when a path falls through to the
  canonical base does it touch disk, and even then it reads only as much of
  the canonical file-manifest artifact as needed to find that one entry (see
  ``_iter_canonical_file_entries`` below) -- it never loads the whole
  manifest into memory as a Python object up front.

Assumed on-disk shape of the canonical file-manifest artifact
---------------------------------------------------------------

``CanonicalMapManifest.artifact_paths`` is a ``dict[str, str]`` of logical
name -> path relative to ``storage_root`` (see ``canonical.py``'s
docstring). The builder that populates this dict
(:func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest`,
migration-plan step 3) writes the logical name ``"file_manifest"`` as a
**JSON Lines** file -- one JSON object per line, each with at least a
``"path"`` key, re-serialized from ``project_map["files"]`` at build time --
rather than a single JSON document holding the entire inventory as one
array/object (see ``canonical_builder._write_file_manifest_jsonl``). JSON
Lines is chosen deliberately: it lets a lookup stop reading as soon as it
finds a matching line, instead of parsing (and materializing) every entry in
the file, which is what a single top-level JSON array/object would force.

Shape chosen for the accessor
------------------------------

A single small class, :class:`LazyFileResolver`, wraps one
``EffectiveMapView`` and exposes ``resolve(path) -> ResolvedFile``. A class
(rather than a bag of free functions) was chosen because the overlay-derived
shadow sets (touched paths / removed paths) are worth computing once per
view and reusing across many ``resolve()`` calls in the same session --
free functions would either recompute those sets on every call or force
callers to thread the same intermediate state through by hand.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Union

from .canonical import (
    EFFECTIVE_MAP_VIEW_SCHEMA,
    EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
    CanonicalMapManifest,
    EffectiveMapDiagnostics,
    EffectiveMapView,
    OverlayFileChange,
    WorktreeOverlay,
)

#: Change types in ``OverlayFileChange``/``changed_files`` that still shadow
#: the canonical version of a path with *content* (as opposed to removing
#: it outright).
_CONTENT_SHADOW_TYPES = ("added", "modified", "renamed")


class _RemovedSentinel:
    """Sentinel type returned by :meth:`LazyFileResolver.resolve` for tombstoned paths.

    A dedicated type (rather than reusing ``None``) keeps "path removed by
    the overlay" distinguishable from "path not found anywhere" -- callers
    that only check ``is None`` would otherwise conflate the two.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "REMOVED"

    def __bool__(self) -> bool:
        return False


#: Singleton returned by :meth:`LazyFileResolver.resolve` for a path shadowed
#: by a tombstone (removed, or the source side of a rename).
REMOVED = _RemovedSentinel()

ResolvedFile = Union[OverlayFileChange, dict, _RemovedSentinel, None]


def compose_effective_view(
    canonical: CanonicalMapManifest, overlay: WorktreeOverlay | None
) -> EffectiveMapView:
    """Compose an immutable, lazy ``EffectiveMapView`` from existing objects.

    Pure composition: this function performs no I/O beyond what is already
    resident on ``canonical``/``overlay`` (i.e. none at all -- both
    arguments are already-built, in-memory dataclasses). Compatibility
    validation (``overlay.is_compatible_with_base()``, ``overlay.base_key ==
    canonical.key``) is intentionally **not** duplicated here: it already
    lives in ``EffectiveMapView.__post_init__`` and fires when the
    constructed view below is instantiated, raising ``ValueError`` on
    mismatch.
    """
    diagnostics = _build_diagnostics(canonical, overlay)
    return EffectiveMapView(
        schema=EFFECTIVE_MAP_VIEW_SCHEMA,
        schema_version=EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
        canonical=canonical,
        overlay=overlay,
        diagnostics=diagnostics,
    )


def _build_diagnostics(
    canonical: CanonicalMapManifest, overlay: WorktreeOverlay | None
) -> EffectiveMapDiagnostics:
    """Compute diagnostics using only already-resident fields (no canonical I/O).

    ``files_reused``/``files_remapped`` are derived from
    ``canonical.counts["files"]`` (a plain int already on the manifest) and
    the overlay's own ``changed_files``/``tombstones`` (bounded by the size
    of the delta, never the size of the canonical base) -- the canonical
    file inventory itself is never opened here.
    """
    if overlay is None:
        total_files = canonical.counts.get("files", 0)
        return EffectiveMapDiagnostics(
            cache_hit=True,
            single_flight_waited=False,
            files_reused=total_files,
            files_remapped=0,
            invalidation_reason=None,
        )

    shadowed_paths, remapped_count = _overlay_shadow_summary(overlay)
    total_files = canonical.counts.get("files", 0)
    files_reused = max(total_files - len(shadowed_paths), 0)
    return EffectiveMapDiagnostics(
        cache_hit=True,
        single_flight_waited=False,
        files_reused=files_reused,
        files_remapped=remapped_count,
        invalidation_reason=None,
    )


def _overlay_shadow_summary(overlay: WorktreeOverlay) -> tuple[set[str], int]:
    """Return (paths shadowed for any reason, count remapped with content).

    Shadowed = every path the overlay says is no longer safely served by the
    canonical manifest -- added/modified/renamed-into paths, tombstoned
    paths, and (defensively) any explicit ``"removed"`` entry in
    ``changed_files`` -- matching the task's definition: "added/modified/
    renamed/removed all shadow the canonical version for that path".
    Remapped = only the paths that carry actual overlay *content*
    (added/modified/renamed), excluding removals, per the same definition.
    """
    shadowed: set[str] = set(overlay.tombstones)
    remapped_count = 0
    for change in overlay.changed_files:
        shadowed.add(change.path)
        if change.change_type == "renamed" and change.previous_path:
            shadowed.add(change.previous_path)
        if change.change_type in _CONTENT_SHADOW_TYPES:
            remapped_count += 1
    return shadowed, remapped_count


@dataclass
class LazyFileResolver:
    """Read-only per-path accessor over a composed ``EffectiveMapView``.

    Given a relative path, :meth:`resolve` returns:

    - the overlay's :class:`OverlayFileChange` when the path was
      added/modified/renamed-into by the overlay (no canonical I/O);
    - :data:`REMOVED` when the path is tombstoned -- present in
      ``overlay.tombstones``, the source side of a rename, or an explicit
      ``"removed"`` change (no canonical I/O, and canonical is never
      consulted for a tombstoned path even if it still has an entry there);
    - otherwise, the canonical file-manifest entry for that path (a
      ``dict``) read lazily from disk, or ``None`` if the path is not found
      in either layer.
    """

    view: EffectiveMapView

    def __post_init__(self) -> None:
        self._shadow_index: dict[str, OverlayFileChange] = {}
        self._removed: set[str] = set()
        overlay = self.view.overlay
        if overlay is not None:
            self._removed.update(overlay.tombstones)
            for change in overlay.changed_files:
                if change.change_type in _CONTENT_SHADOW_TYPES:
                    self._shadow_index[change.path] = change
                    if change.change_type == "renamed" and change.previous_path:
                        self._removed.add(change.previous_path)
                elif change.change_type == "removed":
                    self._removed.add(change.path)

    def resolve(self, path: str) -> ResolvedFile:
        """Resolve ``path`` through the overlay first, then the canonical base."""
        if path in self._shadow_index:
            return self._shadow_index[path]
        if path in self._removed:
            return REMOVED
        return _lookup_canonical_entry(self.view.canonical, path)


def _canonical_file_manifest_path(canonical: CanonicalMapManifest) -> str | None:
    relative = canonical.artifact_paths.get("file_manifest")
    if not relative:
        return None
    return os.path.join(canonical.storage_root, relative)


def _iter_canonical_file_entries(canonical: CanonicalMapManifest):
    """Yield ``(path, entry)`` pairs from the canonical file manifest, lazily.

    Reads the backing JSON Lines file one line at a time via a generator --
    callers that stop iterating early (e.g. once a match is found) never
    cause the remaining lines to be read or parsed, so a lookup for one path
    never materializes the full canonical file inventory in memory.
    """
    manifest_path = _canonical_file_manifest_path(canonical)
    if not manifest_path or not os.path.isfile(manifest_path):
        return
    with open(manifest_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            path = entry.get("path")
            if path:
                yield path, entry


def _lookup_canonical_entry(canonical: CanonicalMapManifest, path: str) -> dict | None:
    for entry_path, entry in _iter_canonical_file_entries(canonical):
        if entry_path == path:
            return entry
    return None
