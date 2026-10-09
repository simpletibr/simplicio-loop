"""``simplicio-mapper canonical build|status|verify|gc`` -- canonical-map CLI surface.

Parent: #263; epic: #236; ADR-008 (``.specs/architecture/ADR-008-canonical-map-overlays.md``).

Four verbs over the already-merged canonical-map machinery
(``simplicio_mapper.mapper.canonical*`` / ``effective_view.py``):

* ``canonical build <path> --json`` (issue #266, migration-plan step 7) --
  resolves the default branch via git, builds the full ``CanonicalMapKey``,
  and calls the existing
  :func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest_with_diagnostics`
  builder (never reimplemented here). That builder already writes to a
  ``.tmp-<token>/`` staging directory and promotes atomically via
  ``os.replace`` (see its module docstring) -- this CLI adds **no** second,
  competing write path. Since issue #236 gap #1 (ADR-008 section 4), the
  builder itself also holds a cross-worktree single-flight lock
  (``operation="canonical-build"``, reusing
  :mod:`simplicio_mapper.mapper.file_lock`) around the expensive
  checkout-and-pipeline-run work, so two concurrent ``canonical build``
  invocations against the same digest never both do that work: the loser
  waits (bounded) and reads the winner's promoted manifest. This CLI surfaces
  that outcome verbatim via the receipt's ``reason_code``/``waited_for_lock``
  fields; a reader can never observe a partially-promoted manifest either
  way.
* ``canonical status <path> --json`` (issue #266) -- **read-only**. Never
  calls ``build_canonical_manifest`` (and therefore never builds/writes
  anything). Reports redacted digest/key material, freshness against the
  current resolved default-branch commit, whether a build looks in-progress
  (a ``<digest>.tmp-*`` staging directory is present), and worktree-overlay
  counts (files reused/remapped) when the worktree's key matches an existing
  canonical manifest.
* ``canonical verify <path> --json`` (issue #267) -- independent parity
  proof between the composed ``EffectiveMapView`` (canonical manifest +
  worktree overlay) and a bounded full remap, via
  :func:`simplicio_mapper.mapper.canonical_verify.verify_canonical_parity`.
  Exit 0 on match, 1 on mismatch/failure. Read-only, like ``status``.
* ``canonical overlay <path> [--json]`` (issue #1574) -- maps THIS worktree as the central
  default-branch base plus its own delta and writes only the worktree's state
  (``.simplicio-loop/overlay.json`` + project-map / symbol-index / precedent-index); never writes
  the base. Exit 1 (``status: fallback``) tells the caller to run the full ``index`` instead.
* ``canonical gc <path> [--apply] [--json]`` (issue #268, ADR-008 section 5)
  -- conservative, crash-safe garbage collection of interrupted-promotion
  temp dirs and stale canonical manifests under the same content-addressed
  storage root ``build``/``status`` read from. Dry-run by default; ``--apply``
  opts into actually deleting anything. See
  :mod:`simplicio_mapper.mapper.canonical_gc` for the full scan/reclaim
  logic and its documented heuristic limitations.

``build``/``status`` degrade to a stable, versioned error receipt -- never a
raw traceback -- for: a non-git directory, git being unavailable, a corrupt/
invalid manifest already on disk. A detached ``HEAD`` is **not** an error
case: :func:`canonical_identity.resolve_repo_identity_bundle` resolves the
default branch via ``refs/remotes/origin/HEAD``/``refs/heads/<branch>``, not
via the worktree's current ``HEAD``, so identity resolution (and therefore
both commands) works the same whether or not the calling worktree is
currently on the default branch. ``gc`` reports its own
``simplicio.canonical-gc/v1`` receipt (see ``canonical_gc.py``) rather than
this module's ``build``/``status`` error-receipt shape, since its
candidates/removed/preserved/recovered structure doesn't fit the
single-manifest ``build``/``status`` payload. ``verify`` similarly reports
its own ``verify_canonical_parity`` receipt shape (result/counts/mismatches),
not the ``build``/``status`` error-receipt shape.

Privacy (issue #266 acceptance criteria, honored by ``gc``/``verify`` too):
no output field here ever carries an absolute filesystem path or a raw
remote URL. ``CanonicalMapKey.repo_identity`` is already a one-way hash of
the normalized origin URL (or, lacking a remote, of the absolute common git
dir) computed by ``canonical_identity.resolve_repo_identity`` -- this module
never re-resolves or echoes the raw remote URL, and never emits
``WorktreeOverlay.worktree_path`` (an absolute path by construction) or any
internally-resolved cache-root path. ``canonical_gc.scan_canonical_gc``
relativizes every path in its own receipt for the same reason.

This is a **net-new, isolated CLI surface**: it does not read, write, or
otherwise touch ``.simplicio-loop/`` (the per-worktree index/scan artifacts) and
is not called by ``index``/``scan``'s existing code paths. Wiring the
canonical map into those commands is migration-plan step 6 and explicitly
out of scope here (see issue #266's "Não objetivos"). Issue #266
(``build``/``status``), issue #268 (``gc``), and issue #267 (``verify``)
landed as independent PRs against the same ``canonical`` subcommand
skeleton; this file is the reconciled result -- see the git history of this
module for how they were merged.
"""

