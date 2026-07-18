from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass

from ..history import append_changelog, create_snapshot
from ..mapper import _is_internal_worktree_dir, write_mapping_artifacts
from ..mapper.canonical_reuse import (
    attempt_canonical_reuse,
    is_canonical_reuse_enabled,
)
from ..mapper.canonical_reuse import (
    write_receipt as _write_canonical_reuse_receipt,
)
from ..mapper.process_liveness import process_is_alive as _process_is_alive
from ..mapper.process_liveness import process_start_token as _process_start_token
from ..retrieval_index import build_retrieval_index, write_retrieval_index
from ..toon import encode_toon_with_report
from ._args import _read_json_safe
from ._shared import (
    CONFIDENCE_RANK,
    CONFIDENCE_TAG_ORDER,
    FRESHNESS_SKIP_DIRS,
    INDEX_RESULT_SCHEMA,
    INDEX_STATE_SCHEMA,
)


def _run_once(opts: dict) -> dict:
    root = os.path.abspath(opts["root"])
    meta = dict(_read_json_safe(os.path.join(root, ".starter-meta.json")))
    if opts["stack"]:
        meta["stack"] = opts["stack"]
    if opts["product_name"]:
        meta["product_name"] = opts["product_name"]
    log = (lambda _line: None) if opts["silent"] else print
    canonical_reuse_receipt: dict | None = None
    result: dict | None = None
    # Opt-in only (issue #269): default behavior below (write_mapping_artifacts)
    # is completely unchanged unless a caller explicitly enables reuse via
    # --canonical-reuse or SIMPLICIO_MAPPER_CANONICAL_REUSE=1.
    if is_canonical_reuse_enabled(opts):
        outcome = attempt_canonical_reuse(root, opts["out"], meta)
        canonical_reuse_receipt = outcome.receipt
        result = outcome.run_result
        if result is not None:
            log(
                "-> canonical-reuse hit: reused "
                f"{canonical_reuse_receipt.get('files_reused', 0)} file(s), "
                f"remapped {canonical_reuse_receipt.get('files_remapped', 0)}"
            )
        else:
            log(
                "-> canonical-reuse fallback: "
                f"{canonical_reuse_receipt.get('fallback_reason')} (running full map)"
            )
        _write_canonical_reuse_receipt(root, opts["out"], canonical_reuse_receipt)
    if result is None:
        result = write_mapping_artifacts(
            cwd=root,
            meta=meta,
            incremental=opts["incremental"],
            output_dir=opts["out"],
            log=log,
        )
    if canonical_reuse_receipt is not None:
        result = {**result, "canonical_reuse": canonical_reuse_receipt}
    # Build the retrieval index during the normal scan/index pass so warm
    # task-aware queries never scan candidate bodies. Keep it as a first-class
    # artifact with the same source hashes used by incremental updates.
    artifact_root = os.path.join(root, opts["out"])
    project_map = _read_json_safe(os.path.join(artifact_root, "project-map.json"))
    symbol_index = _read_json_safe(os.path.join(artifact_root, "symbol-index.json"))
    call_graph = _read_json_safe(os.path.join(artifact_root, "call-graph.json"))
    retrieval_index = build_retrieval_index(
        project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        root=root,
    )
    write_retrieval_index(root, opts["out"], retrieval_index)
    # History snapshots (.simplicio/history/*.json) are always cheap JSON and
    # never create a docs/ directory on their own. The changelog markdown is
    # only appended when docs are actually being rendered for this run, so
    # --json-only/--no-docs flows stay JSON-only as documented.
    snapshot = create_snapshot(
        root, out_dir=opts["out"], trigger=opts["command"], retention=opts["retention"], artifacts=result
    )
    if snapshot is not None and opts.get("docs"):
        append_changelog(root, opts["out"], snapshot)
    return result


def _signature(root: str, out: str) -> tuple:
    abs_out = os.path.abspath(os.path.join(root, out))
    entries = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in FRESHNESS_SKIP_DIRS
            and os.path.abspath(os.path.join(current, d)) != abs_out
            and not _is_internal_worktree_dir(current, d)
        ]
        for name in files:
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((path, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


def _state_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "index-state.json")


def _lock_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "index.lock")


