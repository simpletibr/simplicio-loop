"""Builder for a real ``CanonicalMapManifest`` (issue #236, ADR-008 step 3).

This module implements *only* migration-plan step 3 from
``.specs/architecture/ADR-008-canonical-map-overlays.md``: materializing the
mapping artifacts (project-map/precedent-index/symbol-index/call-graph) for
the resolved default-branch **commit** -- never for a worktree's current
(possibly dirty) state -- and wrapping the result in a populated
:class:`simplicio_mapper.mapper.canonical.CanonicalMapManifest`.

In addition to those four artifacts, the builder also writes a
``file_manifest`` JSON Lines side-artifact (one line per entry from
``project_map["files"]``, re-serialized verbatim -- no new computation) so
that :mod:`simplicio_mapper.mapper.effective_view`'s ``LazyFileResolver`` has
something real to read lazily when a path falls through the overlay to the
canonical base. This closes a documented interoperability gap (issue #236):
``effective_view.py`` was written against an assumed ``"file_manifest"``
artifact key that this builder did not originally populate.

It deliberately reuses, rather than reimplements, the existing single
mapping pipeline (:func:`simplicio_mapper.mapper.emit.build_artifacts`), the
identity resolution from :mod:`simplicio_mapper.mapper.canonical_identity`
(ADR-008 step 2), and the path arithmetic from
:mod:`simplicio_mapper.mapper.canonical_storage` (ADR-008 step 3, path slice,
already merged) for where a manifest's content-addressed directory and its
``.tmp-<token>`` staging sibling live. The only new mechanism here is: get a
clean checkout of the exact default-branch commit without touching the
caller's real working tree, via ``git worktree add --detach`` against a
throwaway temp path, then clean that temp worktree back up unconditionally.

Storage layout: ``<storage_root>/canonical/<CanonicalMapKey.digest()>/`` --
shape and staging-path arithmetic come from
:func:`canonical_storage.canonical_manifest_dir` /
:func:`canonical_storage.canonical_manifest_tmp_dir`. The ``storage_root``
argument here is whatever cache root the caller resolved (ADR-008 section 3:
normally ``<common_git_dir>/simplicio`` or the
``SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR`` override, via
:func:`canonical_storage.resolve_canonical_cache_root` -- resolving *that*
default is the caller's job, not this module's).

Idempotency: if ``<storage_root>/canonical/<digest>/manifest.json`` already
exists, this is treated as authoritative and the manifest is loaded and
returned without rebuilding the pipeline (reuse-not-rebuild -- content
addressed by ``CanonicalMapKey.digest()``, so a hit here means every input
that could affect the mapping output is provably unchanged). This mirrors
the general "never recompute a cache hit" pattern used by
:class:`simplicio_mapper.cache.FileProcessingCache`.

Fail-closed: any resolution or build failure returns ``None`` -- never a
partial or corrupt manifest -- matching the pattern already established by
:func:`simplicio_mapper.mapper.canonical_identity.resolve_repo_identity_bundle`.

No production code path calls this yet; wiring into ``index``/``scan``/the
lock (`_index_engine.py`) is out of scope here, tracked as later steps in the
ADR's migration plan.
"""

from __future__ import annotations

import hashlib
import os
import random
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, NamedTuple

import orjson

from .canonical import (
    CANONICAL_MAP_SCHEMA,
    CANONICAL_MAP_SCHEMA_VERSION,
    CanonicalMapKey,
    CanonicalMapManifest,
)
from .canonical_identity import resolve_repo_identity_bundle
from .canonical_storage import (
    canonical_build_lock_path,
    canonical_manifest_dir,
    canonical_manifest_tmp_dir,
)
from .emit import build_artifacts
from .file_lock import acquire_lock_at, inspect_lock_at, release_lock_at
from .parse import _JSON_WRITE_OPTIONS, _now_iso

_GIT_TIMEOUT_SECONDS = 30.0
_MANIFEST_FILE_NAME = "manifest.json"

#: ``operation`` value stamped into the cross-worktree build lock's record
#: (ADR-008 section 4) -- the existing index lock stamps ``"index"``; this is
#: the second value the ADR calls for, distinguishing the two use cases in
#: any lock-file inspection/diagnostics without needing a second lock
#: implementation.
_BUILD_LOCK_OPERATION = "canonical-build"