from __future__ import annotations

import dataclasses
import glob
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

from ..mapper.canonical import CANONICAL_MAP_SCHEMA_VERSION, CanonicalMapKey
from ..mapper.canonical_builder import (
    _load_existing_manifest,
    _mapper_version,
    _native_capabilities_fingerprint,
    build_canonical_manifest_with_diagnostics,
)
from ..mapper.canonical_gc import _relativize, scan_canonical_gc
from ..mapper.canonical_identity import (
    is_git_repository,
    resolve_repo_identity_bundle,
)
from ..mapper.canonical_overlay import compute_worktree_overlay
from ..mapper.canonical_reuse import compute_config_fingerprint
from ..mapper.canonical_storage import (
    canonical_manifest_dir,
    resolve_canonical_cache_root,
)
from ..mapper.canonical_verify import (
    DEFAULT_FILE_LIMIT,
    _is_out_of_scope,
    verify_canonical_parity,
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
    "       simplicio-mapper canonical status <path> [--json]\n"
    "       simplicio-mapper canonical verify <path> [--json] [--storage-root <dir>]\n"
    "                                     [--config-fingerprint <value>] [--limit <n>]\n"
    "       simplicio-mapper canonical gc <path> [--apply] [--json] [--storage-root <dir>]\n"
    "                                     [--ttl-seconds N] [--grace-seconds N]\n"
    "       simplicio-mapper canonical overlay <path> [--json]   (base + this worktree's delta)"
)

# This CLI surface takes no mapping-config overrides (filters, ignore rules, embedding mode), so
# `build`, `status`, `verify` and `overlay` all use the fingerprint of the default mapping
# configuration -- the SAME value the `index`/`scan` adapter and the worktree overlay compute
# (issue #1574): one base per default-branch tree, never one per entry point.
_DEFAULT_CONFIG_FINGERPRINT = compute_config_fingerprint(None, ".simplicio-loop")


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


