"""``simplicio-mapper canonical build|status`` -- read-safe CLI surface (issue #266).

Parent: #263; epic: #236; migration-plan step 7 of
``.specs/architecture/ADR-008-canonical-map-overlays.md``.

This module exposes exactly two verbs over the already-merged canonical-map
machinery (``simplicio_mapper.mapper.canonical*`` / ``effective_view.py``):

* ``canonical build <path> --json``  -- resolves the default branch via git,
  builds the full ``CanonicalMapKey``, and calls the existing
  :func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest`
  builder (never reimplemented here). That builder already writes to a
  ``.tmp-<token>/`` staging directory and promotes atomically via
  ``os.replace`` (see its module docstring) -- this CLI adds **no** second,
  competing write path and holds no lock of its own; a reader can never
  observe a partially-promoted manifest.
* ``canonical status <path> --json`` -- **read-only**. Never calls
  ``build_canonical_manifest`` (and therefore never builds/writes anything).
  Reports redacted digest/key material, freshness against the current
  resolved default-branch commit, whether a build looks in-progress (a
  ``<digest>.tmp-*`` staging directory is present), and worktree-overlay
  counts (files reused/remapped) when the worktree's key matches an existing
  canonical manifest.

Both commands degrade to a stable, versioned error receipt -- never a raw
traceback -- for: a non-git directory, git being unavailable, a corrupt/
invalid manifest already on disk. A detached ``HEAD`` is **not** an error
case: :func:`canonical_identity.resolve_repo_identity_bundle` resolves the
default branch via ``refs/remotes/origin/HEAD``/``refs/heads/<branch>``, not
via the worktree's current ``HEAD``, so identity resolution (and therefore
both commands) works the same whether or not the calling worktree is
currently on the default branch.

Privacy (issue #266 acceptance criteria): no output field here ever carries
an absolute filesystem path or a raw remote URL. ``CanonicalMapKey.repo_identity``
is already a one-way hash of the normalized origin URL (or, lacking a
remote, of the absolute common git dir) computed by
``canonical_identity.resolve_repo_identity`` -- this module never re-resolves
or echoes the raw remote URL, and never emits ``WorktreeOverlay.worktree_path``
(an absolute path by construction) or any internally-resolved cache-root
path.

This is a **net-new, isolated CLI surface**: it does not read, write, or
otherwise touch ``.simplicio/`` (the per-worktree index/scan artifacts) and
is not called by ``index``/``scan``'s existing code paths. Wiring the
canonical map into those commands is migration-plan step 6 and explicitly
out of scope here (see the issue's "Não objetivos").
"""

from __future__ import annotations

import glob
import hashlib
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

from ..mapper.canonical import CANONICAL_MAP_SCHEMA_VERSION, CanonicalMapKey
from ..mapper.canonical_builder import (
    _load_existing_manifest,
    _mapper_version,
    build_canonical_manifest,
)
from ..mapper.canonical_identity import (
    is_git_repository,
    resolve_repo_identity_bundle,
)
from ..mapper.canonical_overlay import compute_worktree_overlay
from ..mapper.canonical_storage import (
    canonical_manifest_dir,
    resolve_canonical_cache_root,
)
from ..mapper.effective_view import compose_effective_view
from ._shared import (
    CANONICAL_BUILD_SCHEMA,
    CANONICAL_BUILD_SCHEMA_VERSION,
    CANONICAL_STATUS_SCHEMA,
    CANONICAL_STATUS_SCHEMA_VERSION,
)

_GIT_TIMEOUT_SECONDS = 5.0

_USAGE = (
    "usage: simplicio-mapper canonical build <path> [--json]\n"
    "       simplicio-mapper canonical status <path> [--json]"
)