INDEX_LOCK_SCHEMA = "simplicio.mapper-index-lock/v1"
LEGACY_INDEX_LOCK_SCHEMA = "simplicio.index-lock/v1"
INDEX_LOCK_TTL_ENV = "SIMPLICIO_MAPPER_LOCK_TTL_SECONDS"
DEFAULT_INDEX_LOCK_TTL_SECONDS = 6 * 60 * 60
MALFORMED_LOCK_GRACE_SECONDS = 2.0


@dataclass(frozen=True)
class _IndexLockHandle:
    path: str
    token: str
    # ``lock_acquired`` is the success-path counterpart to the reclaim reason
    # codes returned by ``_inspect_index_lock`` below (issue #201's proposed
    # contract lists it as one of the minimum reason codes). Callers that want
    # to surface acquisition as evidence in CLI output can read it straight
    # off the handle instead of re-deriving it.
    reason_code: str = "lock_acquired"


def _root_fingerprint(root: str) -> str:
    return hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:24]


def _mapper_version() -> str:
    try:
        from importlib.metadata import version

        return version("simplicio-mapper")
    except Exception:  # noqa: BLE001 - source checkouts may not be installed
        return "unknown"


def _lock_reason(reason: str) -> str:
    return {
        "live": "lock_live_owner",
        "legacy_live": "lock_live_owner",
        "dead_process": "lock_dead_owner_reclaimed",
        "pid_reused": "lock_dead_owner_reclaimed",
        "ttl_expired": "lock_expired_reclaimed",
        "malformed": "lock_malformed_reclaimed",
        "legacy": "lock_legacy_reclaimed",
        "owner_mismatch": "lock_owner_mismatch",
    }.get(reason, reason)


def _index_lock_ttl_seconds() -> float:
    raw = os.environ.get(INDEX_LOCK_TTL_ENV)
    if raw is None:
        return float(DEFAULT_INDEX_LOCK_TTL_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_INDEX_LOCK_TTL_SECONDS)


# `_process_is_alive` / `_process_start_token` used to be defined inline
# here; they now live in `simplicio_mapper.mapper.process_liveness` (issue
# #268) so `canonical_gc.py` can reuse the exact same primitives without
# `simplicio_mapper.mapper` importing from `simplicio_mapper.cli` (see that
# module's docstring for why). Imported above, re-exported under their
# original names so every existing call site in this file is unchanged.


def _lock_file_snapshot(path: str) -> tuple[bytes, tuple[int, int, int]] | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        stat = os.stat(path)
    except OSError:
        return None
    return raw, (stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0))


