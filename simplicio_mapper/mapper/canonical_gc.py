"""Crash-safe, conservative GC for canonical-map storage (issue #268).

Scope: reclaim disk space under a canonical-map cache root
(``<cache_root>/canonical/`` -- see :mod:`.canonical_storage`) by removing
only what is provably safe to remove:

* ``<digest>.tmp-<token>/`` staging directories left behind by an
  interrupted :func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest`
  call -- reclaimed only once the owning process is proven dead (PID check)
  or the staging directory has outlived a lease TTL.
* ``<digest>.deleting-<token>/`` directories -- the crash-safe intermediate
  name this module itself uses during removal (see below); these are never
  a valid target for anything else, so a leftover one is always safe to
  finish deleting on any later GC run, regardless of age or PID.
* Promoted ``<digest>/`` manifest directories that are either missing a
  parseable ``manifest.json`` (broken/corrupt -- never a valid promotion)
  or are a superseded generation of the *same repository* GC was invoked
  against (an older ``commit_sha`` for a repo whose current default-branch
  digest is resolved fresh on every GC call) -- never the current digest,
  never a manifest still inside its post-promotion grace window, and never
  a manifest belonging to a different repository (GC only judges the one
  repo it was asked about; see the module docstring's non-goals).

Non-goals (explicitly out of scope, matching issue #268's parent #263):
this module never enables reuse in ``index``/``scan``, never alters any
existing artifact format, and never touches ``overlays/`` promoted
directories (no builder writes real overlay content there yet -- see
:mod:`.canonical_overlay`'s module docstring -- so there is nothing safe to
reclaim there beyond the same tmp/deleting staging convention).

Crash-safety / concurrent-read-safety design: removing a directory is never
a single ``shutil.rmtree`` on its live name. Instead, the target is first
atomically renamed (``os.replace``, a single filesystem operation) to a
sibling ``<name>.deleting-<token>`` name, *then* recursively deleted. On
POSIX (Linux/macOS), a process that already has a file open inside the
directory keeps a valid file descriptor even after the containing directory
is renamed out from under it -- so the ten-concurrent-readers scenario this
issue's acceptance criteria calls out never observes a torn read, only
"the digest doesn't exist under its original name anymore" if it queries
again afterward. If the process crashes between the rename and the
``rmtree``, the next GC invocation finds the ``.deleting-`` directory and
always finishes removing it (see :func:`_classify_deleting_entry`) --
that is what makes this GC crash-safe rather than merely "safe when it runs
to completion".

Windows note (documented gap, not verified on a live Windows checkout --
this repo's dev/CI environment here is Linux): ``os.replace`` on a
directory that another process holds open files under can fail with
``PermissionError`` on Windows (no POSIX-style "rename over open handles"
guarantee). This module treats that as a fail-closed, retryable condition:
the candidate is left untouched, reported as ``"removed": false`` with
``"reason": "rename_failed"``, and picked up again on the next GC run. This
never corrupts or partially deletes live content -- it just means Windows
GC may need one extra run once contending readers close their handles.
"""

from __future__ import annotations

import os
import secrets
import shutil
import time
from dataclasses import dataclass

import orjson

from .canonical_identity import resolve_repo_identity_bundle
from .canonical_storage import resolve_canonical_cache_root

GC_RECEIPT_SCHEMA = "simplicio.canonical-gc-receipt/v1"
GC_RECEIPT_SCHEMA_VERSION = 1

#: Overridable via env var, mirrors the existing index-lock TTL convention
#: (``simplicio_mapper.cli._index_engine.INDEX_LOCK_TTL_ENV``) but scoped to
#: canonical-map GC so the two knobs can be tuned independently.
GC_TTL_ENV = "SIMPLICIO_MAPPER_CANONICAL_GC_TTL_SECONDS"
DEFAULT_GC_TTL_SECONDS = 6 * 60 * 60

