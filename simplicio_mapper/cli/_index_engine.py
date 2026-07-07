from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

from ..history import append_changelog, create_snapshot
from ..mapper import write_mapping_artifacts
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
    result = write_mapping_artifacts(
        cwd=root,
        meta=meta,
        incremental=opts["incremental"],
        output_dir=opts["out"],
        log=log,
    )
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
            if d not in FRESHNESS_SKIP_DIRS and os.path.abspath(os.path.join(current, d)) != abs_out
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


def _acquire_index_lock(root: str, out: str) -> str | None:
    path = _lock_path(root, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
    return path


def _release_index_lock(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


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
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
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
            if d not in FRESHNESS_SKIP_DIRS and os.path.abspath(os.path.join(current, d)) != abs_out
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
    return {
        "schema": INDEX_RESULT_SCHEMA,
        "status": status,
        "skipped_reason": skipped_reason,
        "paths": {key: path.replace(os.sep, "/") for key, path in paths.items()},
        "counts": counts,
        "changed_files": changed_files,
        "error": error,
    }


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
