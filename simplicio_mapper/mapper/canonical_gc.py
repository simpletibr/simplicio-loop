"""Conservative, crash-safe GC for canonical-map content-addressed snapshots.

Issue #268 (parent #263, epic #236). Scans the canonical-map storage root
(ADR-008 section 3, :mod:`simplicio_mapper.mapper.canonical_storage`) for:

* interrupted-promotion temp directories (``<digest>.tmp-<token>/``, written
  by :func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest`
  before its atomic ``os.replace`` promotion) whose builder process is
  provably dead, and
* promoted manifest directories (``<digest>/manifest.json``) that no longer
  match the CURRENT default-branch commit for the repo at the given path.

Never removes anything without a "provably dead" (or "provably stale, past
grace + TTL") reason, reusing the SAME liveness primitives already
battle-tested in ``simplicio_mapper.cli._index_engine``'s lock-reclaim logic
(:mod:`simplicio_mapper.mapper.process_liveness`) rather than inventing a new
mechanism.

Honest heuristic disclosure (issue #268 explicitly asks for this instead of
overclaiming precision): there is no cross-worktree registry of "currently
referenced" canonical digests yet -- ADR-008's migration plan has not reached
that step. A promoted manifest is therefore treated as "live" only when its
key's ``(repo_identity, default_branch, commit_sha)`` matches the CURRENT
default-branch commit resolved from the ``root`` path passed to
``canonical gc``. Any other promoted manifest is a GC candidate once it
clears the grace window and the TTL below -- this is a conservative
approximation of "unreferenced by every worktree", not a proof of it, and
every :class:`GcReport` this module produces documents the reason per item
so the approximation is never silently overclaimed as precise.

Crash-safety of the removal step itself: a candidate directory is never
handed straight to ``shutil.rmtree`` on its live name. It is first
atomically renamed (``os.replace``, a single filesystem operation) to a
sibling ``<name>.deleting-<token>`` name, then recursively deleted. On
POSIX, a process that already has a file open inside the directory keeps a
valid file descriptor even after the containing directory is renamed out
from under it, so a concurrent reader never observes a torn read -- only
"the digest doesn't exist under its original name anymore" if it looks
again afterward. If the process crashes between the rename and the
``rmtree``, the next GC invocation finds the leftover ``.deleting-``
directory and (being a name only this module's removal path ever writes)
always finishes removing it unconditionally, regardless of age -- this is
what makes the removal step crash-safe rather than merely "safe when it
runs to completion". On Windows, ``os.replace`` on a directory another
process holds open files under can fail with ``PermissionError`` (no
POSIX-style "rename over open handles" guarantee); this is treated as a
fail-closed, retryable condition -- the candidate is left untouched and
reported as an error for that entry, picked up again on the next GC run.

Nothing here is wired into any existing CLI command besides
``simplicio-mapper canonical gc`` (``simplicio_mapper/cli/_canonical.py``).
"""

from __future__ import annotations

import os
import secrets
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import orjson

from .canonical_identity import ResolvedRepoIdentity, resolve_repo_identity_bundle
from .canonical_storage import CANONICAL_CACHE_DIR_ENV_VAR, resolve_canonical_cache_root
from .process_liveness import process_is_alive, process_start_token

CANONICAL_GC_SCHEMA = "simplicio.canonical-gc/v1"
CANONICAL_GC_SCHEMA_VERSION = 1

#: Never touch anything (tmp dir or promoted manifest) whose last activity is
#: more recent than this many seconds -- avoids racing a build that JUST
#: finished its atomic promotion (issue #268 requirement #2).
GC_GRACE_SECONDS_ENV = "SIMPLICIO_MAPPER_CANONICAL_GC_GRACE_SECONDS"
DEFAULT_GC_GRACE_SECONDS = 60.0