#: Environment override for how long a losing builder blocks waiting for the
#: winner to finish and promote, before giving up (``blocking=True`` mode,
#: the default -- see :func:`build_canonical_manifest`). Deliberately a
#: separate knob from ``SIMPLICIO_MAPPER_LOCK_TTL_SECONDS`` (the lock's own
#: dead-owner-reclaim TTL, reused as-is per ADR-008 section 4): the TTL is
#: "how long before we consider the owner dead", this is "how long a waiter
#: is willing to sit idle before falling back to fail-fast", and the two are
#: allowed to differ (a waiter should usually give up long before the lock
#: itself would be reclaimed as abandoned).
_BUILD_LOCK_WAIT_ENV = "SIMPLICIO_MAPPER_CANONICAL_BUILD_LOCK_WAIT_SECONDS"
_DEFAULT_BUILD_LOCK_WAIT_SECONDS = 600.0
_BUILD_LOCK_POLL_SECONDS = 0.2

#: Bounded retry for the throwaway detached checkout below (issue #236/#263
#: acceptance criterion: "dez ou mais processos solicitando o mesmo mapa
#: simultaneamente"). Under real concurrent load, `git worktree add` itself
#: can transiently fail even against unique target paths -- see
#: `_create_detached_checkout`'s docstring -- so a short, jittered retry is
#: the correct fix rather than failing the whole build closed on a
#: known-transient race.
_DETACHED_CHECKOUT_MAX_ATTEMPTS = 4
_DETACHED_CHECKOUT_RETRY_BASE_SECONDS = 0.05


class CanonicalBuildResult(NamedTuple):
    """Additive diagnostics wrapper -- see :func:`build_canonical_manifest_with_diagnostics`."""

    manifest: CanonicalMapManifest | None
    reason_code: str

#: Logical artifact name -> filename inside the digest directory. Kept in
#: sync with the artifact set ``write_mapping_artifacts`` would normally
#: write under ``.simplicio/`` for a live worktree (architecture-inventory is
#: derived documentation, not one of the four canonical artifacts the ADR's
#: manifest tracks, so it is intentionally excluded here).
#:
#: ``file_manifest`` is deliberately *not* listed here: unlike the four
#: entries above (each a single JSON document, written verbatim via
#: :func:`_write_json_stable`), it is a JSON Lines side-artifact -- see
#: :func:`_write_file_manifest_jsonl` -- so it gets its own write step rather
#: than going through the generic per-name loop in
#: :func:`build_canonical_manifest`.
_ARTIFACT_FILE_NAMES: dict[str, str] = {
    "project_map": "project-map.json",
    "precedent_index": "precedent-index.json",
    "symbol_index": "symbol-index.json",
    "call_graph": "call-graph.json",
}

#: Filename (inside the digest directory) for the JSON Lines file-manifest
#: side-artifact that :mod:`simplicio_mapper.mapper.effective_view`'s
#: ``LazyFileResolver`` reads lazily, one line at a time, when a path falls
#: through the overlay to the canonical base (issue #236 interoperability
#: gap between this builder and ``effective_view.py`` -- see both modules'
#: docstrings). One JSON object per line, each carrying at least the
#: ``"path"`` key ``effective_view.py`` requires, plus every other field
#: already present on the corresponding entry in ``project_map["files"]``
#: (``language``, ``size_bytes``, ``last_modified``, ``file_hash``,
#: ``git_status``, ``roles``, ``imports``, ``exports``, ``importance``, and,
#: when non-empty, ``bh_address``/``agent_id`` -- see
#: ``simplicio_mapper.models.ProjectFile.to_dict``) so a resolver lookup
#: never needs to consult ``project_map.json`` itself to get a usable
#: per-file record.
_FILE_MANIFEST_FILE_NAME = "file-manifest.jsonl"


def _mapper_version() -> str:
    try:
        from importlib.metadata import version

        return version("simplicio-mapper")
    except Exception:  # noqa: BLE001 - source checkouts may not be installed
        return "unknown"


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _write_json_stable(path: str, data: Any) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(orjson.dumps(data, option=_JSON_WRITE_OPTIONS))
    os.replace(tmp, path)