def _scoped_overlay(overlay):
    """Drop the mapper's own out-of-scope paths (``SKIP_DIRS``, e.g. ``.simplicio-loop/``) from ``overlay``.

    ``compute_worktree_overlay`` reports every git-visible change verbatim,
    including a stray ``.simplicio-loop/cache/cache.db`` or ``.simplicio-loop/index.lock``
    left untracked by a *previous* mapper invocation (``canonical
    verify``/``index``/``scan`` all write into the mapper's own output dir).
    ``canonical_verify._is_out_of_scope`` already excludes exactly this class
    of path from the ``verify`` comparison so a clean worktree never
    "diverges" over its own cache residue; ``canonical status`` must apply
    the same exclusion to its overlay summary, or a prior ``verify``/``index``
    run makes ``status`` misreport ``dirty=True``/nonzero
    ``files_remapped`` for a worktree the user never touched.
    """
    changed = tuple(
        change
        for change in overlay.changed_files
        if not _is_out_of_scope(change.path)
        and not (change.previous_path and _is_out_of_scope(change.previous_path))
    )
    tombstones = tuple(path for path in overlay.tombstones if not _is_out_of_scope(path))
    dirty = bool(changed) or bool(tombstones)
    return dataclasses.replace(
        overlay,
        changed_files=changed,
        tombstones=tombstones,
        dirty=dirty,
    )


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
        native_capabilities=_native_capabilities_fingerprint(),
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

        result = build_canonical_manifest_with_diagnostics(root, cache_root, _DEFAULT_CONFIG_FINGERPRINT)
        manifest = result.manifest
        if manifest is None:
            return _error_receipt(
                CANONICAL_BUILD_SCHEMA,
                CANONICAL_BUILD_SCHEMA_VERSION,
                "canonical_build_failed",
                f"the canonical manifest builder returned no manifest (reason_code={result.reason_code}; "
                "see stderr of the underlying mapping pipeline, if any)",
            )
        return {
            "schema": CANONICAL_BUILD_SCHEMA,
            "schema_version": CANONICAL_BUILD_SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "status": "ok",
            "reused_existing": reused_existing,
            # issue #236 gap #1 (ADR-008 section 4): which of the two
            # processes racing to build the same digest actually ran the
            # pipeline vs. waited for the other one's promotion. See
            # `build_canonical_manifest_with_diagnostics`'s docstring for the
            # full reason-code catalog.
            "reason_code": result.reason_code,
            "waited_for_lock": result.reason_code in ("reused_after_wait", "built_after_wait"),
            "key": _redacted_key(key),
            "manifest": {
                # Relative to the cache root (never the absolute path
                # ``manifest.storage_root`` carries in-memory) -- matches
                # the privacy invariant every other canonical receipt in
                # this module already honors (see module docstring) and
                # ``canonical_gc.scan_canonical_gc``'s own relativization.
                "storage_root": _relativize(manifest.storage_root, cache_root),
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
                overlay = _scoped_overlay(overlay)
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


def _print_verify_human_receipt(receipt: dict) -> None:
    print(
        f"canonical verify: {receipt['result']} "
        f"(method={receipt['comparison_method']})"
    )
    counts = receipt.get("counts") or {}
    if counts:
        print(
            "  canonical_files={canonical_files} effective_files={effective_files} "
            "remap_files={remap_files} matched={matched} mismatches={mismatches}".format(
                canonical_files=counts.get("canonical_files", 0),
                effective_files=counts.get("effective_files", 0),
                remap_files=counts.get("remap_files", 0),
                matched=counts.get("matched", 0),
                mismatches=counts.get("mismatches", 0),
            )
        )
    print(f"  duration_seconds={receipt.get('duration_seconds')}")
    if receipt.get("digest"):
        print(f"  digest={receipt['digest'][:24]}...")
    if receipt.get("failure_reason"):
        print(f"  failure_reason={receipt['failure_reason']}")
    for item in (receipt.get("mismatches") or [])[:20]:
        print(f"    - {item['reason']}: {item['path']}")


def _run_verify(argv: Sequence[str]) -> int:
    root = "."
    storage_root: str | None = None
    config_fingerprint = _DEFAULT_CONFIG_FINGERPRINT
    file_limit = DEFAULT_FILE_LIMIT
    as_json = False

    positionals: list[str] = []
    i = 0
    items = list(argv)
    while i < len(items):
        arg = items[i]
        if arg in ("-h", "--help"):
            print(
                "usage: simplicio-mapper canonical verify <root> [--json] "
                "[--storage-root <dir>] [--config-fingerprint <value>] [--limit <n>]"
            )
            return 0
        elif arg == "--json":
            as_json = True
        elif arg == "--storage-root":
            i += 1
            storage_root = items[i]
        elif arg == "--config-fingerprint":
            i += 1
            config_fingerprint = items[i]
        elif arg == "--limit":
            i += 1
            try:
                file_limit = int(items[i])
            except (ValueError, IndexError):
                print("--limit requires an integer", file=sys.stderr)
                return 2
        elif arg.startswith("-"):
            print(f"unknown canonical verify option: {arg}", file=sys.stderr)
            return 2
        else:
            positionals.append(arg)
        i += 1

    if positionals:
        root = positionals[0]

    receipt = verify_canonical_parity(
        root,
        storage_root=storage_root,
        config_fingerprint=config_fingerprint,
        file_limit=file_limit,
    )

    if as_json:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    else:
        _print_verify_human_receipt(receipt)

    return 0 if receipt["result"] == "match" else 1


def _run_gc(opts: dict) -> int:
    """``canonical gc`` (issue #268) -- see ``canonical_gc.scan_canonical_gc``.

    Distinct from ``_run_build``/``_run_status`` above: it returns an exit
    code directly (its own ``simplicio.canonical-gc/v1`` receipt shape does
    not fit the single-manifest ``status``/``error`` payload those two
    verbs share), and prints its own human-readable summary.
    """
    report = scan_canonical_gc(
        opts["root"],
        apply=opts["apply"],
        storage_root=opts.get("storage_root") or None,
        ttl_seconds=opts.get("ttl_seconds"),
        promoted_grace_seconds=opts.get("grace_seconds"),
    )
    payload = report.to_dict()
    if opts.get("json"):
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        mode = "apply" if report.apply else "dry-run"
        print(
            f"canonical gc ({mode}): candidates={len(report.candidates)} "
            f"removed={len(report.removed)} recovered={len(report.recovered)} "
            f"preserved={len(report.preserved)}"
        )
        for candidate in report.candidates:
            print(f"  candidate [{candidate.kind}] {candidate.relative_path} reason={candidate.reason}")
        for candidate in report.removed:
            print(f"  removed   [{candidate.kind}] {candidate.relative_path}")
        for candidate in report.recovered:
            print(f"  recovered [{candidate.kind}] {candidate.relative_path}")
        for error in report.errors:
            print(f"  error: {error}", file=sys.stderr)
    return 1 if report.errors else 0


def _run_overlay(opts: dict) -> int:
    """Write the worktree's own overlay state over the central base; exit 1 on any fallback."""
    from ..mapper.central_overlay import OVERLAY_ARTIFACT_FILES, apply_overlay

    root = os.path.abspath(opts["root"])
    outcome = apply_overlay(root)
    payload = dict(outcome.receipt)
    payload["mode"] = "overlay"
    if outcome.artifacts is not None:
        payload["paths"] = {
            name: os.path.join(root, ".simplicio-loop", file_name)
            for name, file_name in OVERLAY_ARTIFACT_FILES.items()
        }
    if opts["json"]:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"canonical overlay: {payload['status']}"
            + (f" ({payload['fallback_reason']})" if payload.get("fallback_reason") else "")
            + f" reused={payload.get('files_reused', 0)} remapped={payload.get('files_remapped', 0)}"
        )
    return 0 if outcome.artifacts is not None else 1


def run_canonical_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper canonical <build|status|verify|gc> <path> ...``."""
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    sub = argv[0]
    rest = argv[1:]
    if sub not in ("build", "status", "verify", "gc", "overlay"):
        print(f"unknown canonical subcommand: {sub}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2

    if sub == "verify":
        return _run_verify(rest)

    root = os.getcwd()
    json_mode = False
    apply_mode = False
    storage_root: str = ""
    ttl_seconds: float | None = None
    grace_seconds: float | None = None
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
        elif arg == "--apply" and sub == "gc":
            apply_mode = True
        elif arg == "--storage-root" and sub == "gc":
            i += 1
            try:
                storage_root = rest[i]
            except IndexError:
                print("--storage-root requires a value", file=sys.stderr)
                return 2
        elif arg == "--ttl-seconds" and sub == "gc":
            i += 1
            try:
                ttl_seconds = float(rest[i])
            except (IndexError, ValueError):
                print("--ttl-seconds requires a number", file=sys.stderr)
                return 2
        elif arg == "--grace-seconds" and sub == "gc":
            i += 1
            try:
                grace_seconds = float(rest[i])
            except (IndexError, ValueError):
                print("--grace-seconds requires a number", file=sys.stderr)
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

    opts = {
        "root": root,
        "json": json_mode,
        "apply": apply_mode,
        "storage_root": storage_root,
        "ttl_seconds": ttl_seconds,
        "grace_seconds": grace_seconds,
    }

    if sub == "gc":
        return _run_gc(opts)
    if sub == "overlay":
        return _run_overlay(opts)

    payload = _run_build(opts) if sub == "build" else _run_status(opts)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(payload)
    return 1 if payload.get("status") == "error" else 0


__all__ = ["run_canonical_cli"]
