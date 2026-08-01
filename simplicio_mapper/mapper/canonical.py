"""Schema definitions for the canonical-map / worktree-overlay design (issue #236).

This module is a **Phase-0 deliverable only**: it defines the versioned
schemas (``CanonicalMapKey``, ``CanonicalMapManifest``, ``WorktreeOverlay``,
``OverlayFileChange``, ``EffectiveMapView``, ``EffectiveMapDiagnostics``)
proposed in ``.specs/architecture/ADR-008-canonical-map-overlays.md``.

No production code path constructs or consumes these types yet. The single
mapping pipeline in ``simplicio_mapper.mapper`` (:mod:`.parse`, :mod:`.graph`,
:mod:`.emit`) and the per-worktree index/lock machinery in
``simplicio_mapper.cli._index_engine`` are unchanged by this module. Wiring
these schemas into a real canonical-map builder, delta computation, atomic
promotion and GC is out of scope here -- see the ADR's migration plan for the
sequenced follow-up steps.

All dataclasses are ``frozen=True``: instances represent immutable snapshots
of a manifest/overlay/view at a point in time, matching the "immutable
canonical map, composed lazily" requirement from the issue.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# Schema version constants. Bump the corresponding ``*_SCHEMA_VERSION`` int
# whenever the shape of the matching dataclass changes in a way that affects
# on-disk compatibility; bump the ``*_SCHEMA`` string only on a breaking
# rename of the schema family itself (mirrors the ``simplicio.*/v1`` pattern
# already used by ``INDEX_STATE_SCHEMA`` and ``INDEX_LOCK_SCHEMA``).
CANONICAL_MAP_SCHEMA = "simplicio.canonical-map/v1"
CANONICAL_MAP_SCHEMA_VERSION = 1

WORKTREE_OVERLAY_SCHEMA = "simplicio.worktree-overlay/v1"
WORKTREE_OVERLAY_SCHEMA_VERSION = 1

EFFECTIVE_MAP_VIEW_SCHEMA = "simplicio.effective-map-view/v1"
EFFECTIVE_MAP_VIEW_SCHEMA_VERSION = 1

#: Valid values for :attr:`OverlayFileChange.change_type`.
OVERLAY_CHANGE_TYPES = frozenset({"added", "modified", "renamed", "removed"})


@dataclass(frozen=True)
class CanonicalMapKey:
    """Identity + invalidation key for a canonical default-branch map.

    Per the issue's mandatory identity rules, every field here participates
    in the reuse decision -- two builds that differ in *any* field below
    must never share a :class:`CanonicalMapManifest`. ``digest()`` is the
    stable, order-independent-of-caller hash used as the content-addressed
    directory name (see ADR-008 section 3).
    """

    repo_identity: str
    default_branch: str
    commit_sha: str
    tree_sha: str
    schema_version: int
    mapper_version: str
    config_fingerprint: str
    platform_tag: str | None = None
    native_capabilities: str = ""

    def digest(self) -> str:
        """Return a stable content-address for this key.

        Field order is fixed (declaration order) so the digest is
        deterministic across processes/platforms for equal keys.
        """
        parts = (
            self.repo_identity,
            self.default_branch,
            self.commit_sha,
            self.tree_sha,
            str(self.schema_version),
            self.mapper_version,
            self.config_fingerprint,
            self.platform_tag or "",
            self.native_capabilities,
        )
        raw = "\x1f".join(parts).encode("utf-8")
        return hashlib.blake2b(raw, digest_size=24).hexdigest()


@dataclass(frozen=True)
class CanonicalMapManifest:
    """Immutable record of one canonical default-branch map build.

    ``storage_root``/``artifact_paths`` describe where the underlying
    artifacts live (content-addressed, outside any single worktree -- see
    ADR-008 section 3); this dataclass itself carries no file-system side
    effects and performs no I/O.
    """

    schema: str
    schema_version: int
    key: CanonicalMapKey
    storage_root: str
    artifact_paths: dict[str, str]
    file_manifest_digest: str
    counts: dict[str, int]
    created_at: str
    builder: dict[str, str]
    generation: int

    def __post_init__(self) -> None:
        _require(self.schema == CANONICAL_MAP_SCHEMA, "schema", self.schema)
        _require(
            self.schema_version == CANONICAL_MAP_SCHEMA_VERSION,
            "schema_version",
            self.schema_version,
        )
        _require(self.generation >= 0, "generation", self.generation)


@dataclass(frozen=True)
class OverlayFileChange:
    """A single file-level delta between a worktree and its canonical base."""

    path: str
    change_type: str
    previous_path: str | None = None
    content_digest: str | None = None

    def __post_init__(self) -> None:
        _require(
            self.change_type in OVERLAY_CHANGE_TYPES,
            "change_type",
            self.change_type,
        )
        if self.change_type == "renamed" and not self.previous_path:
            raise ValueError("OverlayFileChange: 'renamed' requires previous_path")
        if self.change_type == "removed" and self.content_digest is not None:
            raise ValueError("OverlayFileChange: 'removed' must not carry content_digest")


@dataclass(frozen=True)
class WorktreeOverlay:
    """Incremental delta a single worktree computes against a canonical base.

    ``config_fingerprint`` must match ``base_key.config_fingerprint``
    bit-for-bit; a mismatch means this overlay is incompatible with the
    canonical manifest it names and must be rejected by any future consumer
    (Phase-0 only defines the field and the invariant -- no consumer exists
    yet).
    """

    schema: str
    schema_version: int
    base_key: CanonicalMapKey
    worktree_path: str
    worktree_commit_sha: str
    config_fingerprint: str
    changed_files: tuple[OverlayFileChange, ...] = field(default_factory=tuple)
    tombstones: tuple[str, ...] = field(default_factory=tuple)
    dirty: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        _require(self.schema == WORKTREE_OVERLAY_SCHEMA, "schema", self.schema)
        _require(
            self.schema_version == WORKTREE_OVERLAY_SCHEMA_VERSION,
            "schema_version",
            self.schema_version,
        )

    def is_compatible_with_base(self) -> bool:
        """Whether this overlay's config fingerprint matches its base key.

        Pure helper, no I/O. A ``False`` result means the overlay must not
        be composed with the canonical manifest referenced by ``base_key``.
        """
        return self.config_fingerprint == self.base_key.config_fingerprint


@dataclass(frozen=True)
class EffectiveMapDiagnostics:
    """Observability fields the issue requires for every composed view.

    Populated by whatever future code resolves an :class:`EffectiveMapView`;
    this dataclass only defines the shape.
    """

    cache_hit: bool
    single_flight_waited: bool
    files_reused: int
    files_remapped: int
    invalidation_reason: str | None = None


@dataclass(frozen=True)
class EffectiveMapView:
    """Composed, read-only view: canonical manifest plus optional overlay.

    ``overlay`` is ``None`` exactly when the requesting worktree already IS
    the default branch at the canonical commit (no delta to compute). This
    type intentionally holds references, not copies -- composing it must stay
    lazy per the issue's requirement to avoid duplicating the full base map.
    """

    schema: str
    schema_version: int
    canonical: CanonicalMapManifest
    overlay: WorktreeOverlay | None
    diagnostics: EffectiveMapDiagnostics

    def __post_init__(self) -> None:
        _require(self.schema == EFFECTIVE_MAP_VIEW_SCHEMA, "schema", self.schema)
        _require(
            self.schema_version == EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
            "schema_version",
            self.schema_version,
        )
        if self.overlay is not None and not self.overlay.is_compatible_with_base():
            raise ValueError(
                "EffectiveMapView: overlay.config_fingerprint does not match "
                "canonical.key.config_fingerprint"
            )
        if self.overlay is not None and self.overlay.base_key != self.canonical.key:
            raise ValueError(
                "EffectiveMapView: overlay.base_key does not match canonical.key"
            )


def _require(condition: bool, field_name: str, value: object) -> None:
    if not condition:
        raise ValueError(f"invalid {field_name!r}: {value!r}")