def _write_file_manifest_jsonl(path: str, file_entries: list[dict]) -> None:
    """Write ``file_entries`` as a JSON Lines file, one object per line.

    Re-serializes entries ``build_artifacts`` already produced (``project_map
    ["files"]``) -- no new computation, just a different on-disk shape so
    :func:`simplicio_mapper.mapper.effective_view._iter_canonical_file_entries`
    can stream matches one line at a time instead of parsing a single large
    JSON document. Entries are sorted by ``path`` first so the file is
    byte-for-byte reproducible across builds of the same commit (matches this
    builder's idempotency contract -- two builds of the same digest must
    agree on every artifact, not just the manifest's own fields).
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    ordered = sorted(file_entries, key=lambda entry: entry.get("path") or "")
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as handle:
        for entry in ordered:
            # Deliberately *not* `_JSON_WRITE_OPTIONS` (that constant includes
            # `OPT_INDENT_2`, which would pretty-print each entry across
            # multiple lines and break the one-object-per-line JSON Lines
            # contract `effective_view._iter_canonical_file_entries` relies
            # on to stream matches without parsing the whole file).
            handle.write(orjson.dumps(entry))
            handle.write(b"\n")
    os.replace(tmp, path)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "rb") as handle:
            return orjson.loads(handle.read())
    except (OSError, orjson.JSONDecodeError):
        return None


def _compute_file_manifest_digest(root: str, commit_sha: str) -> str | None:
    """Stable digest of the ``(path, blob_sha)`` set tracked at ``commit_sha``.

    Uses ``git ls-tree -r`` against the *main* repository (any worktree of it
    can read any commit's tree without checking it out) -- this never touches
    the detached temp checkout, so it is safe to compute before or after that
    checkout exists.
    """
    result = _run_git(["ls-tree", "-r", commit_sha], root)
    if not result or result.returncode != 0:
        return None
    entries: list[str] = []
    for line in result.stdout.splitlines():
        # format: "<mode> <type> <sha>\t<path>"
        meta, _, path = line.partition("\t")
        if not path:
            continue
        parts = meta.split()
        if len(parts) < 3:
            continue
        blob_sha = parts[2]
        entries.append(f"{path}:{blob_sha}")
    entries.sort()
    import hashlib

    raw = "\x1f".join(entries).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=24).hexdigest()


def _create_detached_checkout(root: str, commit_sha: str) -> tuple[str, str] | None:
    """Create a throwaway ``git worktree`` checked out at ``commit_sha``.

    Returns ``(base_tmp_dir, worktree_path)`` on success -- caller is
    responsible for cleanup via :func:`_remove_detached_checkout`. Returns
    ``None`` (after :data:`_DETACHED_CHECKOUT_MAX_ATTEMPTS` retries) on
    persistent failure; nothing is left behind in that case.

    Two concurrency fixes, both found by actually running ten real
    concurrent build processes against one repository (issue #236/#263
    acceptance criterion "dez ou mais processos solicitando o mesmo mapa
    simultaneamente" -- not previously covered by any real multi-process
    test):

    1. The worktree directory's basename is unique per attempt
       (``wt-<pid>-<attempt>``, not a fixed ``"wt"``): ``git worktree add``
       derives its own internal administrative directory name
       (``<common-git-dir>/worktrees/<name>/``) from the *basename* of the
       target path, not the full path -- ``base_tmp`` being unique per call
       is not enough on its own. Every worker using the literal basename
       ``"wt"`` made git race on allocating that shared administrative
       directory name.
    2. Even with a unique basename, ``git worktree add`` can still
       transiently fail under heavy concurrency against the same
       repository -- observed failure: ``fatal: failed to read
       .git/worktrees/<some-other-worker's-name>/commondir: Success`` --
       i.e. git's own worktree-registration bookkeeping is not fully
       concurrency-safe even across worktrees with distinct names. This is
       transient (a moment later, the same repository is healthy again),
       so a short, jittered, bounded retry is the correct fix rather than
       letting the whole build fail closed on a race that resolves itself.
    """
    for attempt in range(_DETACHED_CHECKOUT_MAX_ATTEMPTS):
        base_tmp = tempfile.mkdtemp(prefix="simplicio-canonical-")
        worktree_path = os.path.join(base_tmp, f"wt-{os.getpid()}-{attempt}")
        result = _run_git(["worktree", "add", "--detach", worktree_path, commit_sha], root)
        if result and result.returncode == 0:
            return base_tmp, worktree_path
        shutil.rmtree(base_tmp, ignore_errors=True)
        if attempt < _DETACHED_CHECKOUT_MAX_ATTEMPTS - 1:
            backoff = _DETACHED_CHECKOUT_RETRY_BASE_SECONDS * (attempt + 1)
            time.sleep(backoff + random.random() * _DETACHED_CHECKOUT_RETRY_BASE_SECONDS)
    return None  # fail-closed after exhausting retries, per module docstring


def _remove_detached_checkout(root: str, base_tmp: str, worktree_path: str) -> None:
    """Best-effort cleanup: never leaves a stray ``git worktree`` entry."""
    result = _run_git(["worktree", "remove", "--force", worktree_path], root)
    if not result or result.returncode != 0:
        # Directory may already be gone, or removal raced with something
        # holding a file open (e.g. AV scanners on Windows) -- fall back to
        # a manual prune so `git worktree list` never keeps a dangling entry.
        shutil.rmtree(worktree_path, ignore_errors=True)
        _run_git(["worktree", "prune"], root)
    shutil.rmtree(base_tmp, ignore_errors=True)


def _promote_digest_dir(tmp_digest_dir: str, digest_dir: str) -> None:
    """Atomically rename ``tmp_digest_dir`` to ``digest_dir``, tolerating the
    two distinct Windows failure modes a POSIX ``rename(2)`` wouldn't hit
    (issue #263 Windows-validation gap, reproduced with a real threading
    test, not just multiple processes):

    1. Two callers racing to promote the SAME content-addressed digest can
       have the loser observe ``PermissionError``/``FileExistsError``
       instead of a clean POSIX-style winner/loser outcome, even though the
       digest guarantees a byte-identical result either way.
    2. A transient sharing violation (commonly Windows Defender or the
       Search Indexer briefly holding a handle open on a directory that was
       just written to) can make ``os.replace`` fail with
       ``PermissionError`` even with no other caller involved at all --
       this is a genuinely transient condition that clears on retry, not a
       race to detect and reuse.

    Never silently loses data: if the destination is genuinely absent and
    every retry still fails, the last error propagates.
    """
    last_error: OSError | None = None
    for attempt in range(6):
        if attempt:
            time.sleep(min(0.05 * (2**attempt), 1.0))
        try:
            os.replace(tmp_digest_dir, digest_dir)
            return
        except OSError as exc:
            last_error = exc
            if os.path.isdir(digest_dir):
                # A sibling call already won the promotion race; discard our
                # copy of the (content-addressed, expected byte-identical)
                # tmp dir and let the caller reuse what's already there.
                shutil.rmtree(tmp_digest_dir, ignore_errors=True)
                return
    assert last_error is not None
    raise last_error


def _load_existing_manifest(digest_dir: str) -> CanonicalMapManifest | None:
    manifest_path = os.path.join(digest_dir, _MANIFEST_FILE_NAME)
    if not os.path.isfile(manifest_path):
        return None
    raw = _read_json(manifest_path)
    if not raw:
        return None
    try:
        key_raw = raw["key"]
        key = CanonicalMapKey(
            repo_identity=key_raw["repo_identity"],
            default_branch=key_raw["default_branch"],
            commit_sha=key_raw["commit_sha"],
            tree_sha=key_raw["tree_sha"],
            schema_version=key_raw["schema_version"],
            mapper_version=key_raw["mapper_version"],
            config_fingerprint=key_raw["config_fingerprint"],
            platform_tag=key_raw.get("platform_tag"),
        )
        return CanonicalMapManifest(
            schema=raw["schema"],
            schema_version=raw["schema_version"],
            key=key,
            storage_root=raw["storage_root"],
            artifact_paths=raw["artifact_paths"],
            file_manifest_digest=raw["file_manifest_digest"],
            counts=raw["counts"],
            created_at=raw["created_at"],
            builder=raw["builder"],
            generation=raw["generation"],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _root_fingerprint(root: str) -> str:
    return hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:24]


def _build_lock_wait_seconds(override: float | None) -> float:
    if override is not None:
        return max(0.0, override)
    raw = os.environ.get(_BUILD_LOCK_WAIT_ENV)
    if raw is None:
        return _DEFAULT_BUILD_LOCK_WAIT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_BUILD_LOCK_WAIT_SECONDS


def build_canonical_manifest(
    root: str,
    storage_root: str,
    config_fingerprint: str,
    *,
    blocking: bool = True,
    lock_wait_seconds: float | None = None,
) -> CanonicalMapManifest | None:
    """Build (or reuse) a :class:`CanonicalMapManifest` for ``root``'s default branch.

    Materializes the mapping artifacts for the resolved default-branch
    **commit** -- via a detached ``git worktree add`` temp checkout, never
    against ``root``'s own (possibly dirty) working tree -- and stores them
    content-addressed under
    ``storage_root/canonical/<CanonicalMapKey.digest()>/`` (path shape from
    :func:`canonical_storage.canonical_manifest_dir`).

    Idempotent: if that digest directory already has a ``manifest.json``, it
    is loaded and returned as-is (no rebuild) -- see the module docstring for
    why a cache hit here is always safe to trust.

    Cross-worktree single-flight (issue #236, ADR-008 section 4): before
    doing the expensive detached-checkout-and-pipeline-run work, this
    acquires the same battle-tested lock primitive the per-worktree index
    lock uses (:mod:`simplicio_mapper.mapper.file_lock`, generalized from
    ``simplicio_mapper.cli._index_engine``), keyed at
    :func:`canonical_storage.canonical_build_lock_path` with
    ``operation="canonical-build"``. A loser of the race never redoes the
    full pipeline blindly:

    * ``blocking=True`` (the default): waits, bounded by ``lock_wait_seconds``
      (or ``SIMPLICIO_MAPPER_CANONICAL_BUILD_LOCK_WAIT_SECONDS``, default 600s),
      polling for either the winner's promoted manifest to appear (returned
      directly, no rebuild) or the lock to free up (tries to become the new
      owner itself -- covers the winner crashing mid-build). Returns ``None``
      if the deadline passes with neither outcome.
    * ``blocking=False``: fails fast (returns ``None``) the instant the lock
      is found held by another live owner -- for callers (e.g. a future async
      Loop Hub caller) that would rather retry later than block a thread.

    Use :func:`build_canonical_manifest_with_diagnostics` for a version of
    this same contract that also reports *why* (a stable reason code) --
    this function's ``Optional[CanonicalMapManifest]`` return type is kept
    exactly as before for every existing caller.

    Returns ``None`` (never a partial manifest) when identity resolution
    fails, the detached checkout cannot be created, the underlying mapping
    pipeline raises, or the lock-wait deadline above is exceeded.
    """
    return build_canonical_manifest_with_diagnostics(
        root,
        storage_root,
        config_fingerprint,
        blocking=blocking,
        lock_wait_seconds=lock_wait_seconds,
    ).manifest


def build_canonical_manifest_with_diagnostics(
    root: str,
    storage_root: str,
    config_fingerprint: str,
    *,
    blocking: bool = True,
    lock_wait_seconds: float | None = None,
) -> CanonicalBuildResult:
    """Same contract as :func:`build_canonical_manifest`, plus a reason code.

    Reason codes (stable, safe to match on):

    * ``identity_unresolved`` -- repo/default-branch/commit identity could
      not be resolved (non-git directory, git unavailable, ...).
    * ``reused_cache_hit`` -- a promoted manifest for this exact key already
      existed before this call did anything else; no lock was needed.
    * ``lock_contended_fail_fast`` -- ``blocking=False`` and another live
      owner already holds the build lock for this digest.
    * ``lock_wait_timeout`` -- ``blocking=True``, waited the full budget, and
      neither a promoted manifest appeared nor did the lock ever free up for
      us to acquire.
    * ``reused_after_wait`` -- waited for a concurrent builder, then found
      its promoted manifest (the common, intended win-condition of this
      fix: exactly one process does the real work).
    * ``file_manifest_digest_failed`` / ``checkout_failed`` /
      ``pipeline_failed`` -- fail-closed at the corresponding build step.
    * ``built`` -- this call acquired the lock uncontended and built fresh.
    * ``built_after_wait`` -- this call waited first (lock briefly held by
      another process that released without promoting, e.g. it errored out),
      then itself acquired the lock and built fresh.
    """
    identity = resolve_repo_identity_bundle(root)
    if identity is None:
        return CanonicalBuildResult(None, "identity_unresolved")

    key = CanonicalMapKey(
        repo_identity=identity.repo_identity,
        default_branch=identity.default_branch,
        commit_sha=identity.commit_sha,
        tree_sha=identity.tree_sha,
        schema_version=CANONICAL_MAP_SCHEMA_VERSION,
        mapper_version=_mapper_version(),
        config_fingerprint=config_fingerprint,
        platform_tag=None,
    )
    digest = key.digest()
    cache_root = os.path.abspath(storage_root)
    digest_dir = os.path.normpath(canonical_manifest_dir(cache_root, digest))

    existing = _load_existing_manifest(digest_dir)
    if existing is not None and existing.key == key:
        return CanonicalBuildResult(existing, "reused_cache_hit")

    lock_path = canonical_build_lock_path(cache_root, digest)
    lock_extra = {"root_fingerprint": _root_fingerprint(root), "digest": digest}
    lock = acquire_lock_at(lock_path, operation=_BUILD_LOCK_OPERATION, extra_fields=lock_extra)
    waited = False

    if lock is None:
        if not blocking:
            return CanonicalBuildResult(None, "lock_contended_fail_fast")
        waited = True
        deadline = time.monotonic() + _build_lock_wait_seconds(lock_wait_seconds)
        while time.monotonic() < deadline:
            existing = _load_existing_manifest(digest_dir)
            if existing is not None and existing.key == key:
                return CanonicalBuildResult(existing, "reused_after_wait")
            if not inspect_lock_at(lock_path)["active"]:
                break
            time.sleep(_BUILD_LOCK_POLL_SECONDS)

        # Either the lock looks free now (owner released/crashed/expired) or
        # we ran out of patience -- re-check the cheap idempotent path once
        # more before trying to become the new owner ourselves.
        existing = _load_existing_manifest(digest_dir)
        if existing is not None and existing.key == key:
            return CanonicalBuildResult(existing, "reused_after_wait")
        lock = acquire_lock_at(lock_path, operation=_BUILD_LOCK_OPERATION, extra_fields=lock_extra)
        if lock is None:
            return CanonicalBuildResult(None, "lock_wait_timeout")

    try:
        # Re-check idempotency now that we actually hold the lock -- closes
        # the race window between the pre-lock check above and acquiring it
        # (another process could have promoted between those two moments).
        existing = _load_existing_manifest(digest_dir)
        if existing is not None and existing.key == key:
            return CanonicalBuildResult(
                existing, "reused_after_wait" if waited else "reused_cache_hit"
            )

        file_manifest_digest = _compute_file_manifest_digest(root, identity.commit_sha)
        if file_manifest_digest is None:
            return CanonicalBuildResult(None, "file_manifest_digest_failed")

        checkout = _create_detached_checkout(root, identity.commit_sha)
        if checkout is None:
            return CanonicalBuildResult(None, "checkout_failed")
        base_tmp, worktree_path = checkout
        try:
            artifacts = build_artifacts(worktree_path, meta=None, incremental=False)
        except Exception:  # noqa: BLE001 - any pipeline failure must fail closed
            return CanonicalBuildResult(None, "pipeline_failed")
        finally:
            _remove_detached_checkout(root, base_tmp, worktree_path)

        project_map = artifacts["project_map"]
        precedent_index = artifacts["precedent_index"]
        symbol_index = artifacts["symbol_index"]
        call_graph = artifacts["call_graph"]

        # Absolute path to the digest directory itself -- not merely relative
        # to `cache_root` -- so any consumer (in particular
        # `effective_view._canonical_file_manifest_path`, which does
        # `os.path.join(canonical.storage_root, artifact_paths[name])` with no
        # other context about where the cache root lives) can resolve an
        # artifact's real on-disk path from the manifest alone, regardless of
        # the resolving process's current working directory.
        # `test_effective_view.py` already exercises this exact contract (its
        # fixtures always pass an absolute directory as `storage_root`) --
        # this was a second, real interoperability gap alongside the missing
        # `file_manifest` artifact key (issue #236): a cache-root-relative
        # string here left every artifact unresolvable by `effective_view.py`
        # even after `file_manifest` existed.
        storage_root_field = digest_dir

        # The staging token must be unique per *call*, not just per process:
        # two threads in the same process (same PID) racing to build the same
        # digest would otherwise stomp on one another's tmp dir mid-write
        # (issue #263 Windows-validation gap -- reproduced via a real
        # threading test, not just multiple processes).
        tmp_digest_dir = os.path.normpath(
            canonical_manifest_tmp_dir(cache_root, digest, f"{os.getpid()}-{secrets.token_hex(8)}")
        )
        shutil.rmtree(tmp_digest_dir, ignore_errors=True)
        try:
            artifact_paths: dict[str, str] = {}
            for logical_name, file_name in _ARTIFACT_FILE_NAMES.items():
                _write_json_stable(os.path.join(tmp_digest_dir, file_name), artifacts[logical_name])
                artifact_paths[logical_name] = file_name

            _write_file_manifest_jsonl(
                os.path.join(tmp_digest_dir, _FILE_MANIFEST_FILE_NAME),
                list(project_map.get("files") or []),
            )
            artifact_paths["file_manifest"] = _FILE_MANIFEST_FILE_NAME

            counts = {
                "files": len(project_map.get("files") or []),
                "precedents": len(precedent_index.get("items") or []),
                "symbols": (symbol_index.get("counts") or {}).get("symbols", 0),
                "relationships": (call_graph.get("counts") or {}).get("edges", 0),
            }
            created_at = _now_iso()
            builder = {
                "pid": str(os.getpid()),
                "host": socket.gethostname(),
                "mapper_version": key.mapper_version,
            }
            manifest_payload = {
                "schema": CANONICAL_MAP_SCHEMA,
                "schema_version": CANONICAL_MAP_SCHEMA_VERSION,
                "key": {
                    "repo_identity": key.repo_identity,
                    "default_branch": key.default_branch,
                    "commit_sha": key.commit_sha,
                    "tree_sha": key.tree_sha,
                    "schema_version": key.schema_version,
                    "mapper_version": key.mapper_version,
                    "config_fingerprint": key.config_fingerprint,
                    "platform_tag": key.platform_tag,
                },
                "storage_root": storage_root_field,
                "artifact_paths": artifact_paths,
                "file_manifest_digest": file_manifest_digest,
                "counts": counts,
                "created_at": created_at,
                "builder": builder,
                "generation": 1,
            }
            _write_json_stable(os.path.join(tmp_digest_dir, _MANIFEST_FILE_NAME), manifest_payload)

            # Atomic promotion: only a fully-written temp dir ever becomes the
            # real digest dir (mirrors the write-then-rename pattern already
            # used by `_write_index_state` / `_write_json_stable`). Uses
            # `_promote_digest_dir` (bounded retry on transient Windows
            # PermissionError, issue #263) rather than a bare `os.replace`.
            if os.path.isdir(digest_dir):
                # Another process/call already promoted the same digest
                # while we were building under our own lock -- should not
                # happen now that the build lock serializes builders, but
                # kept as defense-in-depth matching the pre-lock idempotency
                # contract (content-addressed -> byte-identical outcome
                # expected either way). Prefer the existing promoted copy and
                # discard ours.
                shutil.rmtree(tmp_digest_dir, ignore_errors=True)
                reused = _load_existing_manifest(digest_dir)
                if reused is not None and reused.key == key:
                    return CanonicalBuildResult(reused, "reused_after_wait")
            else:
                os.makedirs(os.path.dirname(digest_dir), exist_ok=True)
                _promote_digest_dir(tmp_digest_dir, digest_dir)
                reused = _load_existing_manifest(digest_dir)
                if reused is not None and reused.key != key:
                    # The dir that landed at this digest doesn't match our
                    # key -- a genuinely different build content-addressed to
                    # the same digest (should be unreachable in practice,
                    # since the digest is a hash of the key, but never
                    # silently serve a mismatch).
                    shutil.rmtree(tmp_digest_dir, ignore_errors=True)
                    raise RuntimeError(
                        f"canonical manifest at {digest_dir!r} does not match "
                        "the expected CanonicalMapKey after promotion"
                    )
        finally:
            shutil.rmtree(tmp_digest_dir, ignore_errors=True)

        manifest = CanonicalMapManifest(
            schema=CANONICAL_MAP_SCHEMA,
            schema_version=CANONICAL_MAP_SCHEMA_VERSION,
            key=key,
            storage_root=storage_root_field,
            artifact_paths=artifact_paths,
            file_manifest_digest=file_manifest_digest,
            counts=counts,
            created_at=created_at,
            builder=builder,
            generation=1,
        )
        return CanonicalBuildResult(manifest, "built_after_wait" if waited else "built")
    finally:
        release_lock_at(lock)