#: TTL a promoted manifest that is no longer the current default-branch
#: commit must clear before it becomes a removal candidate -- mirrors the
#: ``SIMPLICIO_MAPPER_LOCK_TTL_SECONDS`` env-var pattern used by the index
#: lock (``simplicio_mapper.cli._index_engine.INDEX_LOCK_TTL_ENV``), applied
#: here to canonical snapshots instead of locks.
GC_TTL_SECONDS_ENV = "SIMPLICIO_MAPPER_CANONICAL_GC_TTL_SECONDS"
DEFAULT_GC_TTL_SECONDS = float(7 * 24 * 60 * 60)  # 7 days

_TMP_INFIX = ".tmp-"
_DELETING_INFIX = ".deleting-"
_MANIFEST_FILE_NAME = "manifest.json"
#: Not written by any production code path yet (``canonical_builder.py``
#: does not create a companion lock next to its tmp dir today) -- this is
#: forward-compatible detection only, per ADR-008 section 4's plan to
#: generalize the index-lock machinery to a ``canonical-build`` operation.
#: When absent (the current, common case) the temp-dir's own
#: ``<digest>.tmp-<token>`` name -- whose token is the builder's own PID,
#: see ``canonical_builder.build_canonical_manifest`` -- is the liveness
#: signal instead (see :func:`_classify_temp_dir`).
_BUILD_LOCK_FILE_NAME = "build.lock"


def _read_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return float(default)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(default)


def _grace_seconds(override: float | None = None) -> float:
    if override is not None:
        return max(0.0, float(override))
    return _read_float_env(GC_GRACE_SECONDS_ENV, DEFAULT_GC_GRACE_SECONDS)


def _ttl_seconds(override: float | None = None) -> float:
    if override is not None:
        return max(0.0, float(override))
    return _read_float_env(GC_TTL_SECONDS_ENV, DEFAULT_GC_TTL_SECONDS)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        parsed = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _relativize(path: str, base: str) -> str:
    return os.path.relpath(path, base).replace(os.sep, "/")


def _dir_last_activity(path: str) -> float:
    """Latest mtime of ``path`` or anything inside it -- "last write" proxy.

    Never raises: an unreadable entry contributes nothing and the directory's
    own mtime is always included as a floor.
    """
    try:
        latest = os.stat(path).st_mtime
    except OSError:
        latest = 0.0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                latest = max(latest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return latest


def _parse_pid(token: str) -> int | None:
    try:
        pid = int(token)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _age_from_iso(value: str, now: float) -> float | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return max(0.0, now - parsed.timestamp())


def _classify_lock_record(record: dict) -> str:
    """Mirror ``_index_engine._inspect_index_lock``'s dead/live/pid_reused bar.

    Only used when a ``build.lock`` file is actually present (see module
    docstring -- no production writer exists yet, this is forward-compat).
    """
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return "malformed"
    if not process_is_alive(pid):
        return "dead"
    expected_start = record.get("process_start_identity")
    if isinstance(expected_start, str) and expected_start not in ("", "unknown"):
        actual_start = process_start_token(pid)
        if actual_start is not None and actual_start != expected_start:
            return "pid_reused"
    return "live"


@dataclass(frozen=True)
class GcCandidate:
    """One scanned item -- a temp dir, a ``.deleting-`` leftover, or a promoted manifest dir.

    ``relative_path`` is always relative to the canonical cache root -- never
    an absolute filesystem path (issue #268 requirement #6: no absolute paths
    or remote URLs leaked into the receipt).
    """

    relative_path: str
    kind: str  # "temp_dir" | "manifest_dir" | "deleting_leftover"
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {"path": self.relative_path, "kind": self.kind, "reason": self.reason}
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass(frozen=True)
class GcReport:
    """Versioned receipt for one ``canonical gc`` invocation."""

    schema: str
    schema_version: int
    apply: bool
    candidates: list[GcCandidate]
    removed: list[GcCandidate]
    recovered: list[GcCandidate]
    preserved: list[GcCandidate]
    errors: list[str]

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "apply": self.apply,
            "candidates": [c.to_dict() for c in self.candidates],
            "removed": [c.to_dict() for c in self.removed],
            "recovered": [c.to_dict() for c in self.recovered],
            "preserved": [c.to_dict() for c in self.preserved],
            "errors": list(self.errors),
        }