# This isolated CLI surface takes no mapping-config overrides (filters,
# ignore rules, embedding mode -- the flags the real `config_fingerprint`
# is supposed to hash per ADR-008 section 1). Threading those through is
# migration-plan step 6 (the index/scan adapter), explicitly out of scope
# for this issue. Both `build` and `status` use this same fixed sentinel so
# a `status` call always reports freshness against exactly the key a `build`
# call from this CLI would (or did) use -- never a false invalidation.
_DEFAULT_CONFIG_FINGERPRINT = hashlib.blake2b(
    b"simplicio-mapper canonical-cli/v1: no config overrides", digest_size=24
).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _detached_head(root: str) -> bool:
    """Return whether ``root`` is currently on a detached HEAD.

    Purely diagnostic -- never gates identity resolution (see module
    docstring): the default branch is resolved independent of the current
    ``HEAD``.
    """
    result = _run_git(["symbolic-ref", "-q", "HEAD"], root)
    if result is None:
        return False
    return result.returncode != 0


def _redacted_key(key: CanonicalMapKey) -> dict:
    """Serialize a ``CanonicalMapKey`` with no absolute path / raw remote URL.

    Every field on ``CanonicalMapKey`` is already safe to emit as-is:
    ``repo_identity`` is a one-way hash (never the raw origin URL or a raw
    path), ``default_branch``/``commit_sha``/``tree_sha``/``mapper_version``
    are non-sensitive identifiers, and ``config_fingerprint`` is itself a
    hash. Nothing here reaches for ``common_git_dir`` or any worktree path.
    """
    return {
        "repo_identity": key.repo_identity,
        "default_branch": key.default_branch,
        "commit_sha": key.commit_sha,
        "tree_sha": key.tree_sha,
        "schema_version": key.schema_version,
        "mapper_version": key.mapper_version,
        "config_fingerprint": key.config_fingerprint,
        "platform_tag": key.platform_tag,
        "digest": key.digest(),
    }


def _error_receipt(schema: str, schema_version: int, reason: str, detail: str = "") -> dict:
    payload = {
        "schema": schema,
        "schema_version": schema_version,
        "generated_at": _now_iso(),
        "status": "error",
        "error": {"reason": reason},
    }
    if detail:
        payload["error"]["detail"] = detail
    return payload


def _git_diagnostics(root: str) -> dict:
    return {
        "is_git_repository": is_git_repository(root),
        "detached_head": _detached_head(root),
    }


def _resolve_key_and_paths(root: str):
    """Resolve identity + build the CanonicalMapKey + cache-root paths.

    Returns ``(key, cache_root, digest_dir)`` or ``None`` when identity
    cannot be resolved (non-git directory, git unavailable, no default
    branch resolvable) -- fail-closed, matching
    ``resolve_repo_identity_bundle``'s own contract. ``cache_root``/
    ``digest_dir`` are absolute paths used only internally for file lookups;
    callers must never emit them verbatim.
    """
    identity = resolve_repo_identity_bundle(root)
    if identity is None:
        return None
    key = CanonicalMapKey(
        repo_identity=identity.repo_identity,
        default_branch=identity.default_branch,
        commit_sha=identity.commit_sha,
        tree_sha=identity.tree_sha,
        schema_version=CANONICAL_MAP_SCHEMA_VERSION,
        mapper_version=_mapper_version(),
        config_fingerprint=_DEFAULT_CONFIG_FINGERPRINT,
        platform_tag=None,
    )
    cache_root = os.path.abspath(resolve_canonical_cache_root(identity.common_git_dir))
    digest_dir = os.path.normpath(canonical_manifest_dir(cache_root, key.digest()))
    return key, cache_root, digest_dir


