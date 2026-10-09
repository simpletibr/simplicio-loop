"""Compute a :class:`WorktreeOverlay` delta (ADR-008 migration-plan step 4, issue #236).

This module implements *only* migration-plan step 4 from
``.specs/architecture/ADR-008-canonical-map-overlays.md``: computing the
incremental delta between a worktree's current state (working tree,
including staged/unstaged/untracked changes) and a canonical
:class:`~simplicio_mapper.mapper.canonical.CanonicalMapKey`'s base commit.

Two git passes are composed into one final change set, both relative to the
canonical base commit:

1. The *committed* delta between ``base_key.commit_sha`` and the worktree's
   current ``HEAD`` -- ``git diff --name-status -M <base_sha> <head_sha>``.
2. The *uncommitted* delta on top of ``HEAD`` -- staged, unstaged and
   untracked changes via ``git status --porcelain --untracked-files=all``
   (same invocation shape as :func:`simplicio_mapper.mapper.parse._git_status_map`,
   kept independent here since this module has its own merge/chaining needs).

Both passes are merged into a single set of :class:`OverlayFileChange`
entries expressed relative to the canonical base -- e.g. a file renamed by a
commit and then further edited by an unstaged change still resolves to one
``renamed`` entry with ``previous_path`` pointing at the name it had in the
canonical base, not at the intermediate post-commit name.

Nothing here is wired into the existing index/scan pipeline or into
``mapper.canonical`` construction beyond returning the schema's own
dataclasses -- no production code path calls
:func:`compute_worktree_overlay` yet. See the ADR's migration plan, step 5+,
for the follow-up that composes this into an
:class:`~simplicio_mapper.mapper.canonical.EffectiveMapView`.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time

from .canonical import (
    WORKTREE_OVERLAY_SCHEMA,
    WORKTREE_OVERLAY_SCHEMA_VERSION,
    CanonicalMapKey,
    OverlayFileChange,
    WorktreeOverlay,
)

_GIT_TIMEOUT_SECONDS = 15.0

#: git status/diff rename-detection threshold, applied identically to both
#: the committed (``git diff``) and uncommitted (``git status``) passes so a
#: rename detected in one pass is never reported differently than the other.
_RENAME_DETECTION = "-M"


def _run_git(
    args: list[str], cwd: str, timeout: float = _GIT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess | None:
    """Run a read-only ``git`` subprocess, or ``None`` on any spawn/timeout failure.

    Mirrors the error-handling shape of
    ``canonical_identity._run_git``/``_index_engine._git_signature``: only
    OS-level spawn failures and timeouts collapse to ``None`` here, a
    non-zero exit code is still returned so callers can distinguish "git
    ran and said no" from "git could not run at all".
    """
    try:
        return subprocess.run(
            # quotepath=false: report non-ASCII names as they are on disk (issue #1574), otherwise
            # a changed file named "módulo.py" arrives as "m\303\263dulo.py" and is never matched.
            ["git", "-c", "core.quotepath=false", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _norm(path: str) -> str:
    """Normalize a git-reported path to forward slashes, no leading ``./``."""
    value = path.strip().strip('"')
    value = value.replace("\\", "/")
    return value[2:] if value.startswith("./") else value


def _resolve_head_commit_sha(root: str) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], root)
    if not result or result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _parse_name_status(output: str) -> list[tuple[str, str | None, str]] | None:
    """Parse ``git diff --name-status`` output into ``(kind, from_path, to_path)``.

    ``from_path`` is only populated for ``renamed`` entries (the previous
    name); ``added``/``modified``/``removed`` carry ``None`` there since the
    caller resolves the effective origin from cumulative merge state, not
    from this single hop in isolation.
    """
    entries: list[tuple[str, str | None, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0]
        if code.startswith("R"):
            if len(parts) < 3:
                continue
            entries.append(("renamed", _norm(parts[1]), _norm(parts[2])))
        elif code.startswith("C"):
            # Copies have no prior path to tombstone; treat the destination
            # as a fresh addition relative to the base.
            if len(parts) < 3:
                continue
            entries.append(("added", None, _norm(parts[2])))
        elif code.startswith("A"):
            entries.append(("added", None, _norm(parts[1])))
        elif code.startswith("D"):
            entries.append(("removed", None, _norm(parts[1])))
        else:
            entries.append(("modified", None, _norm(parts[1])))
    return entries


def _committed_delta(
    root: str, base_sha: str, head_sha: str
) -> list[tuple[str, str | None, str]] | None:
    """Return ``base_sha``..``head_sha`` committed changes, or ``None`` on failure."""
    if base_sha == head_sha:
        return []
    result = _run_git(
        ["diff", "--name-status", _RENAME_DETECTION, base_sha, head_sha, "--"],
        root,
    )
    if not result or result.returncode != 0:
        return None
    return _parse_name_status(result.stdout)


def _parse_status_porcelain(output: str) -> list[tuple[str, str | None, str]]:
    """Parse ``git status --porcelain`` lines into ``(kind, from_path, to_path)``.

    Classification priority when both index and worktree characters are set
    (e.g. ``"AD"``, ``"MM"``) is deletion > rename > addition > modification
    -- the on-disk absence/rename of a file is the fact that matters for an
    overlay, regardless of what the index says happened along the way.
    """
    entries: list[tuple[str, str | None, str]] = []
    for line in output.split("\n"):
        if not line.strip():
            continue
        code = line[:2]
        raw = line[3:].strip()
        if " -> " in raw:
            from_raw, to_raw = raw.split(" -> ", 1)
            from_path, to_path = _norm(from_raw), _norm(to_raw)
        else:
            from_path, to_path = None, _norm(raw)
        if "D" in code:
            entries.append(("removed", None, to_path))
        elif "R" in code:
            entries.append(("renamed", from_path or to_path, to_path))
        elif code == "??" or "A" in code:
            entries.append(("added", None, to_path))
        else:
            entries.append(("modified", None, to_path))
    return entries


def _uncommitted_delta(root: str) -> tuple[list[tuple[str, str | None, str]], bool] | None:
    """Return (entries, dirty) from ``git status --porcelain``, or ``None`` on failure."""
    result = _run_git(["status", "--porcelain", "--untracked-files=all"], root)
    if not result or result.returncode != 0:
        return None
    dirty = bool(result.stdout.strip())
    return _parse_status_porcelain(result.stdout), dirty


def _apply_hop(
    state: dict[str, str | None],
    tombstones: set[str],
    kind: str,
    from_key: str | None,
    to_key: str,
) -> None:
    """Fold one hop's ``(kind, from_key, to_key)`` change into cumulative state.

    ``state`` maps a *current* path to its origin path relative to the
    canonical base (``None`` means "no origin -- brand new since base").
    ``tombstones`` holds base-relative paths known to be gone. Both are
    mutated in place so a second hop (uncommitted changes) can chain
    correctly on top of a first hop (committed changes) -- e.g. a rename
    followed by a further rename still resolves to one ``renamed`` entry
    against the original base path.
    """
    if kind == "added":
        if to_key in tombstones:
            tombstones.discard(to_key)
            state[to_key] = to_key
        elif to_key not in state:
            state[to_key] = None
    elif kind == "modified":
        if to_key in state:
            return
        if to_key in tombstones:
            tombstones.discard(to_key)
        state[to_key] = to_key
    elif kind == "removed":
        if to_key in state:
            origin = state.pop(to_key)
            if origin is not None:
                tombstones.add(origin)
        elif to_key not in tombstones:
            tombstones.add(to_key)
    elif kind == "renamed":
        source = from_key or to_key
        if source in state:
            origin = state.pop(source)
        elif source in tombstones:
            tombstones.discard(source)
            origin = source
        else:
            origin = source
        if origin is None:
            state[to_key] = None
        elif origin == to_key:
            state.pop(to_key, None)
        else:
            state[to_key] = origin


def _content_digest(root: str, rel_path: str) -> str | None:
    """Return a blake2b digest of ``rel_path``'s current on-disk content.

    Same hash family as :meth:`CanonicalMapKey.digest`/``FileProcessingCache``
    elsewhere in this package. Returns ``None`` when the file cannot be read
    (e.g. a race between the git scan and the caller) rather than raising --
    an overlay entry with a missing digest is still useful, a crash is not.
    """
    abs_path = os.path.join(root, rel_path)
    try:
        with open(abs_path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    return hashlib.blake2b(data, digest_size=24).hexdigest()


def compute_worktree_overlay(
    worktree_root: str, base_key: CanonicalMapKey, config_fingerprint: str
) -> WorktreeOverlay | None:
    """Compute the :class:`WorktreeOverlay` for ``worktree_root`` against ``base_key``.

    Returns ``None`` (fail-closed, matches
    ``canonical_identity.resolve_repo_identity_bundle``'s contract) whenever
    any git step fails to run cleanly -- not a git repository, the base
    commit is missing/unreachable, or any subprocess spawn/timeout error.
    Never returns a partially-populated overlay.
    """
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], worktree_root)
    if not inside or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None

    head_sha = _resolve_head_commit_sha(worktree_root)
    if not head_sha:
        return None

    committed = _committed_delta(worktree_root, base_key.commit_sha, head_sha)
    if committed is None:
        return None

    uncommitted_result = _uncommitted_delta(worktree_root)
    if uncommitted_result is None:
        return None
    uncommitted, dirty = uncommitted_result

    state: dict[str, str | None] = {}
    tombstones: set[str] = set()
    for kind, from_key, to_key in committed:
        _apply_hop(state, tombstones, kind, from_key, to_key)
    for kind, from_key, to_key in uncommitted:
        _apply_hop(state, tombstones, kind, from_key, to_key)

    changed_files: list[OverlayFileChange] = []
    # ``tombstones`` per the schema docstring covers *both* removed paths and
    # the previous name of a renamed path -- either way, the base-relative
    # path no longer resolves to that name in the current tree.
    all_tombstones = set(tombstones)
    for path, origin in state.items():
        if origin is None:
            changed_files.append(
                OverlayFileChange(
                    path=path,
                    change_type="added",
                    content_digest=_content_digest(worktree_root, path),
                )
            )
        elif origin == path:
            changed_files.append(
                OverlayFileChange(
                    path=path,
                    change_type="modified",
                    content_digest=_content_digest(worktree_root, path),
                )
            )
        else:
            changed_files.append(
                OverlayFileChange(
                    path=path,
                    change_type="renamed",
                    previous_path=origin,
                    content_digest=_content_digest(worktree_root, path),
                )
            )
            all_tombstones.add(origin)

    tombstone_paths = tuple(sorted(all_tombstones))
    for path in sorted(tombstones):
        changed_files.append(OverlayFileChange(path=path, change_type="removed"))
    changed_files.sort(key=lambda change: change.path)

    return WorktreeOverlay(
        schema=WORKTREE_OVERLAY_SCHEMA,
        schema_version=WORKTREE_OVERLAY_SCHEMA_VERSION,
        base_key=base_key,
        worktree_path=os.path.abspath(worktree_root),
        worktree_commit_sha=head_sha,
        config_fingerprint=config_fingerprint,
        changed_files=tuple(changed_files),
        tombstones=tombstone_paths,
        dirty=dirty,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