def _empty_report(apply: bool, errors: list[str]) -> GcReport:
    return GcReport(
        schema=CANONICAL_GC_SCHEMA,
        schema_version=CANONICAL_GC_SCHEMA_VERSION,
        apply=apply,
        candidates=[],
        removed=[],
        recovered=[],
        preserved=[],
        errors=errors,
    )


def _classify_deleting_leftover(rel: str) -> GcCandidate:
    # A `.deleting-` name is written only by `_reclaim`'s own removal path,
    # immediately before an unconditional `rmtree`. Nothing else ever reads
    # or writes it, so finding one always means a prior GC `--apply` run (or
    # the builder, which never uses this infix) crashed mid-delete -- always
    # safe to finish, regardless of age or any PID embedded in the name.
    return GcCandidate(rel, "deleting_leftover", "crash_leftover_deleting", {})


def _classify_temp_dir(
    entry_path: str, entry_name: str, rel: str, now: float, *, grace_seconds: float
) -> tuple[GcCandidate, bool]:
    """Classify a ``<digest>.tmp-<token>`` interrupted-promotion directory.

    Returns ``(candidate, is_gc_candidate)`` -- ``is_gc_candidate`` is
    ``False`` whenever the directory could still belong to a live/in-progress
    build, per the "never guess-remove based on directory age alone"
    requirement.
    """
    _, _, token = entry_name.partition(_TMP_INFIX)
    age = max(0.0, now - _dir_last_activity(entry_path))

    lock_record = _read_json(os.path.join(entry_path, _BUILD_LOCK_FILE_NAME))
    if lock_record is not None:
        verdict = _classify_lock_record(lock_record)
        if verdict == "live":
            return (
                GcCandidate(rel, "temp_dir", "temp_dir_build_lock_live", {"token": token}),
                False,
            )
        if verdict == "malformed" and age < grace_seconds:
            return (
                GcCandidate(
                    rel, "temp_dir", "temp_dir_build_lock_malformed_within_grace", {"token": token}
                ),
                False,
            )
        return (
            GcCandidate(
                rel,
                "temp_dir",
                f"temp_dir_build_lock_{verdict}",
                {"token": token, "age_seconds": round(age, 3)},
            ),
            True,
        )

    # No companion lock file (the common case today -- see module docstring)
    # -- fall back to the pid embedded in the tmp-dir's own name
    # (`canonical_builder.build_canonical_manifest` names it
    # `str(os.getpid())`) plus the same `process_is_alive` primitive the
    # index lock uses. A live builder PID is never reclaimed regardless of
    # age; a dead/unparseable one still gets a grace window before removal
    # to avoid racing a promotion that finished moments ago.
    pid = _parse_pid(token)
    if pid is not None and process_is_alive(pid):
        return GcCandidate(rel, "temp_dir", "temp_dir_builder_pid_alive", {"pid": pid}), False
    if age < grace_seconds:
        return (
            GcCandidate(rel, "temp_dir", "temp_dir_within_grace_window", {"age_seconds": round(age, 3)}),
            False,
        )
    reason = "temp_dir_builder_pid_dead" if pid is not None else "temp_dir_token_unparseable_stale"
    detail: dict[str, Any] = {"age_seconds": round(age, 3)}
    if pid is not None:
        detail["pid"] = pid
    return GcCandidate(rel, "temp_dir", reason, detail), True


