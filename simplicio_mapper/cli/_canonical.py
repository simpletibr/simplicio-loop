"""``simplicio-mapper canonical build|status|gc`` -- issues #266/#268 (ADR-008 step 6, partial).

Exposes a public, read-safe surface over the canonical-map model built in
issue #236 (``simplicio_mapper.mapper.canonical*`` / ``effective_view.py``):
create a real ``CanonicalMapManifest`` for a repository's resolved default
branch, report on one that may already exist, and garbage-collect stale
storage -- without wiring any path into the existing ``index``/``scan``/
``status`` commands (explicitly out of scope, per the issues' "Nao
objetivos").

Sub-commands:

* ``canonical build <root> [--json]``  -- resolves the default branch via
  git, builds (or reuses, idempotently) the full ``CanonicalMapKey`` and
  calls :func:`simplicio_mapper.mapper.canonical_builder.build_canonical_manifest`,
  which already performs the atomic promotion (write-to-tmp + ``os.replace``)
  described in ADR-008 section 5. Readers of the promoted digest directory
  never observe a partial manifest -- either the ``manifest.json`` exists and
  is complete, or it does not exist yet.
* ``canonical status <root> [--json]`` -- **read-only**: never calls the
  builder, never writes anything under ``storage_root``. Reports only
  redaction-safe fields -- a content-addressed digest, the redacted key
  summary (short SHAs, not full paths), freshness, cache/single-flight
  diagnostics (as already computed by
  :func:`simplicio_mapper.mapper.effective_view.compose_effective_view`),
  overlay counts, and an explicit invalidation/fallback reason. Per the
  issue's privacy requirement, the receipt **never** includes an absolute
  path, a raw remote URL, or file content -- see :func:`_redacted_key_summary`
  and :func:`_status_receipt` below for exactly which fields are omitted.
* ``canonical gc [<root>] [--json] [--apply] [--storage-root DIR]
  [--ttl-seconds N] [--grace-seconds N]`` -- crash-safe, conservative removal
  of temporary/expired/unreferenced canonical-map snapshots (issue #268).
  Dry-run is the default; mutation requires the explicit ``--apply`` opt-in.
  See :mod:`simplicio_mapper.mapper.canonical_gc` for the actual candidate
  classification and crash-safe removal logic -- this module only parses
  argv, resolves options, and prints the resulting receipt.

``build``/``status`` degrade to a stable, schema-shaped fallback receipt
(never a traceback) for: a non-git directory, a detached ``HEAD`` worktree
(which this module -- unlike ``index``/``scan`` -- does not treat as an error
at all, since default-branch resolution and overlay computation both work
correctly against a detached checkout; see the "detached HEAD" tests), a
missing/unavailable ``git`` executable, and a corrupt ``manifest.json`` on
disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Sequence

from ..mapper.canonical import CanonicalMapKey
from ..mapper.canonical_builder import _load_existing_manifest, build_canonical_manifest
from ..mapper.canonical_gc import run_canonical_gc
from ..mapper.canonical_identity import (
    is_git_repository,
    resolve_common_git_dir,
    resolve_repo_identity_bundle,
)
from ..mapper.canonical_overlay import compute_worktree_overlay
from ..mapper.canonical_storage import canonical_manifest_dir, resolve_canonical_cache_root
from ..mapper.effective_view import compose_effective_view

CANONICAL_STATUS_SCHEMA = "simplicio.canonical-status/v1"
CANONICAL_STATUS_SCHEMA_VERSION = 1

CANONICAL_BUILD_SCHEMA = "simplicio.canonical-build/v1"
CANONICAL_BUILD_SCHEMA_VERSION = 1

#: Documented v1 default for ``CanonicalMapKey.config_fingerprint`` at this
#: CLI surface. No mapping-parameter knobs (filters/ignore-rules/parser
#: mode/embeddings mode) are exposed yet by ``canonical build``/``status`` --
#: this constant is a stable placeholder so every caller of this module today
#: shares one ``CanonicalMapKey`` (and thus one on-disk digest) for the same
#: commit, per ADR-008's identity rule. Bump the literal string (not just the
#: constant name) the day a real per-invocation config fingerprint is wired
#: in here -- that is a deliberate cache invalidation, not a rename.
_DEFAULT_CONFIG_FINGERPRINT = "simplicio-mapper-canonical-cli/v1-no-knobs"

#: Reasons a fallback receipt can carry -- every one of these is a stable,
#: documented state, never a raised exception surfacing to the caller.
_REASON_GIT_UNAVAILABLE = "git_unavailable"
_REASON_NOT_A_GIT_REPOSITORY = "not_a_git_repository"
_REASON_GIT_IDENTITY_UNAVAILABLE = "git_identity_unavailable"
_REASON_NO_CANONICAL_MANIFEST = "no_canonical_manifest"
_REASON_INVALID_MANIFEST = "invalid_manifest"
_REASON_OVERLAY_UNAVAILABLE = "overlay_unavailable"
_REASON_BUILD_FAILED = "build_failed"


def _git_available() -> bool:
    import shutil

    return shutil.which("git") is not None


def _short_sha(sha: str | None) -> str | None:
    if not sha:
        return None
    return sha[:12]


def _fingerprint_digest(config_fingerprint: str) -> str:
    """Digest of the config fingerprint -- never the raw value, defensively.

    The default fingerprint here carries no secret, but a caller-supplied one
    (once this surface grows real knobs) might embed local filter paths --
    hashing it keeps the receipt shape safe regardless of what a future
    caller passes.
    """
    return hashlib.blake2b(config_fingerprint.encode("utf-8"), digest_size=16).hexdigest()


def _redacted_key_summary(key: CanonicalMapKey) -> dict:
    """Redacted, privacy-safe summary of a ``CanonicalMapKey``.

    Deliberately omits ``key.repo_identity`` (already a hash, but still not
    needed by any consumer of this receipt) and never carries a full
    ``commit_sha``/``tree_sha`` or any filesystem path -- only the
    content-addressed digest and short (12-char) SHA prefixes, which is
    already the convention ``git log --oneline`` / GitHub UI use for a
    human-safe commit reference.
    """
    return {
        "key_digest": key.digest(),
        "default_branch": key.default_branch,
        "commit_sha_short": _short_sha(key.commit_sha),
        "tree_sha_short": _short_sha(key.tree_sha),
        "key_schema_version": key.schema_version,
        "mapper_version": key.mapper_version,
        "config_fingerprint_digest": _fingerprint_digest(key.config_fingerprint),
        "platform_tag": key.platform_tag,
    }


def _fallback_receipt(schema: str, schema_version: int, reason: str, *, key: CanonicalMapKey | None = None) -> dict:
    receipt: dict = {
        "schema": schema,
        "schema_version": schema_version,
        "status": "fallback",
        "reason": reason,
    }
    if key is not None:
        receipt["key"] = _redacted_key_summary(key)
    return receipt


def _resolve_key(root: str, config_fingerprint: str) -> tuple[CanonicalMapKey | None, str | None]:
    """Resolve a ``CanonicalMapKey`` for ``root``, or a stable fallback reason.

    Returns ``(key, None)`` on success, or ``(None, reason)`` -- one of
    ``_REASON_GIT_UNAVAILABLE``/``_REASON_NOT_A_GIT_REPOSITORY``/
    ``_REASON_GIT_IDENTITY_UNAVAILABLE`` -- on any failure. Never raises.
    """
    if not _git_available():
        return None, _REASON_GIT_UNAVAILABLE
    if not is_git_repository(root):
        return None, _REASON_NOT_A_GIT_REPOSITORY
    identity = resolve_repo_identity_bundle(root)
    if identity is None:
        return None, _REASON_GIT_IDENTITY_UNAVAILABLE
    key = CanonicalMapKey(
        repo_identity=identity.repo_identity,
        default_branch=identity.default_branch,
        commit_sha=identity.commit_sha,
        tree_sha=identity.tree_sha,
        schema_version=1,
        mapper_version=_mapper_version(),
        config_fingerprint=config_fingerprint,
        platform_tag=None,
    )
    return key, None


def _mapper_version() -> str:
    try:
        from importlib.metadata import version

        return version("simplicio-mapper")
    except Exception:  # noqa: BLE001 - source checkouts may not be installed
        return "unknown"


def _resolve_storage_root(root: str) -> str | None:
    common_git_dir = resolve_common_git_dir(root)
    if not common_git_dir:
        return None
    return resolve_canonical_cache_root(common_git_dir)


def _build_receipt(root: str, config_fingerprint: str) -> dict:
    """Build (or reuse) the canonical manifest and return a stable receipt.

    Never raises: any resolution/build failure collapses to a fallback
    receipt with a documented ``reason``, matching
    ``build_canonical_manifest``'s own fail-closed contract (returns
    ``None`` rather than a partial manifest).
    """
    key, reason = _resolve_key(root, config_fingerprint)
    if key is None:
        return _fallback_receipt(CANONICAL_BUILD_SCHEMA, CANONICAL_BUILD_SCHEMA_VERSION, reason)

    storage_root = _resolve_storage_root(root)
    if storage_root is None:
        return _fallback_receipt(
            CANONICAL_BUILD_SCHEMA, CANONICAL_BUILD_SCHEMA_VERSION, _REASON_GIT_IDENTITY_UNAVAILABLE, key=key
        )

    digest_dir = canonical_manifest_dir(os.path.abspath(storage_root), key.digest())
    already_existed = os.path.isfile(os.path.join(digest_dir, "manifest.json"))

    try:
        manifest = build_canonical_manifest(root, storage_root, config_fingerprint)
    except Exception:  # noqa: BLE001 - CLI boundary must report a stable failure, never a traceback
        return _fallback_receipt(
            CANONICAL_BUILD_SCHEMA, CANONICAL_BUILD_SCHEMA_VERSION, _REASON_BUILD_FAILED, key=key
        )
    if manifest is None:
        return _fallback_receipt(
            CANONICAL_BUILD_SCHEMA, CANONICAL_BUILD_SCHEMA_VERSION, _REASON_BUILD_FAILED, key=key
        )

    return {
        "schema": CANONICAL_BUILD_SCHEMA,
        "schema_version": CANONICAL_BUILD_SCHEMA_VERSION,
        "status": "ok",
        "reused": already_existed,
        "key": _redacted_key_summary(manifest.key),
        "counts": dict(manifest.counts),
        "created_at": manifest.created_at,
    }


def _status_receipt(root: str, config_fingerprint: str) -> dict:
    """Read-only status receipt -- never builds, never writes.

    See the module docstring for the exact privacy contract this receipt
    must uphold (no absolute path, no raw remote URL, no file content).
    """
    key, reason = _resolve_key(root, config_fingerprint)
    if key is None:
        return _fallback_receipt(CANONICAL_STATUS_SCHEMA, CANONICAL_STATUS_SCHEMA_VERSION, reason)

    storage_root = _resolve_storage_root(root)
    if storage_root is None:
        return _fallback_receipt(
            CANONICAL_STATUS_SCHEMA, CANONICAL_STATUS_SCHEMA_VERSION, _REASON_GIT_IDENTITY_UNAVAILABLE, key=key
        )

    digest_dir = canonical_manifest_dir(os.path.abspath(storage_root), key.digest())
    manifest_path = os.path.join(digest_dir, "manifest.json")
    manifest_file_exists = os.path.isfile(manifest_path)
    manifest = _load_existing_manifest(digest_dir) if manifest_file_exists else None

    if manifest is None:
        reason = _REASON_INVALID_MANIFEST if manifest_file_exists else _REASON_NO_CANONICAL_MANIFEST
        return _fallback_receipt(CANONICAL_STATUS_SCHEMA, CANONICAL_STATUS_SCHEMA_VERSION, reason, key=key)

    overlay = compute_worktree_overlay(root, manifest.key, config_fingerprint)
    if overlay is None:
        return _fallback_receipt(
            CANONICAL_STATUS_SCHEMA, CANONICAL_STATUS_SCHEMA_VERSION, _REASON_OVERLAY_UNAVAILABLE, key=key
        )

    try:
        view = compose_effective_view(manifest, overlay)
    except ValueError:
        # overlay/base incompatibility (config fingerprint drift, stale base
        # key, etc.) -- a stable receipt, not a crash.
        return _fallback_receipt(
            CANONICAL_STATUS_SCHEMA, CANONICAL_STATUS_SCHEMA_VERSION, _REASON_OVERLAY_UNAVAILABLE, key=key
        )

    diagnostics = view.diagnostics
    return {
        "schema": CANONICAL_STATUS_SCHEMA,
        "schema_version": CANONICAL_STATUS_SCHEMA_VERSION,
        "status": "ok",
        "key": _redacted_key_summary(manifest.key),
        "counts": dict(manifest.counts),
        "freshness": {
            "canonical_created_at": manifest.created_at,
            "worktree_head_sha_short": _short_sha(overlay.worktree_commit_sha),
            "worktree_dirty": overlay.dirty,
            "worktree_same_commit_as_canonical": overlay.worktree_commit_sha == manifest.key.commit_sha,
        },
        "cache": {
            "cache_hit": diagnostics.cache_hit,
            "single_flight_waited": diagnostics.single_flight_waited,
        },
        "overlay": {
            "present": True,
            "changed_files_count": len(overlay.changed_files),
            "tombstones_count": len(overlay.tombstones),
            "dirty": overlay.dirty,
        },
        "invalidation_reason": diagnostics.invalidation_reason,
    }


def _print_build_summary(receipt: dict) -> None:
    if receipt["status"] != "ok":
        print(f"canonical build: {receipt['status']} ({receipt['reason']})", file=sys.stderr)
        return
    key = receipt["key"]
    verb = "reused" if receipt["reused"] else "built"
    print(f"canonical build: {verb} {key['key_digest'][:16]}... branch={key['default_branch']} commit={key['commit_sha_short']}")
    counts = receipt["counts"]
    print(
        f"  files={counts.get('files')} symbols={counts.get('symbols')} "
        f"precedents={counts.get('precedents')} relationships={counts.get('relationships')}"
    )


def _print_status_summary(receipt: dict) -> None:
    if receipt["status"] != "ok":
        print(f"canonical status: {receipt['status']} ({receipt['reason']})", file=sys.stderr)
        return
    key = receipt["key"]
    freshness = receipt["freshness"]
    overlay = receipt["overlay"]
    print(f"canonical status: {key['key_digest'][:16]}... branch={key['default_branch']}")
    print(f"  worktree_head={freshness['worktree_head_sha_short']} dirty={freshness['worktree_dirty']}")
    print(
        f"  overlay changed_files={overlay['changed_files_count']} tombstones={overlay['tombstones_count']}"
    )
    print(f"  cache_hit={receipt['cache']['cache_hit']} invalidation_reason={receipt['invalidation_reason']}")


def _run_gc(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    receipt = run_canonical_gc(
        root,
        storage_root=opts.get("storage_root") or None,
        apply=opts.get("apply", False),
        ttl_seconds=opts.get("ttl_seconds"),
        promoted_grace_seconds=opts.get("grace_seconds"),
    )
    if opts.get("json"):
        print(json.dumps(receipt, sort_keys=True))
    else:
        candidates = receipt["candidates"]
        removed = receipt["removed"]
        preserved = receipt["preserved"]
        print(f"canonical gc mode={receipt['mode']} candidates={len(candidates)}")
        print(f"  removed={len(removed)} preserved={len(preserved)}")
        for entry in candidates:
            marker = "removed" if entry in removed else ("would-remove" if entry["action"] == "remove" else "keep")
            print(f"  [{marker}] {entry['location']} reason={entry['reason']}")
        if not opts.get("apply", False) and any(c["action"] == "remove" for c in candidates):
            print("  (dry-run: pass --apply to actually remove the entries above)")
    return 0


_HELP = """usage: simplicio-mapper canonical build <path> [--json] [--config-fingerprint <value>]
       simplicio-mapper canonical status <path> [--json] [--config-fingerprint <value>]
       simplicio-mapper canonical gc [<path>] [--json] [--apply] [--storage-root DIR]
                                     [--ttl-seconds N] [--grace-seconds N]