def _remove_lock_snapshot(path: str, snapshot: tuple[bytes, tuple[int, int, int]]) -> bool:
    if _lock_file_snapshot(path) != snapshot:
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _inspect_index_lock(root: str, out: str, *, recover: bool = False) -> dict:
    """Classify a lock and optionally remove a proven orphan without races."""
    path = _lock_path(root, out)
    snapshot = _lock_file_snapshot(path)
    if snapshot is None:
        return {"exists": False, "active": False, "recovered": False, "reason": "absent"}
    raw, stat_identity = snapshot
    age = max(0.0, time.time() - (stat_identity[0] / 1_000_000_000))
    stripped = raw.decode("utf-8", errors="replace").strip()
    record: dict | None = None
    legacy = False
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            record = parsed
        elif isinstance(parsed, int) and parsed > 0 and stripped.isdigit():
            legacy = True
            record = {"pid": parsed}
    except ValueError:
        if stripped.isdigit():
            legacy = True
            record = {"pid": int(stripped)}

    reason = "malformed"
    recoverable = age >= MALFORMED_LOCK_GRACE_SECONDS
    pid = None
    if record is not None:
        pid = record.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            reason = "malformed"
            recoverable = age >= MALFORMED_LOCK_GRACE_SECONDS
        else:
            alive = _process_is_alive(pid)
            acquired_at = record.get("acquired_at")
            process_start = record.get("process_start_identity", record.get("process_start"))
            record_age = age
            if isinstance(acquired_at, (int, float)):
                record_age = max(0.0, time.time() - float(acquired_at))
            if not alive:
                reason = "dead_process"
                recoverable = True
            elif record_age > _index_lock_ttl_seconds():
                # Report expiration for operators, but retain the lock while
                # the owner is alive. Reclaiming an active lock can permit two
                # deep passes to mutate the same artifact set concurrently.
                reason = "ttl_expired"
                recoverable = False
            elif legacy:
                reason = "legacy_live"
                recoverable = False
            elif (
                record.get("schema") not in (INDEX_LOCK_SCHEMA, LEGACY_INDEX_LOCK_SCHEMA)
                or not isinstance(record.get("owner_token", record.get("token")), str)
                or not record.get("owner_token", record.get("token"))
                or not isinstance(process_start, str)
            ):
                reason = "malformed"
                # A partially-written record can still contain a valid PID.
                # Never reclaim it while that process is alive; malformed
                # metadata is not evidence that ownership ended.
                recoverable = age >= MALFORMED_LOCK_GRACE_SECONDS and not alive
            else:
                actual_start = _process_start_token(pid)
                expected_start = process_start
                if (
                    actual_start is not None
                    and expected_start != "unknown"
                    and actual_start != expected_start
                ):
                    reason = "pid_reused"
                    recoverable = True
                else:
                    reason = "live"
                    # A live owner is never reclaimed solely because its
                    # heartbeat is old. This is the critical cross-platform
                    # safety invariant; TTL only applies once the owner is
                    # proven dead or unresolvable.
                    recoverable = False

    recovered = False
    if recover and recoverable:
        recovered = _remove_lock_snapshot(path, snapshot)
        if not recovered:
            # A concurrent owner replaced the observed lock; never unlink it.
            return _inspect_index_lock(root, out, recover=False)
    return {
        "exists": not recovered,
        "active": not recovered and not recoverable,
        "recovered": recovered,
        "reason": reason,
        "reason_code": _lock_reason(reason),
        "pid": pid,
        "age_seconds": round(age, 3),
        "legacy": legacy,
        "owner": record if isinstance(record, dict) else None,
    }


def _acquire_index_lock(root: str, out: str) -> _IndexLockHandle | None:
    path = _lock_path(root, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _attempt in range(4):
        token = secrets.token_hex(16)
        record = {
            "schema": INDEX_LOCK_SCHEMA,
            "pid": os.getpid(),
            "process_start": _process_start_token(os.getpid()) or "unknown",
            "token": token,
            "acquired_at": time.time(),
            # Canonical v1 fields. The short aliases above remain for readers
            # of the pre-0.21 lock format.
            "process_start_identity": _process_start_token(os.getpid()) or "unknown",
            "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
            "created_at": time.time(),
            "heartbeat_at": time.time(),
            "owner_token": token,
            "root_fingerprint": _root_fingerprint(root),
            "mapper_version": _mapper_version(),
            "operation": "index",
        }
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            status = _inspect_index_lock(root, out, recover=True)
            if status["active"]:
                return None
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return _IndexLockHandle(path=path, token=token)
    return None


def _release_index_lock(lock: _IndexLockHandle | None) -> None:
    if not lock:
        return
    snapshot = _lock_file_snapshot(lock.path)
    if snapshot is None:
        return
    try:
        record = json.loads(snapshot[0].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return
    if not isinstance(record, dict) or record.get("owner_token", record.get("token")) != lock.token:
        return
    _remove_lock_snapshot(lock.path, snapshot)


def _artifact_paths(root: str, out: str) -> dict[str, str]:
    abs_out = os.path.abspath(os.path.join(root, out))
    return {
        "project_map": os.path.join(abs_out, "project-map.json"),
        "precedent_index": os.path.join(abs_out, "precedent-index.json"),
        "architecture_inventory": os.path.join(abs_out, "architecture-inventory.json"),
        "symbol_index": os.path.join(abs_out, "symbol-index.json"),
        "call_graph": os.path.join(abs_out, "call-graph.json"),
    }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_signature(root: str, out: str) -> dict | None:
    ignored_out = os.path.relpath(os.path.abspath(os.path.join(root, out)), root)
    ignored_out = ignored_out.replace(os.sep, "/").rstrip("/") or ".simplicio"
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            stdin=subprocess.DEVNULL,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            stdin=subprocess.DEVNULL,
        )
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                ".",
                f":!{ignored_out}",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if head.returncode != 0 or status.returncode != 0:
        return None
    tree = _tree_signature(root, out)
    return {
        "kind": "git",
        "head": head.stdout.strip(),
        "status_hash": _hash_text(status.stdout),
        "tree_hash": tree.get("hash"),
    }


def _tree_signature(root: str, out: str) -> dict:
    digest = hashlib.sha256()
    abs_out = os.path.abspath(os.path.join(root, out))
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in FRESHNESS_SKIP_DIRS
            and os.path.abspath(os.path.join(current, d)) != abs_out
            and not _is_internal_worktree_dir(current, d)
        ]
        for name in sorted(files):
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return {"kind": "tree", "hash": digest.hexdigest()}