#: Grace window after a manifest's ``created_at`` during which it is never
#: eligible for "superseded generation" removal, even if a newer commit on
#: the same repo has already been resolved -- protects a manifest that just
#: finished promoting and may still be in use by a reader that resolved it
#: moments ago (issue #268 AC: "nunca remove ... snapshot recém-promovido").
GC_PROMOTED_GRACE_ENV = "SIMPLICIO_MAPPER_CANONICAL_GC_GRACE_SECONDS"
DEFAULT_GC_PROMOTED_GRACE_SECONDS = 5 * 60

#: Minimum age before a *malformed* tmp/broken entry (no readable PID, or no
#: parseable manifest) is even considered -- guards against a race with a
#: writer that has not finished ``os.open``/first ``write`` yet.
MALFORMED_GRACE_SECONDS = 2.0

#: Must match ``simplicio_mapper.mapper.canonical_storage._TMP_INFIX``. Not
#: imported directly (that name is private to its module); every test in
#: ``tests/python/test_canonical_gc.py`` builds fixtures via
#: ``canonical_manifest_tmp_dir`` itself, so any drift between the two
#: literals is caught immediately by the test suite rather than silently
#: skipping real staging directories.
_TMP_INFIX = ".tmp-"
_DELETING_INFIX = ".deleting-"
_MANIFEST_FILE_NAME = "manifest.json"

_CANONICAL_SUBDIR = "canonical"
_OVERLAYS_SUBDIR = "overlays"