def _run_build(opts: dict) -> dict:
    root = os.path.abspath(opts["root"])
    try:
        if not is_git_repository(root):
            return _error_receipt(
                CANONICAL_BUILD_SCHEMA,
                CANONICAL_BUILD_SCHEMA_VERSION,
                "not_a_git_repository_or_git_unavailable",
                "root is not inside a git working tree, or git could not be invoked",
            )
        resolved = _resolve_key_and_paths(root)
        if resolved is None:
            return _error_receipt(
                CANONICAL_BUILD_SCHEMA,
                CANONICAL_BUILD_SCHEMA_VERSION,
                "identity_unresolved",
                "could not resolve default branch / commit / tree identity",
            )
        key, cache_root, digest_dir = resolved
        reused_existing = os.path.isfile(os.path.join(digest_dir, "manifest.json"))

        manifest = build_canonical_manifest(root, cache_root, _DEFAULT_CONFIG_FINGERPRINT)
        if manifest is None:
            return _error_receipt(
                CANONICAL_BUILD_SCHEMA,
                CANONICAL_BUILD_SCHEMA_VERSION,
                "canonical_build_failed",
                "the canonical manifest builder returned no manifest (see stderr of the underlying mapping pipeline, if any)",
            )
        return {
            "schema": CANONICAL_BUILD_SCHEMA,
            "schema_version": CANONICAL_BUILD_SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "status": "ok",
            "reused_existing": reused_existing,
            "key": _redacted_key(key),
            "manifest": {
                "storage_root": manifest.storage_root,
                "artifact_paths": manifest.artifact_paths,
                "file_manifest_digest": manifest.file_manifest_digest,
                "counts": manifest.counts,
                "created_at": manifest.created_at,
                "builder": manifest.builder,
                "generation": manifest.generation,
            },
        }
    except Exception as error:  # noqa: BLE001 - CLI boundary must never raise a raw traceback
        return _error_receipt(
            CANONICAL_BUILD_SCHEMA,
            CANONICAL_BUILD_SCHEMA_VERSION,
            "unexpected_error",
            str(error),
        )


def _run_status(opts: dict) -> dict:
    root = os.path.abspath(opts["root"])
    try:
        git_diag = _git_diagnostics(root)
        if not git_diag["is_git_repository"]:
            payload = _error_receipt(
                CANONICAL_STATUS_SCHEMA,
                CANONICAL_STATUS_SCHEMA_VERSION,
                "not_a_git_repository_or_git_unavailable",
                "root is not inside a git working tree, or git could not be invoked",
            )
            payload["git"] = git_diag
            return payload

        resolved = _resolve_key_and_paths(root)
        if resolved is None:
            payload = _error_receipt(
                CANONICAL_STATUS_SCHEMA,
                CANONICAL_STATUS_SCHEMA_VERSION,
                "identity_unresolved",
                "could not resolve default branch / commit / tree identity",
            )
            payload["git"] = git_diag
            return payload

        key, cache_root, digest_dir = resolved
        manifest_path = os.path.join(digest_dir, "manifest.json")
        manifest_exists = os.path.isfile(manifest_path)
        loaded = _load_existing_manifest(digest_dir) if manifest_exists else None

        invalidation_reason: str | None = None
        matches = False
        if not manifest_exists:
            invalidation_reason = "no_manifest_for_current_key"
        elif loaded is None:
            invalidation_reason = "corrupt_manifest"
        elif loaded.key != key:
            # Should not happen (the digest dir is keyed by key.digest()),
            # but never silently trust a mismatched key on disk.
            invalidation_reason = "key_mismatch"
        else:
            matches = True

        canonical_subdir = os.path.join(cache_root, "canonical")
        tmp_pattern = os.path.join(canonical_subdir, f"{key.digest()}.tmp-*")
        in_progress_dirs = [p for p in glob.glob(tmp_pattern) if os.path.isdir(p)]

        overlay_summary = None
        if matches:
            overlay = compute_worktree_overlay(root, key, _DEFAULT_CONFIG_FINGERPRINT)
            if overlay is not None:
                view = compose_effective_view(loaded, overlay)
                overlay_summary = {
                    "present": True,
                    "dirty": overlay.dirty,
                    "worktree_commit_sha": overlay.worktree_commit_sha,
                    "changed_files_count": len(overlay.changed_files),
                    "tombstones_count": len(overlay.tombstones),
                    "files_reused": view.diagnostics.files_reused,
                    "files_remapped": view.diagnostics.files_remapped,
                }
            else:
                overlay_summary = {
                    "present": False,
                    "reason": "overlay_computation_failed",
                }

        return {
            "schema": CANONICAL_STATUS_SCHEMA,
            "schema_version": CANONICAL_STATUS_SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "status": "ok",
            "git": git_diag,
            "key": _redacted_key(key),
            "freshness": {
                "manifest_exists": manifest_exists,
                "matches_current_key": matches,
                "invalidation_reason": invalidation_reason,
            },
            "build_state": {
                "in_progress": bool(in_progress_dirs),
                "staging_dir_count": len(in_progress_dirs),
            },
            "overlay": overlay_summary,
        }
    except Exception as error:  # noqa: BLE001 - CLI boundary must never raise a raw traceback
        return _error_receipt(
            CANONICAL_STATUS_SCHEMA,
            CANONICAL_STATUS_SCHEMA_VERSION,
            "unexpected_error",
            str(error),
        )