def _freshness_signature(root: str, out: str) -> dict:
    return _git_signature(root, out) or _tree_signature(root, out)


def _read_index_state(root: str, out: str) -> dict:
    return _read_json_safe(_state_path(root, out))


def _write_index_state(root: str, out: str, signature: dict, counts: dict | None = None) -> None:
    path = _state_path(root, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "schema": INDEX_STATE_SCHEMA,
        "signature": signature,
        "counts": counts or {},
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _artifacts_exist(paths: dict[str, str]) -> bool:
    return all(os.path.exists(path) for path in paths.values())


def _index_result(
    root: str,
    out: str,
    *,
    status: str,
    skipped_reason: str | None = None,
    run_result: dict | None = None,
    counts: dict | None = None,
    error: str | None = None,
) -> dict:
    paths = _artifact_paths(root, out)
    project_map = run_result.get("project_map", {}) if run_result else {}
    precedent_index = run_result.get("precedent_index", {}) if run_result else {}
    architecture_inventory = run_result.get("architecture_inventory", {}) if run_result else {}
    symbol_index = run_result.get("symbol_index", {}) if run_result else {}
    call_graph = run_result.get("call_graph", {}) if run_result else {}
    changed_files = list(project_map.get("changed_files") or [])
    counts = counts or {
        "files": len(project_map.get("files", []) or []),
        "precedents": len(precedent_index.get("items", []) or []),
        "changed_files": len(changed_files),
        "modules": len(architecture_inventory.get("modules", []) or []),
        "layers": len(architecture_inventory.get("layers", []) or []),
        "symbols": len(symbol_index.get("symbols", []) or []),
        "relationships": len(call_graph.get("edges", []) or []),
    }
    payload = {
        "schema": INDEX_RESULT_SCHEMA,
        "status": status,
        "skipped_reason": skipped_reason,
        "paths": {key: path.replace(os.sep, "/") for key, path in paths.items()},
        "counts": counts,
        "changed_files": changed_files,
        "error": error,
    }
    # Only ever present when the caller opted in to canonical reuse (issue
    # #269) -- default `index`/`scan` output is unaffected, byte-for-byte.
    if run_result is not None and "canonical_reuse" in run_result:
        payload["canonical_reuse"] = run_result["canonical_reuse"]
    return payload


_INDEX_COUNT_TAGS = {
    "files": "MEASURED",
    "precedents": "MEASURED",
    "changed_files": "MEASURED",
    "symbols": "MEASURED",
    "relationships": "MEASURED",
    "docs": "MEASURED",
    "modules": "CANON",
    "layers": "CANON",
}

_CONFIDENCE_TAG_LEGEND = {
    "MEASURED": "Read directly off the code on disk this run (AST/regex over real source files).",
    "OPERATOR": "Human/operator supplied the exact number out-of-band; not emitted by this CLI on its own.",
    "CANON": "Derived from doc/README/architecture-convention claims, not a direct code read.",
    "UNVERIFIED": "Not cross-checked against a live run of the mapped system.",
}


def _apply_tagging(payload: dict) -> dict:
    """Attach Asolaria confidence tags to ``payload["counts"]`` (``--tagged``).

    See ``_INDEX_COUNT_TAGS``/``_CONFIDENCE_TAG_LEGEND`` above for the
    MEASURED/OPERATOR/CANON/UNVERIFIED discipline this mirrors from
    Algorithms of Asolaria (issue #150, P0).
    """
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        return payload
    payload = dict(payload)
    payload["confidence_tags"] = {key: _INDEX_COUNT_TAGS.get(key, "UNVERIFIED") for key in counts}
    payload["confidence_tag_legend"] = dict(_CONFIDENCE_TAG_LEGEND)
    return payload


def _apply_confidence_filter(payload: dict, min_tag: str) -> dict:
    """Keep only ``counts`` entries at least as strong as ``min_tag`` (``--confidence``).

    Never silently drops a weaker entry — "no deflate-gate": every filtered
    key is still recorded, with its tag, under ``confidence_filtered_out``.
    """
    tags = payload.get("confidence_tags")
    if not isinstance(tags, dict):
        return payload
    threshold = CONFIDENCE_RANK[min_tag]
    counts = payload.get("counts") or {}
    kept = {}
    dropped = []
    for key, value in counts.items():
        tag = tags.get(key, "UNVERIFIED")
        if CONFIDENCE_RANK.get(tag, len(CONFIDENCE_TAG_ORDER)) <= threshold:
            kept[key] = value
        else:
            dropped.append({"key": key, "tag": tag})
    payload = dict(payload)
    payload["counts"] = kept
    payload["confidence_threshold"] = min_tag
    payload["confidence_filtered_out"] = dropped
    return payload


_FNV_OFFSET_BASIS_64 = 0xCBF29CE484222325

_FNV_PRIME_64 = 0x100000001B3

_FNV_MASK_64 = 0xFFFFFFFFFFFFFFFF


def _fnv1a64_hex(text: str) -> str:
    """FNV-1a, 64-bit variant, as a 16-hex-char string (non-cryptographic hash)."""
    digest = _FNV_OFFSET_BASIS_64
    for byte in text.encode("utf-8"):
        digest ^= byte
        digest = (digest * _FNV_PRIME_64) & _FNV_MASK_64
    return f"{digest:016x}"


def _sha16_hex(text: str) -> str:
    """sha256 truncated to 16 hex chars (8 bytes) — same convention already
    used for this repo's own precedent-index item ids."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _citizen_identity(root: str, key: str) -> str:
    """Stable identity for ``key`` within the federation of mapped repos."""
    repo_name = os.path.basename(os.path.abspath(root or os.getcwd())) or "repo"
    return f"{repo_name}::{key}"


def _apply_geometry(payload: dict, root: str) -> dict:
    """Attach REALMATHPOS/FNV-1a64/sha16/citizenIdentity addressing (``--geometry``).

    Applied per entry in ``payload["paths"]`` (each mapper artifact file).
    ``realmathpos`` degenerates to the artifact file's root position
    (line 1, col 1) rather than a specific symbol position — this CLI's
    `index`/`ask` commands do carry true file:line:col positions for
    individual symbols/routes elsewhere (see the `ask`/`endpoints`
    payloads), which is out of scope for this top-level artifact-address
    pass; see #150 P1 for a per-symbol geometry follow-up.
    """
    paths = payload.get("paths")
    if not isinstance(paths, dict):
        return payload
    geometry = {}
    for key, path in paths.items():
        geometry[key] = {
            "realmathpos": {"file": path, "line": 1, "col": 1},
            "fnv1a64": _fnv1a64_hex(path),
            "sha16": _sha16_hex(path),
            "citizen_identity": _citizen_identity(root, key),
        }
    payload = dict(payload)
    payload["addressing_geometry"] = geometry
    return payload


def _print_toon(payload: dict) -> None:
    """Print ``payload`` as TOON on stdout; log any fallbacks to stderr.

    A silent fallback means an operator has no way to tell how much of the
    payload actually took the token-lean tabular/inline path versus the
    embedded-JSON fallback — issue #148's "log do motivo" requirement.
    ``toon_fallbacks`` mirrors the machine-readable shape used elsewhere in
    the ecosystem (see TOON-CONTRACT.md).
    """
    text, fallbacks = encode_toon_with_report(payload)
    print(text)
    if fallbacks:
        print(json.dumps({"toon_fallbacks": fallbacks}, sort_keys=True), file=sys.stderr)


def _emit_index_json(opts: dict, payload: dict) -> None:
    if opts.get("tagged"):
        payload = _apply_tagging(payload)
        if opts.get("confidence"):
            payload = _apply_confidence_filter(payload, opts["confidence"])
    if opts.get("geometry"):
        payload = _apply_geometry(payload, opts.get("root"))
    if opts.get("for_llm") == "toon":
        _print_toon(payload)
    elif opts["json"]:
        print(json.dumps(payload, sort_keys=True))