canonical build   Resolve the default branch via git and build (or reuse) the
                  canonical map manifest for that commit. Atomic promotion --
                  readers never observe a partial manifest.
canonical status  Read-only. Reports digest/redacted key, freshness,
                  cache/single-flight diagnostics and overlay counts. Never
                  builds or writes anything. Never includes an absolute
                  path, a remote URL, or file content.
canonical gc      Crash-safe, conservative removal of temporary/expired/
                  unreferenced canonical-map snapshots. Dry-run by default;
                  pass --apply to actually remove entries.
"""


def _parse_build_status_opts(rest: list[str], sub: str) -> tuple[dict, int | None]:
    root = os.getcwd()
    as_json = False
    config_fingerprint = _DEFAULT_CONFIG_FINGERPRINT
    i = 0
    positional_taken = False
    while i < len(rest):
        arg = rest[i]
        if arg in ("-h", "--help"):
            print(_HELP)
            return {}, 0
        elif arg == "--json":
            as_json = True
        elif arg == "--config-fingerprint":
            i += 1
            try:
                config_fingerprint = rest[i]
            except IndexError:
                print("--config-fingerprint requires a value", file=sys.stderr)
                return {}, 2
        elif arg == "--root":
            i += 1
            try:
                root = rest[i]
            except IndexError:
                print("--root requires a value", file=sys.stderr)
                return {}, 2
        elif not arg.startswith("-") and not positional_taken:
            root = arg
            positional_taken = True
        else:
            print(f"unknown canonical {sub} option: {arg}", file=sys.stderr)
            return {}, 2
        i += 1
    return {"root": os.path.abspath(root), "json": as_json, "config_fingerprint": config_fingerprint}, None


def _parse_gc_opts(rest: list[str]) -> tuple[dict, int | None]:
    opts: dict = {
        "root": os.getcwd(),
        "json": False,
        "apply": False,
        "storage_root": "",
        "ttl_seconds": None,
        "grace_seconds": None,
    }
    positionals: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-h", "--help"):
            print(_HELP)
            return {}, 0
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--apply":
            opts["apply"] = True
        elif arg == "--storage-root":
            i += 1
            opts["storage_root"] = rest[i]
        elif arg == "--ttl-seconds":
            i += 1
            opts["ttl_seconds"] = float(rest[i])
        elif arg == "--grace-seconds":
            i += 1
            opts["grace_seconds"] = float(rest[i])
        elif arg.startswith("-"):
            print(f"unknown canonical option: {arg}", file=sys.stderr)
            return {}, 2
        else:
            positionals.append(arg)
        i += 1
    if positionals:
        opts["root"] = positionals[0]
    return opts, None


def run_canonical_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper canonical <build|status|gc> ...``."""
    if not argv or argv[0] in ("-h", "--help"):
        print(_HELP)
        return 0
    sub = argv[0]
    rest = list(argv[1:])

    if sub in ("build", "status"):
        opts, early_exit = _parse_build_status_opts(rest, sub)
        if early_exit is not None:
            return early_exit
        if sub == "build":
            receipt = _build_receipt(opts["root"], opts["config_fingerprint"])
            if opts["json"]:
                print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
            else:
                _print_build_summary(receipt)
        else:
            receipt = _status_receipt(opts["root"], opts["config_fingerprint"])
            if opts["json"]:
                print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
            else:
                _print_status_summary(receipt)
        return 0 if receipt["status"] == "ok" else 1

    if sub == "gc":
        opts, early_exit = _parse_gc_opts(rest)
        if early_exit is not None:
            return early_exit
        return _run_gc(opts)

    print(f"unknown canonical sub-command: {sub}", file=sys.stderr)
    print(_HELP, file=sys.stderr)
    return 2


__all__ = ["run_canonical_cli", "CANONICAL_STATUS_SCHEMA", "CANONICAL_BUILD_SCHEMA"]