def _process_is_alive(pid: int) -> bool:
    """Cross-platform, dependency-free liveness check for ``pid``.

    Deliberately self-contained (not imported from
    ``simplicio_mapper.cli._index_engine``): ``cli`` depends on ``mapper``,
    never the reverse, so importing the CLI's lock helpers from here would
    invert that layering for a two-branch liveness check that is easy to
    keep in sync by inspection alone.
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            process = kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(process)
        except (AttributeError, OSError):
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _gc_ttl_seconds() -> float:
    raw = os.environ.get(GC_TTL_ENV)
    if raw is None:
        return float(DEFAULT_GC_TTL_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_GC_TTL_SECONDS)


def _gc_promoted_grace_seconds() -> float:
    raw = os.environ.get(GC_PROMOTED_GRACE_ENV)
    if raw is None:
        return float(DEFAULT_GC_PROMOTED_GRACE_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_GC_PROMOTED_GRACE_SECONDS)


def _dir_age_seconds(path: str, now: float) -> float:
    try:
        stat = os.stat(path)
    except OSError:
        return 0.0
    return max(0.0, now - stat.st_mtime)


def _read_manifest(digest_dir: str) -> dict | None:
    manifest_path = os.path.join(digest_dir, _MANIFEST_FILE_NAME)
    try:
        with open(manifest_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        parsed = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


@dataclass(frozen=True)
class GCCandidate:
    """One directory entry GC inspected under ``canonical/`` or ``overlays/``.

    ``name`` is a directory *basename* (a content-addressed digest, or a
    digest plus a ``.tmp-``/``.deleting-`` suffix) -- never an absolute path,
    matching the receipt's no-absolute-path-leak requirement.
    """

    subdir: str
    name: str
    kind: str
    action: str
    reason: str
    age_seconds: float
    pid: int | None = None
    removed: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        payload = {
            "location": f"{self.subdir}/{self.name}",
            "kind": self.kind,
            "action": self.action,
            "reason": self.reason,
            "age_seconds": round(self.age_seconds, 3),
        }
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.removed is not None:
            payload["removed"] = self.removed
        if self.error is not None:
            payload["error"] = self.error
        return payload


def _classify_deleting_entry(subdir: str, name: str, age_seconds: float) -> GCCandidate:
    # A `.deleting-` name is written only by this module's own removal path,
    # immediately before an unconditional `rmtree`. Nothing else ever reads
    # or writes it, so finding one always means a prior GC run (or the
    # builder, which never uses this infix) crashed mid-delete -- always
    # safe to finish, regardless of age or any PID embedded in the token.
    return GCCandidate(
        subdir=subdir,
        name=name,
        kind="deleting_leftover",
        action="remove",
        reason="crash_leftover_deleting",
        age_seconds=age_seconds,
    )


def _classify_tmp_entry(
    subdir: str, name: str, entry_path: str, age_seconds: float, ttl_seconds: float
) -> GCCandidate:
    token = name.rsplit(_TMP_INFIX, 1)[-1]
    pid: int | None = None
    if token.isdigit():
        try:
            pid = int(token)
        except ValueError:
            pid = None

    if pid is not None:
        if age_seconds < MALFORMED_GRACE_SECONDS:
            return GCCandidate(
                subdir=subdir,
                name=name,
                kind="tmp_staging",
                action="preserve",
                reason="too_young_to_judge",
                age_seconds=age_seconds,
                pid=pid,
            )
        if _process_is_alive(pid):
            return GCCandidate(
                subdir=subdir,
                name=name,
                kind="tmp_staging",
                action="preserve",
                reason="owner_alive",
                age_seconds=age_seconds,
                pid=pid,
            )
        return GCCandidate(
            subdir=subdir,
            name=name,
            kind="tmp_staging",
            action="remove",
            reason="dead_process_owner",
            age_seconds=age_seconds,
            pid=pid,
        )

    # No parseable PID in the staging token: the only remaining proof of
    # abandonment is lease expiry (issue #268 AC: "prova de lease expirado
    # ou identidade de PID morta" -- either suffices on its own).
    if age_seconds > ttl_seconds:
        return GCCandidate(
            subdir=subdir,
            name=name,
            kind="tmp_staging",
            action="remove",
            reason="lease_expired",
            age_seconds=age_seconds,
        )
    return GCCandidate(
        subdir=subdir,
        name=name,
        kind="tmp_staging",
        action="preserve",
        reason="lease_not_expired",
        age_seconds=age_seconds,
    )


def _classify_promoted_entry(
    name: str,
    entry_path: str,
    age_seconds: float,
    *,
    promoted_grace_seconds: float,
    ttl_seconds: float,
    current_repo_identity: str | None,
    current_digest: str | None,
) -> GCCandidate:
    manifest = _read_manifest(entry_path)
    if manifest is None:
        if age_seconds <= max(MALFORMED_GRACE_SECONDS, ttl_seconds):
            reason = "too_young_to_judge" if age_seconds <= MALFORMED_GRACE_SECONDS else "lease_not_expired"
            return GCCandidate(
                subdir=_CANONICAL_SUBDIR,
                name=name,
                kind="promoted_manifest",
                action="preserve",
                reason=reason,
                age_seconds=age_seconds,
            )
        return GCCandidate(
            subdir=_CANONICAL_SUBDIR,
            name=name,
            kind="promoted_manifest",
            action="remove",
            reason="broken_manifest_expired",
            age_seconds=age_seconds,
        )

    key = manifest.get("key") if isinstance(manifest.get("key"), dict) else {}
    repo_identity = key.get("repo_identity")

    if current_repo_identity is None or repo_identity != current_repo_identity:
        return GCCandidate(
            subdir=_CANONICAL_SUBDIR,
            name=name,
            kind="promoted_manifest",
            action="preserve",
            reason="other_repo_out_of_scope",
            age_seconds=age_seconds,
        )

    if name == current_digest:
        return GCCandidate(
            subdir=_CANONICAL_SUBDIR,
            name=name,
            kind="promoted_manifest",
            action="preserve",
            reason="current_reference",
            age_seconds=age_seconds,
        )

    if age_seconds < promoted_grace_seconds:
        return GCCandidate(
            subdir=_CANONICAL_SUBDIR,
            name=name,
            kind="promoted_manifest",
            action="preserve",
            reason="recently_promoted",
            age_seconds=age_seconds,
        )

    return GCCandidate(
        subdir=_CANONICAL_SUBDIR,
        name=name,
        kind="promoted_manifest",
        action="remove",
        reason="superseded_generation",
        age_seconds=age_seconds,
    )


def _remove_directory(parent_dir: str, name: str) -> tuple[bool, str | None]:
    """Crash-safe removal: atomic rename to a ``.deleting-`` sibling, then rmtree.

    Returns ``(removed, error)``. ``removed`` is only ``True`` once the
    rename succeeded -- from that point on, the directory's original name is
    already vacated (safe for a new build to reuse the digest, and safe for
    the caller to report as gone) even if the subsequent ``rmtree`` itself
    is incomplete (a later GC run finishes it via
    :func:`_classify_deleting_entry`).
    """
    src = os.path.join(parent_dir, name)
    deleting_name = f"{name}{_DELETING_INFIX}{secrets.token_hex(8)}"
    dst = os.path.join(parent_dir, deleting_name)
    try:
        os.replace(src, dst)
    except OSError as error:
        return False, f"rename_failed: {error.__class__.__name__}"
    shutil.rmtree(dst, ignore_errors=True)
    return True, None


def _resolve_current_reference(root: str, storage_root: str) -> tuple[str | None, str | None]:
    """Best-effort ``(repo_identity, digest)`` for the repo's current default branch.

    Returns ``(None, None)`` when identity resolution fails for any reason
    (non-git directory, detached-without-remote edge cases, etc.) -- GC still
    runs in that case, it just never classifies any promoted manifest as
    "superseded" (falls back to ``other_repo_out_of_scope``/preserve), which
    is the conservative direction to fail in.
    """
    identity = resolve_repo_identity_bundle(root)
    if identity is None:
        return None, None
    # The digest also depends on `schema_version`/`mapper_version`/
    # `config_fingerprint`, which this function has no way to know without
    # rebuilding -- so instead of recomputing a digest, scan already-promoted
    # manifests for one whose key matches this repo's resolved
    # (repo_identity, default_branch, commit_sha, tree_sha) tuple. That is
    # exactly the information GC needs ("is this repo's current commit
    # represented by some promoted digest") without ever invoking the
    # builder or requiring a config fingerprint as an extra GC argument.
    canonical_dir = os.path.join(storage_root, _CANONICAL_SUBDIR)
    try:
        entries = os.listdir(canonical_dir)
    except OSError:
        return identity.repo_identity, None
    for entry_name in entries:
        if _TMP_INFIX in entry_name or _DELETING_INFIX in entry_name:
            continue
        manifest = _read_manifest(os.path.join(canonical_dir, entry_name))
        if manifest is None:
            continue
        key = manifest.get("key") if isinstance(manifest.get("key"), dict) else {}
        if (
            key.get("repo_identity") == identity.repo_identity
            and key.get("default_branch") == identity.default_branch
            and key.get("commit_sha") == identity.commit_sha
            and key.get("tree_sha") == identity.tree_sha
        ):
            return identity.repo_identity, entry_name
    return identity.repo_identity, None


def run_canonical_gc(
    root: str,
    *,
    storage_root: str | None = None,
    apply: bool = False,
    ttl_seconds: float | None = None,
    promoted_grace_seconds: float | None = None,
) -> dict:
    """Inspect (and, if ``apply``, reclaim) canonical-map GC candidates for ``root``.

    Dry-run by default (``apply=False``): every candidate is classified and
    reported, nothing on disk changes. Passing ``apply=True`` is the explicit
    opt-in this issue's acceptance criteria requires for any mutation.

    Idempotent: a second call (dry-run or apply) against the same, unchanged
    on-disk state reaches the same classification for every remaining entry
    -- an ``apply`` run that already removed everything reclaimable leaves a
    following run with zero removable candidates.
    """
    now = time.time()
    ttl = _gc_ttl_seconds() if ttl_seconds is None else max(0.0, ttl_seconds)
    grace = _gc_promoted_grace_seconds() if promoted_grace_seconds is None else max(0.0, promoted_grace_seconds)

    abs_root = os.path.abspath(root)
    if storage_root is not None:
        cache_root = os.path.abspath(storage_root)
    else:
        common_git_dir = None
        try:
            from .canonical_identity import resolve_common_git_dir

            common_git_dir = resolve_common_git_dir(abs_root)
        except Exception:  # noqa: BLE001 - identity resolution must never crash GC
            common_git_dir = None
        cache_root = resolve_canonical_cache_root(common_git_dir or abs_root)

    current_repo_identity, current_digest = _resolve_current_reference(abs_root, cache_root)

    candidates: list[GCCandidate] = []

    canonical_dir = os.path.join(cache_root, _CANONICAL_SUBDIR)
    try:
        canonical_entries = sorted(os.listdir(canonical_dir))
    except OSError:
        canonical_entries = []

    for name in canonical_entries:
        entry_path = os.path.join(canonical_dir, name)
        if not os.path.isdir(entry_path):
            continue
        age = _dir_age_seconds(entry_path, now)
        if _DELETING_INFIX in name:
            candidates.append(_classify_deleting_entry(_CANONICAL_SUBDIR, name, age))
        elif _TMP_INFIX in name:
            candidates.append(_classify_tmp_entry(_CANONICAL_SUBDIR, name, entry_path, age, ttl))
        else:
            candidates.append(
                _classify_promoted_entry(
                    name,
                    entry_path,
                    age,
                    promoted_grace_seconds=grace,
                    ttl_seconds=ttl,
                    current_repo_identity=current_repo_identity,
                    current_digest=current_digest,
                )
            )

    overlays_dir = os.path.join(cache_root, _OVERLAYS_SUBDIR)
    try:
        overlay_entries = sorted(os.listdir(overlays_dir))
    except OSError:
        overlay_entries = []

    for name in overlay_entries:
        entry_path = os.path.join(overlays_dir, name)
        if not os.path.isdir(entry_path):
            continue
        age = _dir_age_seconds(entry_path, now)
        if _DELETING_INFIX in name:
            candidates.append(_classify_deleting_entry(_OVERLAYS_SUBDIR, name, age))
        elif _TMP_INFIX in name:
            candidates.append(_classify_tmp_entry(_OVERLAYS_SUBDIR, name, entry_path, age, ttl))
        else:
            # No builder promotes real overlay content today (see module
            # docstring) -- nothing here is ever judged reclaimable, only
            # reported, so a future overlay-promotion feature cannot be
            # silently broken by this GC reclaiming its output ahead of that
            # feature actually landing.
            candidates.append(
                GCCandidate(
                    subdir=_OVERLAYS_SUBDIR,
                    name=name,
                    kind="promoted_overlay",
                    action="preserve",
                    reason="overlay_removal_not_implemented",
                    age_seconds=age,
                )
            )

    removed: list[GCCandidate] = []
    preserved: list[GCCandidate] = []
    for candidate in candidates:
        if candidate.action != "remove":
            preserved.append(candidate)
            continue
        if not apply:
            preserved.append(
                GCCandidate(
                    subdir=candidate.subdir,
                    name=candidate.name,
                    kind=candidate.kind,
                    action="remove",
                    reason=candidate.reason,
                    age_seconds=candidate.age_seconds,
                    pid=candidate.pid,
                    removed=False,
                    error="dry_run",
                )
            )
            continue
        parent_dir = os.path.join(cache_root, candidate.subdir)
        ok, error = _remove_directory(parent_dir, candidate.name)
        outcome = GCCandidate(
            subdir=candidate.subdir,
            name=candidate.name,
            kind=candidate.kind,
            action="remove",
            reason=candidate.reason,
            age_seconds=candidate.age_seconds,
            pid=candidate.pid,
            removed=ok,
            error=error,
        )
        if ok:
            removed.append(outcome)
        else:
            preserved.append(outcome)

    return {
        "schema": GC_RECEIPT_SCHEMA,
        "schema_version": GC_RECEIPT_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "mode": "apply" if apply else "dry_run",
        "ttl_seconds": ttl,
        "promoted_grace_seconds": grace,
        "candidates": [candidate.to_dict() for candidate in candidates],
        "removed": [candidate.to_dict() for candidate in removed],
        "preserved": [candidate.to_dict() for candidate in preserved],
    }


__all__ = [
    "GC_RECEIPT_SCHEMA",
    "GC_RECEIPT_SCHEMA_VERSION",
    "run_canonical_gc",
]