def _print_human(payload: dict) -> None:
    schema = payload.get("schema", "?")
    status = payload.get("status", "?")
    if status == "error":
        error = payload.get("error", {})
        print(f"canonical {schema} status=error reason={error.get('reason')}", file=sys.stderr)
        detail = error.get("detail")
        if detail:
            print(f"  detail: {detail}", file=sys.stderr)
        return
    if schema == CANONICAL_BUILD_SCHEMA:
        manifest = payload.get("manifest", {})
        key = payload.get("key", {})
        print(
            f"canonical build ok digest={key.get('digest', '')[:16]}… "
            f"branch={key.get('default_branch')} commit={key.get('commit_sha', '')[:12]} "
            f"reused_existing={payload.get('reused_existing')}"
        )
        counts = manifest.get("counts", {})
        print(f"  files={counts.get('files')} symbols={counts.get('symbols')} relationships={counts.get('relationships')}")
        return
    if schema == CANONICAL_STATUS_SCHEMA:
        key = payload.get("key", {})
        freshness = payload.get("freshness", {})
        build_state = payload.get("build_state", {})
        print(
            f"canonical status digest={key.get('digest', '')[:16]}… "
            f"branch={key.get('default_branch')} commit={key.get('commit_sha', '')[:12]}"
        )
        print(
            f"  manifest_exists={freshness.get('manifest_exists')} "
            f"matches_current_key={freshness.get('matches_current_key')} "
            f"invalidation_reason={freshness.get('invalidation_reason')}"
        )
        print(f"  build_in_progress={build_state.get('in_progress')}")
        overlay = payload.get("overlay")
        if overlay:
            if overlay.get("present"):
                print(
                    f"  overlay dirty={overlay.get('dirty')} files_reused={overlay.get('files_reused')} "
                    f"files_remapped={overlay.get('files_remapped')}"
                )
            else:
                print(f"  overlay unavailable ({overlay.get('reason')})")
        return
    print(payload)


def run_canonical_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper canonical <build|status> <path> ...``."""
    import json

    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    sub = argv[0]
    rest = argv[1:]
    if sub not in ("build", "status"):
        print(f"unknown canonical subcommand: {sub}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2

    root = os.getcwd()
    json_mode = False
    positional: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-h", "--help"):
            print(_USAGE)
            return 0
        elif arg == "--json":
            json_mode = True
        elif arg == "--root":
            i += 1
            try:
                root = rest[i]
            except IndexError:
                print("--root requires a value", file=sys.stderr)
                return 2
        elif arg.startswith("-"):
            print(f"unknown canonical {sub} option: {arg}", file=sys.stderr)
            print(_USAGE, file=sys.stderr)
            return 2
        else:
            positional.append(arg)
        i += 1
    if positional:
        root = positional[0]

    opts = {"root": root, "json": json_mode}
    payload = _run_build(opts) if sub == "build" else _run_status(opts)

    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(payload)

    return 1 if payload.get("status") == "error" else 0


__all__ = ["run_canonical_cli"]
