"""map_view.py — canonical map + worktree overlay consumption (issue #213).

Goal: a task/agent/retry running in a git worktree should not trigger a
full re-map of the whole project just because it is in a different
worktree (or a different retry of the same run) than the last call —
when a canonical map for the shared repo's current default-branch commit
and a small overlay for this worktree's actual diff already exist and
still match the live git identity, reuse them.

Storage layout:

* **Canonical manifest** — one JSON file per (shared repo, default-branch
  HEAD sha, mapper config fingerprint), stored under the *common* git dir
  (``git rev-parse --git-common-dir``), which is already the one location
  every worktree of a repo shares — exactly the same trick git itself uses
  for the object database. This is what lets N sibling worktrees of the
  same repo reuse one canonical build instead of N redundant ones.
* **Worktree overlay** — one JSON file per (worktree root, merge-base sha,
  dirty fingerprint), stored under that worktree's own git-dir (``git
  rev-parse --git-dir``), since it is specific to that worktree's actual
  working-tree state. Deliberately NOT under ``<root>/.simplicio-loop`` — a file
  written inside the tracked working tree would show up as a new untracked
  file on the very next `git status`, shifting the dirty fingerprint (and
  therefore the overlay path itself) out from under the call that just
  computed it. The same reasoning is why this module logs via `info()`
  rather than `emit_event(..., root=...)`, which would append to
  `<root>/.simplicio-loop/events.jsonl` inside the tree on every call.

Neither file is ever trusted blindly: ``CanonicalMapManifest.matches``/
``WorktreeOverlay.matches`` re-check the live git identity every call, so a
stale manifest (branch switched, rebase happened, file went dirty) is
silently rejected — but the rebuild/fallback that follows is always logged
(issue #213 AC: "Recusar silenciosamente mapas incompatíveis; rebuild/
fallback deve ser explícito e registrado").

Scope note: this repo has no network client for an external "Map Service"
(the Simplicio Loop Hub referenced in the issue lives in a different
package/repo). What is implemented here is the **standalone fallback**
half of the issue's plan — "Implementar fallback standalone usando os
mesmos contratos" — using the exact same ``CanonicalMapManifest``/
``WorktreeOverlay``/``EffectiveMapView`` contracts a future Hub client
integration would reuse. See ADR-005 for the full scoping rationale.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mapper import MAPPER_BIN, artifact_status
from .observability import info
from .utils.serialization import dumps, loads

SCHEMA_CANONICAL = "simplicio.canonical-map-manifest/v1"
SCHEMA_OVERLAY = "simplicio.worktree-overlay/v1"
SCHEMA_VIEW = "simplicio.effective-map-view/v1"

SOURCE_CANONICAL_OVERLAY_HIT = "canonical_overlay_hit"
SOURCE_FULL_REMAP = "full_remap"
SOURCE_FALLBACK_STANDALONE = "fallback_standalone"


_SPAWN_RETRIES = 2


def _run_git(root: str | os.PathLike[str], *args: str, timeout: float = 10) -> str | None:
    """Run `git <args>` in `root`, returning stripped stdout or None.

    A non-zero exit (not a repo, unknown ref, ...) returns None immediately
    — that is a legitimate answer. An `OSError` raised by the *spawn* itself
    (e.g. a transient Windows handle-table failure under heavy concurrent
    subprocess use) is retried a bounded number of times before giving up:
    treating a transient spawn failure as "not a git repo" would silently
    fall back to `fallback_standalone`/force a full remap on an otherwise
    healthy repo, which is exactly the false negative issue #213's
    "recusar silenciosamente" guardrail is meant to prevent.
    """
    last_error: OSError | None = None
    for _attempt in range(_SPAWN_RETRIES + 1):
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.SubprocessError:
            return None
        except OSError as exc:
            last_error = exc
            continue
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()
    del last_error  # exhausted retries — fail open like any other None case
    return None


def _dirty_fingerprint(root: str | os.PathLike[str]) -> str:
    status = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status is None:
        return ""
    return hashlib.sha256(status.encode("utf-8")).hexdigest()[:16]


def _mapper_config_fingerprint() -> str:
    """A coarse "did the mapper toolchain itself change" signal.

    No mapper config file convention exists in this repo yet, so the
    installed `simplicio-mapper` version string stands in for it: a mapper
    upgrade invalidates a canonical manifest built under the old version.
    """
    exe = shutil.which(MAPPER_BIN)
    if not exe:
        return ""
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _resolve_default_branch(root: str | os.PathLike[str], head_sha: str | None) -> str | None:
    if head_sha is None:
        return None
    ref = _run_git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref
    for candidate in ("origin/main", "origin/master", "main", "master"):
        if _run_git(root, "rev-parse", "--verify", "-q", candidate) is not None:
            return candidate
    return None  # single-branch / no-remote repo: HEAD is its own baseline


@dataclass(frozen=True)
class GitIdentity:
    """The live coordinates a canonical/overlay manifest is checked against."""

    root: Path
    common_dir: Path | None
    git_dir: Path | None
    head_sha: str | None
    default_branch: str | None
    merge_base_sha: str | None
    dirty_fingerprint: str
    mapper_config_fingerprint: str

    @property
    def is_git_repo(self) -> bool:
        return self.head_sha is not None


def resolve_git_identity(root: str | os.PathLike[str]) -> GitIdentity:
    base = Path(root).resolve()
    head_sha = _run_git(base, "rev-parse", "HEAD")
    common_dir_raw = _run_git(base, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common_dir = Path(common_dir_raw).resolve() if common_dir_raw else None
    git_dir_raw = _run_git(base, "rev-parse", "--path-format=absolute", "--git-dir")
    git_dir = Path(git_dir_raw).resolve() if git_dir_raw else None
    default_branch = _resolve_default_branch(base, head_sha)
    merge_base_sha: str | None = None
    if head_sha and default_branch:
        merge_base_sha = _run_git(base, "merge-base", "HEAD", default_branch)
    elif head_sha:
        merge_base_sha = head_sha
    return GitIdentity(
        root=base,
        common_dir=common_dir,
        git_dir=git_dir,
        head_sha=head_sha,
        default_branch=default_branch,
        merge_base_sha=merge_base_sha,
        dirty_fingerprint=_dirty_fingerprint(base) if head_sha else "",
        mapper_config_fingerprint=_mapper_config_fingerprint(),
    )


def _changed_files_since(root: str | os.PathLike[str], merge_base_sha: str | None) -> list[str]:
    if not merge_base_sha:
        return []
    out = _run_git(root, "diff", "--name-only", merge_base_sha)
    return [line for line in (out or "").splitlines() if line]


def _safe_load(path: Path) -> dict[str, Any] | None:
    try:
        data = loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class CanonicalMapManifest:
    """The shared-repo, default-branch-HEAD-keyed map (issue #213 contract)."""

    schema: str
    common_dir: str
    head_sha: str
    mapper_config_fingerprint: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    built_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "common_dir": self.common_dir,
            "head_sha": self.head_sha,
            "mapper_config_fingerprint": self.mapper_config_fingerprint,
            "artifacts": self.artifacts,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalMapManifest:
        raw_artifacts = data.get("artifacts")
        artifacts: dict[str, Any] = raw_artifacts if isinstance(raw_artifacts, dict) else {}
        return cls(
            schema=str(data.get("schema", SCHEMA_CANONICAL)),
            common_dir=str(data.get("common_dir", "")),
            head_sha=str(data.get("head_sha", "")),
            mapper_config_fingerprint=str(data.get("mapper_config_fingerprint", "")),
            artifacts=artifacts,
            built_at=float(data.get("built_at", 0.0) or 0.0),
        )

    def matches(self, identity: GitIdentity) -> bool:
        return (
            identity.common_dir is not None
            and self.common_dir == str(identity.common_dir)
            and identity.head_sha is not None
            and self.head_sha == identity.head_sha
            and self.mapper_config_fingerprint == identity.mapper_config_fingerprint
        )


@dataclass(frozen=True)
class WorktreeOverlay:
    """The worktree-specific delta on top of the canonical manifest."""

    schema: str
    worktree_root: str
    merge_base_sha: str
    dirty_fingerprint: str
    changed_files: list[str] = field(default_factory=list)
    built_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "worktree_root": self.worktree_root,
            "merge_base_sha": self.merge_base_sha,
            "dirty_fingerprint": self.dirty_fingerprint,
            "changed_files": self.changed_files,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorktreeOverlay:
        changed = data.get("changed_files")
        return cls(
            schema=str(data.get("schema", SCHEMA_OVERLAY)),
            worktree_root=str(data.get("worktree_root", "")),
            merge_base_sha=str(data.get("merge_base_sha", "")),
            dirty_fingerprint=str(data.get("dirty_fingerprint", "")),
            changed_files=[str(item) for item in changed] if isinstance(changed, list) else [],
            built_at=float(data.get("built_at", 0.0) or 0.0),
        )

    def matches(self, identity: GitIdentity) -> bool:
        return (
            self.worktree_root == str(identity.root)
            and identity.merge_base_sha is not None
            and self.merge_base_sha == identity.merge_base_sha
            and self.dirty_fingerprint == identity.dirty_fingerprint
        )


@dataclass(frozen=True)
class EffectiveMapView:
    """What a caller actually consumes: canonical + overlay, or a fallback."""

    schema: str
    root: str
    snapshot_id: str
    source: str
    canonical: CanonicalMapManifest | None
    overlay: WorktreeOverlay | None
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_receipt(self) -> dict[str, Any]:
        """The propagatable identity — prompts/task contracts/reports embed
        this (issue #213 AC: "Propagar map snapshot ID em prompts, task
        contracts, receipts e reports")."""
        return {
            "schema": self.schema,
            "root": self.root,
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "canonical_hit": self.canonical is not None,
            "overlay_hit": self.overlay is not None,
        }


def _snapshot_id(head_sha: str, dirty_fingerprint: str) -> str:
    return hashlib.sha256(f"{head_sha}:{dirty_fingerprint}".encode()).hexdigest()[:16]


def _canonical_path(identity: GitIdentity) -> Path | None:
    if identity.common_dir is None or not identity.head_sha:
        return None
    return identity.common_dir / "simplicio-canonical-map" / f"{identity.head_sha}.json"


def _overlay_path(identity: GitIdentity) -> Path | None:
    """Where this worktree's overlay manifest lives.

    Stored under the worktree's own git-dir (``git rev-parse --git-dir``,
    e.g. ``.git`` for the main worktree or ``.git/worktrees/<name>`` for a
    linked one) rather than under ``<root>/.simplicio-loop`` — writing it inside
    the tracked working tree would show up as a new untracked file on the
    next `git status`, changing `dirty_fingerprint` (and therefore
    `snapshot_id`) on every subsequent call and defeating the whole point
    of a stable, reusable fingerprint.
    """
    if identity.git_dir is None:
        return None
    merge_base = identity.merge_base_sha or "nogit"
    dirty = identity.dirty_fingerprint or "clean"
    return identity.git_dir / "simplicio-worktree-overlay" / f"{merge_base}-{dirty}.json"


# Process-lifetime reuse of the SAME view across retries of one run (issue
# #213 AC: "Reutilizar o mesmo view handle durante todo o run/retry") —
# keyed by the full live identity tuple so a genuine identity change (branch
# switch, new dirty state) still resolves a fresh view instead of serving a
# now-wrong one.
_VIEW_CACHE: dict[tuple[str, ...], EffectiveMapView] = {}


def _cache_key(identity: GitIdentity) -> tuple[str, ...]:
    return (
        str(identity.common_dir) if identity.common_dir else str(identity.root),
        identity.head_sha or "",
        identity.merge_base_sha or "",
        identity.dirty_fingerprint,
        identity.mapper_config_fingerprint,
    )


def clear_view_cache() -> None:
    """Test/CLI hook — drop the process-level view cache."""
    _VIEW_CACHE.clear()


def get_effective_map_view(root: str | os.PathLike[str], *, force_remap: bool = False) -> EffectiveMapView:
    """Resolve the EffectiveMapView for `root`, reusing a matching canonical
    manifest + worktree overlay from disk when the live git identity still
    matches them — this is the "no redundant full remap" path (issue #213).
    """
    root_path = Path(root).resolve()
    # Mapper inspection may materialize its own cache under ``.simplicio-loop``.
    # Resolve that state before fingerprinting the worktree, otherwise the
    # cache write changes ``git status`` after the overlay path is chosen and
    # makes the just-created overlay unreachable on the next call.
    artifacts = artifact_status(root_path)
    identity = resolve_git_identity(root_path)
    cache_key = _cache_key(identity)
    if not force_remap and cache_key in _VIEW_CACHE:
        return _VIEW_CACHE[cache_key]

    canonical: CanonicalMapManifest | None = None
    overlay: WorktreeOverlay | None = None
    canonical_path = _canonical_path(identity)

    if not force_remap and canonical_path is not None and canonical_path.exists():
        data = _safe_load(canonical_path)
        if data is not None:
            candidate = CanonicalMapManifest.from_dict(data)
            if candidate.matches(identity):
                canonical = candidate

    overlay_path = _overlay_path(identity)
    if not force_remap and overlay_path is not None and overlay_path.exists():
        data = _safe_load(overlay_path)
        if data is not None:
            overlay_candidate = WorktreeOverlay.from_dict(data)
            if overlay_candidate.matches(identity):
                overlay = overlay_candidate

    if canonical is not None and overlay is not None:
        source = SOURCE_CANONICAL_OVERLAY_HIT
    else:
        # Missing or stale manifest(s) — rebuild whichever half is absent.
        # Always logged: a silently-accepted incompatible manifest is
        # exactly what issue #213 forbids, but the rebuild itself must be
        # explicit (issue #213 AC).
        if canonical is None and canonical_path is not None:
            canonical = CanonicalMapManifest(
                schema=SCHEMA_CANONICAL,
                common_dir=str(identity.common_dir),
                head_sha=identity.head_sha or "",
                mapper_config_fingerprint=identity.mapper_config_fingerprint,
                artifacts=artifacts,
                built_at=time.time(),
            )
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_bytes(dumps(canonical.to_dict(), indent=True))
        if overlay is None:
            overlay = WorktreeOverlay(
                schema=SCHEMA_OVERLAY,
                worktree_root=str(identity.root),
                merge_base_sha=identity.merge_base_sha or "",
                dirty_fingerprint=identity.dirty_fingerprint,
                changed_files=_changed_files_since(identity.root, identity.merge_base_sha),
                built_at=time.time(),
            )
            if overlay_path is not None:
                overlay_path.parent.mkdir(parents=True, exist_ok=True)
                overlay_path.write_bytes(dumps(overlay.to_dict(), indent=True))
        source = SOURCE_FULL_REMAP if identity.is_git_repo else SOURCE_FALLBACK_STANDALONE

    # Deliberately `info()` (stderr only), not `emit_event(..., root=...)`:
    # the latter would append to `<root>/.simplicio-loop/events.jsonl` *inside
    # the working tree on every call*, making the tree itself newly dirty
    # and shifting `dirty_fingerprint` (and therefore `snapshot_id` and the
    # overlay path) out from under the very call that just computed it —
    # silently defeating the reuse this module exists to provide.
    info(f"map_view_resolved source={source} root={identity.root}")

    view = EffectiveMapView(
        schema=SCHEMA_VIEW,
        root=str(identity.root),
        snapshot_id=_snapshot_id(identity.head_sha or "", identity.dirty_fingerprint),
        source=source,
        canonical=canonical,
        overlay=overlay,
        artifacts=artifacts,
    )
    _VIEW_CACHE[cache_key] = view
    return view


def doctor_map_view_status(root: str | os.PathLike[str]) -> dict[str, Any]:
    """`simplicio-py doctor` hook — canonical/overlay hit state + changed
    files + fallback reason, per issue #213's doctor/status AC."""
    view = get_effective_map_view(root)
    receipt = view.to_receipt()
    receipt["schema"] = "simplicio.map-view-status/v1"  # override the embedded view schema
    receipt["changed_files"] = view.overlay.changed_files if view.overlay else []
    return receipt
