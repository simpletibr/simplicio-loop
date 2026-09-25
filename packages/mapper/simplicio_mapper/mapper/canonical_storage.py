"""Content-addressed storage path resolution (issue #236, ADR-008 step 3, partial).

This module implements *only* the path-computation slice of migration-plan
step 3 from ``.specs/architecture/ADR-008-canonical-map-overlays.md`` section
3 ("Armazenamento content-addressed"): given a resolved common git dir (see
:func:`simplicio_mapper.mapper.canonical_identity.resolve_common_git_dir`)
and a :class:`simplicio_mapper.mapper.canonical.CanonicalMapKey` digest, where
would the canonical manifest / worktree overlay for that key live on disk.

Every function here is pure path arithmetic -- string/``os.path`` composition
only. Nothing here creates directories, writes files, or performs any I/O;
the atomic-promotion write path described in ADR-008 section 5
(``<digest>.tmp-<token>/`` staging directory, ``os.replace`` promotion) is a
later migration step and out of scope for this module. No production code
path calls these functions yet; nothing here is wired into any existing CLI
command.
"""

from __future__ import annotations

import json
import os
import time
import uuid

from simplicio_mapper.mapper.canonical import CanonicalMapKey

#: Documented override for the canonical-map content-addressed cache root
#: (ADR-008 section 3). When unset, the cache root falls back to
#: ``<common_git_dir>/simplicio``.
CANONICAL_CACHE_DIR_ENV_VAR = "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"

_CANONICAL_SUBDIR = "canonical"
_OVERLAYS_SUBDIR = "overlays"
_TMP_INFIX = ".tmp-"


def resolve_canonical_cache_root(common_git_dir: str) -> str:
    """Return the root directory canonical manifests/overlays are stored under.

    Honors the ``SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR`` override (ADR-008
    section 3) when set to a non-empty value; otherwise falls back to
    ``<common_git_dir>/simplicio``, matching the shared, out-of-worktree
    location ``resolve_common_git_dir`` already resolves.
    """
    override = os.environ.get(CANONICAL_CACHE_DIR_ENV_VAR)
    if override:
        return override
    return os.path.join(common_git_dir, "simplicio")


def canonical_manifest_dir(cache_root: str, key_digest: str) -> str:
    """Return the content-addressed directory for a canonical manifest.

    Shape: ``<cache_root>/canonical/<key_digest>/`` (ADR-008 section 3) --
    two worktrees whose :class:`CanonicalMapKey` produce the same digest
    resolve to the same directory with no additional coordination.
    """
    return os.path.join(cache_root, _CANONICAL_SUBDIR, key_digest) + os.sep


def canonical_manifest_tmp_dir(cache_root: str, key_digest: str, token: str) -> str:
    """Return the staging directory a future builder writes to before promotion.

    Shape: ``<cache_root>/canonical/<key_digest>.tmp-<token>/`` (ADR-008
    section 5) -- a sibling of the final :func:`canonical_manifest_dir`
    result so the eventual ``os.replace`` promotion stays on the same
    filesystem. This function only computes the path; it does not create the
    directory or perform the promotion itself.
    """
    return (
        os.path.join(cache_root, _CANONICAL_SUBDIR, f"{key_digest}{_TMP_INFIX}{token}")
        + os.sep
    )


def overlay_dir(cache_root: str, overlay_digest: str) -> str:
    """Return the content-addressed directory for a worktree overlay.

    Shape: ``<cache_root>/overlays/<overlay_digest>/`` (ADR-008 section 3) --
    kept as a sibling subdirectory of ``canonical/``, never nested inside a
    canonical manifest directory, so promoting/GC-ing a canonical manifest
    never has to account for overlay contents.
    """
    return os.path.join(cache_root, _OVERLAYS_SUBDIR, overlay_digest) + os.sep


def canonical_manifest_dir_for_key(cache_root: str, key: CanonicalMapKey) -> str:
    """Compose :func:`canonical_manifest_dir` with ``CanonicalMapKey.digest()``.

    Thin convenience wrapper proving the two Phase-0 modules
    (``mapper.canonical`` and this one) compose end-to-end -- still no I/O.
    """
    return canonical_manifest_dir(cache_root, key.digest())


def canonical_build_lock_path(cache_root: str, key_digest: str) -> str:
    """Return the cross-worktree single-flight lock path for a build of ``key_digest``.

    ADR-008 section 4 originally sketched this path as
    ``<digest>/build.lock`` (i.e. *inside* the eventual manifest directory).
    That shape was deliberately not used here: :func:`canonical_manifest_dir`
    is only ever supposed to exist once fully promoted (the builder's own
    ``if os.path.isdir(digest_dir): ...`` idempotency check treats its mere
    existence as "already promoted" -- see
    ``simplicio_mapper.mapper.canonical_builder``), and ``os.replace`` cannot
    atomically promote a temp directory onto a *non-empty* existing
    directory on every platform this project supports (Windows in
    particular). Putting the lock file inside the digest directory before
    promotion would make that directory non-empty ahead of time and break
    the atomic-promotion invariant the builder already relies on.

    Shape used instead: ``<cache_root>/canonical/<key_digest>.build.lock`` --
    a sibling of :func:`canonical_manifest_dir`'s result (same directory
    ``os.replace`` already promotes into), never a child of it. Two
    worktrees building the same digest resolve to the same lock path with no
    additional coordination, exactly like the manifest directory itself.
    """
    return os.path.join(cache_root, _CANONICAL_SUBDIR, f"{key_digest}.build.lock")


def claim_canonical_build(
    cache_root: str, key_digest: str, owner: str, lease_seconds: float = 300.0
) -> dict[str, object]:
    """Atomically claim one canonical build or return the live follower lease.

    The lock is deliberately outside the promoted generation directory. A
    stale lease is removed only after its expiry, then retried with a fresh
    fencing token; callers must include that token in every promotion.
    """
    lock_path = canonical_build_lock_path(cache_root, key_digest)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    now = time.time()
    payload = {
        "schema": "simplicio.mapper-single-flight/v1",
        "key_digest": key_digest,
        "owner": owner,
        "token": uuid.uuid4().hex,
        "created_at": now,
        "expires_at": now + max(0.01, lease_seconds),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            with open(lock_path, encoding="utf-8") as handle:
                current = json.load(handle)
        except (OSError, ValueError, TypeError):
            return {"role": "follower", "reason": "malformed_lock", "path": lock_path}
        if float(current.get("expires_at", 0)) > now:
            return {"role": "follower", "path": lock_path, "lease": current}
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass
        return claim_canonical_build(cache_root, key_digest, owner, lease_seconds)
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
    return {"role": "owner", "path": lock_path, "lease": payload}


def release_canonical_build(cache_root: str, key_digest: str, token: str) -> bool:
    """Release only the lock carrying the caller's fencing token."""
    lock_path = canonical_build_lock_path(cache_root, key_digest)
    try:
        with open(lock_path, encoding="utf-8") as handle:
            current = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    if current.get("token") != token:
        return False
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        return False
    return True