def _classify_manifest_dir(
    entry_path: str,
    rel: str,
    identity: ResolvedRepoIdentity | None,
    now: float,
    *,
    grace_seconds: float,
    ttl_seconds: float,
) -> tuple[GcCandidate, bool]:
    """Classify a promoted ``<digest>/manifest.json`` directory."""
    raw = _read_json(os.path.join(entry_path, _MANIFEST_FILE_NAME))
    dir_age = max(0.0, now - _dir_last_activity(entry_path))

    if raw is None:
        if dir_age < grace_seconds:
            return (
                GcCandidate(
                    rel, "manifest_dir", "manifest_missing_within_grace", {"age_seconds": round(dir_age, 3)}
                ),
                False,
            )
        return (
            GcCandidate(
                rel, "manifest_dir", "manifest_missing_or_corrupt", {"age_seconds": round(dir_age, 3)}
            ),
            True,
        )

    key_raw = raw.get("key") if isinstance(raw.get("key"), dict) else {}
    manifest_commit_sha = key_raw.get("commit_sha")
    created_at = raw.get("created_at")
    age = created_at and _age_from_iso(created_at, now)
    if age is None:
        age = dir_age

    if identity is None:
        # Cannot prove anything is stale without knowing the current
        # default-branch commit -- conservative: preserve unconditionally.
        return (
            GcCandidate(rel, "manifest_dir", "unable_to_resolve_current_identity", {}),
            False,
        )

    is_current = (
        key_raw.get("repo_identity") == identity.repo_identity
        and key_raw.get("default_branch") == identity.default_branch
        and manifest_commit_sha == identity.commit_sha
    )
    if is_current:
        return (
            GcCandidate(
                rel, "manifest_dir", "current_default_branch_manifest", {"commit_sha": manifest_commit_sha}
            ),
            False,
        )

    if age < grace_seconds:
        return (
            GcCandidate(
                rel,
                "manifest_dir",
                "within_grace_window_recent_promotion",
                {"age_seconds": round(age, 3), "commit_sha": manifest_commit_sha},
            ),
            False,
        )
    if age < ttl_seconds:
        return (
            GcCandidate(
                rel,
                "manifest_dir",
                "stale_commit_within_ttl_retention",
                {"age_seconds": round(age, 3), "commit_sha": manifest_commit_sha},
            ),
            False,
        )
    return (
        GcCandidate(
            rel,
            "manifest_dir",
            "expired_unreferenced_snapshot",
            {"age_seconds": round(age, 3), "commit_sha": manifest_commit_sha},
        ),
        True,
    )


def _remove_reclaimable(cache_root: str, candidate: GcCandidate) -> tuple[bool, str | None]:
    """Crash-safe removal: atomic rename to a ``.deleting-`` sibling, then rmtree.

    Returns ``(removed, error)``. ``removed`` is only ``True`` once the
    rename succeeded -- from that point on the directory's original name is
    already vacated (safe for a new build to reuse the digest, and safe for
    the caller to report as gone) even if the subsequent ``rmtree`` itself
    is incomplete (a later GC run finishes it via
    :func:`_classify_deleting_leftover`).
    """
    abs_path = os.path.normpath(os.path.join(cache_root, candidate.relative_path))
    parent_dir, name = os.path.split(abs_path)
    deleting_name = f"{name}{_DELETING_INFIX}{secrets.token_hex(8)}"
    deleting_path = os.path.join(parent_dir, deleting_name)
    try:
        os.replace(abs_path, deleting_path)
    except OSError as error:
        return False, f"rename_failed: {error.__class__.__name__}: {error}"
    shutil.rmtree(deleting_path, ignore_errors=True)
    return True, None


def scan_canonical_gc(
    root: str,
    *,
    apply: bool = False,
    now: float | None = None,
    storage_root: str | None = None,
    ttl_seconds: float | None = None,
    promoted_grace_seconds: float | None = None,
) -> GcReport:
    """Scan (and optionally reclaim) the canonical-map storage root for ``root``.

    Dry-run by default (``apply=False``): returns every candidate found
    without deleting anything. Pass ``apply=True`` to actually remove
    proven-reclaimable temp dirs / stale manifest dirs / crash-leftover
    ``.deleting-`` directories.

    ``storage_root``/``ttl_seconds``/``promoted_grace_seconds`` are optional
    explicit overrides (used by ``simplicio-mapper canonical gc``'s
    ``--storage-root``/``--ttl-seconds``/``--grace-seconds`` flags and by
    tests); when omitted, the storage root is resolved from ``root`` the same
    way ``canonical build``/``status`` do, and the TTL/grace window fall back
    to ``GC_TTL_SECONDS_ENV``/``GC_GRACE_SECONDS_ENV`` (or their defaults).

    Idempotent: given no concurrent writers, calling this twice with the same
    ``now`` (or a slightly later one, since nothing here shrinks the grace
    window) produces the same candidate set; after an ``apply=True`` run
    actually removes something, a second run no longer finds it.
    """
    now = now if now is not None else time.time()
    errors: list[str] = []
    abs_root = os.path.abspath(root)
    grace = _grace_seconds(promoted_grace_seconds)
    ttl = _ttl_seconds(ttl_seconds)

    identity = resolve_repo_identity_bundle(abs_root)
    override = storage_root or os.environ.get(CANONICAL_CACHE_DIR_ENV_VAR)
    if identity is None and not override:
        errors.append(
            "root is not a git repository and neither --storage-root nor "
            f"{CANONICAL_CACHE_DIR_ENV_VAR} is set; nothing to scan"
        )
        return _empty_report(apply, errors)

    if storage_root is not None:
        cache_root = os.path.abspath(storage_root)
    else:
        cache_root = resolve_canonical_cache_root(identity.common_git_dir if identity else "")
    canonical_root = os.path.normpath(os.path.join(cache_root, "canonical"))

    if not os.path.isdir(canonical_root):
        return _empty_report(apply, errors)

    scanned: list[tuple[GcCandidate, bool]] = []
    try:
        entries = sorted(os.listdir(canonical_root))
    except OSError as error:
        errors.append(f"failed to list canonical storage root: {error}")
        return _empty_report(apply, errors)

    for entry in entries:
        entry_path = os.path.join(canonical_root, entry)
        if not os.path.isdir(entry_path):
            continue
        rel = _relativize(entry_path, cache_root)
        if _DELETING_INFIX in entry:
            scanned.append((_classify_deleting_leftover(rel), True))
        elif _TMP_INFIX in entry:
            scanned.append(_classify_temp_dir(entry_path, entry, rel, now, grace_seconds=grace))
        else:
            scanned.append(
                _classify_manifest_dir(entry_path, rel, identity, now, grace_seconds=grace, ttl_seconds=ttl)
            )

    candidates = [c for c, is_gc in scanned if is_gc]
    preserved = [c for c, is_gc in scanned if not is_gc]
    removed: list[GcCandidate] = []
    recovered: list[GcCandidate] = []

    if apply:
        for candidate in candidates:
            ok, error = _remove_reclaimable(cache_root, candidate)
            if not ok:
                errors.append(f"failed to remove {candidate.relative_path}: {error}")
                continue
            if candidate.kind == "temp_dir":
                recovered.append(candidate)
            else:
                removed.append(candidate)

    return GcReport(
        schema=CANONICAL_GC_SCHEMA,
        schema_version=CANONICAL_GC_SCHEMA_VERSION,
        apply=apply,
        candidates=candidates,
        removed=removed,
        recovered=recovered,
        preserved=preserved,
        errors=errors,
    )


__all__ = [
    "CANONICAL_GC_SCHEMA",
    "CANONICAL_GC_SCHEMA_VERSION",
    "GC_GRACE_SECONDS_ENV",
    "GC_TTL_SECONDS_ENV",
    "GcCandidate",
    "GcReport",
    "scan_canonical_gc",
]
