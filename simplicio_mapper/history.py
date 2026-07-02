"""Documentation history: append-only snapshots + semantic delta (F6).

Each call to :func:`maybe_snapshot` compares a compact semantic digest of
the current tree (modules, layers, cross-module dependencies, flows,
symbols) against the last stored snapshot. A new snapshot is written only
when the digest changed — ``map`` runs with no real delta never grow
``.simplicio/history/``. Snapshots are append-only; garbage collection only
ever removes the *oldest* snapshots once ``retention`` is exceeded (see
YOOL_TUPLE_HAMT.md §11.2 disk guardrail).

Emits ``simplicio.doc-history/v1`` deltas as documented in
``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from typing import Any

import orjson

from .flows import build_flow_inventory
from .mapper import _now_iso, build_artifacts

DOC_HISTORY_SCHEMA = "simplicio.doc-history/v1"
DOC_HISTORY_INDEX_SCHEMA = "simplicio.doc-history-index/v1"
DOC_HISTORY_VERSION = 1
DEFAULT_RETENTION_COUNT = 50

_JSON_OPTS = orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE


def _history_dir(cwd: str, out_dir: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(cwd, out_dir)), "history")


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(orjson.dumps(data, option=_JSON_OPTS))
    os.replace(tmp, path)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "rb") as handle:
            return orjson.loads(handle.read())
    except (OSError, ValueError):
        return None


def _hash_obj(data: Any) -> str:
    return hashlib.sha256(orjson.dumps(data, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _git_head(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _digest_from_artifacts(cwd: str, artifacts: dict) -> dict:
    inventory = artifacts["architecture_inventory"]
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    flow_inventory = build_flow_inventory(cwd, artifacts)

    modules = {module["name"]: module["file_count"] for module in inventory.get("modules", [])}
    layers = {layer["name"]: layer["file_count"] for layer in inventory.get("layers", [])}
    dependency_pairs = set()
    for edge in call_graph.get("edges", []):
        if edge.get("type") != "imports":
            continue
        source_file, target_file = edge.get("source_file"), edge.get("target_file")
        if not source_file or not target_file:
            continue
        source = source_file.split("/", 1)[0] if "/" in source_file else "."
        target = target_file.split("/", 1)[0] if "/" in target_file else "."
        if source != target:
            dependency_pairs.add((source, target))
    symbols = sorted({symbol["qualified_name"] for symbol in symbol_index.get("symbols", [])})
    flows = sorted(flow["id"] for flow in flow_inventory.get("flows", []))
    flow_effects = {
        flow["id"]: sorted(f"{effect['type']}:{effect['evidence']['path']}" for effect in flow["effects"])
        for flow in flow_inventory.get("flows", [])
    }
    return {
        "modules": modules,
        "layers": layers,
        "dependencies": sorted(list(pair) for pair in dependency_pairs),
        "symbols": symbols,
        "flows": flows,
        "flow_effects": flow_effects,
    }


def _compute_delta(previous: dict | None, current: dict) -> dict:
    previous = previous or {}
    prev_modules = previous.get("modules", {})
    curr_modules = current.get("modules", {})
    modules_added = sorted(set(curr_modules) - set(prev_modules))
    modules_removed = sorted(set(prev_modules) - set(curr_modules))
    modules_changed = [
        {"module": name, "files_delta": curr_modules[name] - prev_modules.get(name, 0)}
        for name in sorted(set(curr_modules) & set(prev_modules))
        if curr_modules[name] != prev_modules.get(name)
    ]

    prev_deps = {tuple(pair) for pair in previous.get("dependencies") or []}
    curr_deps = {tuple(pair) for pair in current.get("dependencies") or []}

    prev_flows = set(previous.get("flows") or [])
    curr_flows = set(current.get("flows") or [])
    prev_flow_effects = previous.get("flow_effects", {})
    curr_flow_effects = current.get("flow_effects", {})
    flows_changed = sorted(
        fid for fid in curr_flows & prev_flows
        if curr_flow_effects.get(fid) != prev_flow_effects.get(fid)
    )

    prev_symbols = set(previous.get("symbols") or [])
    curr_symbols = set(current.get("symbols") or [])

    prev_layers = previous.get("layers", {})
    curr_layers = current.get("layers", {})
    layers_changed = sorted(
        name for name in set(curr_layers) | set(prev_layers)
        if curr_layers.get(name) != prev_layers.get(name)
    )

    return {
        "schema": DOC_HISTORY_SCHEMA,
        "version": DOC_HISTORY_VERSION,
        "modules": {
            "added": modules_added,
            "removed": modules_removed,
            "changed": modules_changed,
        },
        "dependencies": {
            "added": sorted(list(pair) for pair in (curr_deps - prev_deps)),
            "removed": sorted(list(pair) for pair in (prev_deps - curr_deps)),
        },
        "flows": {
            "added": sorted(curr_flows - prev_flows),
            "removed": sorted(prev_flows - curr_flows),
            "changed": flows_changed,
        },
        "symbols": {
            "added": len(curr_symbols - prev_symbols),
            "removed": len(prev_symbols - curr_symbols),
        },
        "layers": {"changed": layers_changed},
    }


def _summarize_delta(delta: dict) -> str:
    parts = []
    if delta["modules"]["added"]:
        parts.append(f"+{len(delta['modules']['added'])} module(s)")
    if delta["modules"]["removed"]:
        parts.append(f"-{len(delta['modules']['removed'])} module(s)")
    if delta["dependencies"]["added"] or delta["dependencies"]["removed"]:
        parts.append(
            f"+{len(delta['dependencies']['added'])}/-{len(delta['dependencies']['removed'])} dependency edge(s)"
        )
    if delta["flows"]["added"] or delta["flows"]["removed"]:
        parts.append(f"+{len(delta['flows']['added'])}/-{len(delta['flows']['removed'])} flow(s)")
    if delta["symbols"]["added"] or delta["symbols"]["removed"]:
        parts.append(f"{delta['symbols']['added']} symbol(s) added, {delta['symbols']['removed']} removed")
    return "; ".join(parts) or "no semantic change"


def _gc(history_dir: str, snapshots: list[dict], retention: int) -> list[str]:
    removed = []
    while len(snapshots) > max(retention, 0):
        victim = snapshots.pop(0)
        victim_dir = os.path.join(history_dir, victim["id"])
        if os.path.isdir(victim_dir):
            for name in os.listdir(victim_dir):
                try:
                    os.remove(os.path.join(victim_dir, name))
                except OSError:
                    pass
            try:
                os.rmdir(victim_dir)
            except OSError:
                pass
        removed.append(victim["id"])
    return removed


def create_snapshot(
    cwd: str,
    out_dir: str = ".simplicio",
    trigger: str = "map",
    retention: int = DEFAULT_RETENTION_COUNT,
    artifacts: dict | None = None,
) -> dict | None:
    """Create a new append-only history snapshot if the tree's semantic
    digest changed since the last snapshot. Returns ``None`` (no-op) when
    nothing changed, so unrelated ``map`` runs never grow the history."""
    abs_cwd = os.path.abspath(cwd)
    history_dir = _history_dir(abs_cwd, out_dir)
    index_path = os.path.join(history_dir, "index.json")
    index = _read_json(index_path) or {"schema": DOC_HISTORY_INDEX_SCHEMA, "snapshots": []}
    snapshots: list[dict] = index["snapshots"]

    artifacts = artifacts if artifacts is not None else build_artifacts(abs_cwd, output_dir=out_dir)
    digest = _digest_from_artifacts(abs_cwd, artifacts)
    digest_hash = _hash_obj(digest)

    if snapshots and snapshots[-1]["digest_hash"] == digest_hash:
        return None

    generated_at = artifacts["project_map"].get("generated_at") or _now_iso()
    snapshot_id = f"{re.sub(r'[^0-9A-Za-z]+', '-', generated_at).strip('-')}_{digest_hash[:8]}"
    snapshot_dir = os.path.join(history_dir, snapshot_id)

    previous_digest = None
    if snapshots:
        previous_digest = _read_json(os.path.join(history_dir, snapshots[-1]["id"], "digest.json"))
    delta = _compute_delta(previous_digest, digest)
    summary = _summarize_delta(delta)

    manifest = {
        "schema": "simplicio.doc-history-manifest/v1",
        "id": snapshot_id,
        "created_at": generated_at,
        "trigger": trigger,
        "git_head": _git_head(abs_cwd),
        "digest_hash": digest_hash,
        "artifact_hashes": {
            name: _hash_obj(artifacts[name])
            for name in ("project_map", "architecture_inventory", "symbol_index", "call_graph")
        },
    }
    _write_json(os.path.join(snapshot_dir, "manifest.json"), manifest)
    _write_json(os.path.join(snapshot_dir, "digest.json"), digest)
    _write_json(os.path.join(snapshot_dir, "delta.json"), delta)

    entry = {"id": snapshot_id, "created_at": generated_at, "trigger": trigger, "digest_hash": digest_hash, "summary": summary}
    snapshots.append(entry)
    removed = _gc(history_dir, snapshots, retention)
    _write_json(index_path, index)

    return {**entry, "delta": delta, "removed": removed}


def render_changelog_entry(entry: dict) -> str:
    return (
        f"## {entry['created_at']} — `{entry['id']}`\n\n"
        f"- Trigger: {entry.get('trigger', 'map')}\n"
        f"- {entry['summary']}\n"
    )


def append_changelog(cwd: str, out_dir: str, entry: dict) -> str:
    """Append (never rewrite) one entry to architecture-changelog.md."""
    changelog_path = os.path.join(os.path.abspath(os.path.join(cwd, out_dir)), "docs", "architecture-changelog.md")
    os.makedirs(os.path.dirname(changelog_path), exist_ok=True)
    rendered = render_changelog_entry(entry)
    if os.path.exists(changelog_path):
        with open(changelog_path, "a", encoding="utf-8") as handle:
            handle.write("\n" + rendered)
    else:
        header = (
            "# Architecture Changelog\n\n"
            "Append-only. Each entry is a `.simplicio/history/` snapshot created "
            "by `map`/`update`/`sync` when the tree's semantic digest changed.\n\n"
        )
        with open(changelog_path, "w", encoding="utf-8") as handle:
            handle.write(header + rendered)
    return changelog_path


def maybe_snapshot(
    cwd: str,
    out_dir: str = ".simplicio",
    trigger: str = "map",
    retention: int = DEFAULT_RETENTION_COUNT,
    artifacts: dict | None = None,
) -> dict | None:
    """Create a snapshot if needed and append its changelog entry."""
    result = create_snapshot(cwd, out_dir=out_dir, trigger=trigger, retention=retention, artifacts=artifacts)
    if result is not None:
        append_changelog(cwd, out_dir, result)
    return result


def list_snapshots(cwd: str, out_dir: str = ".simplicio") -> list[dict]:
    index = _read_json(os.path.join(_history_dir(cwd, out_dir), "index.json")) or {"snapshots": []}
    return index["snapshots"]


def diff_snapshots(cwd: str, out_dir: str, from_id: str, to_id: str) -> dict:
    history_dir = _history_dir(cwd, out_dir)
    from_digest = _read_json(os.path.join(history_dir, from_id, "digest.json"))
    to_digest = _read_json(os.path.join(history_dir, to_id, "digest.json"))
    if from_digest is None or to_digest is None:
        missing = from_id if from_digest is None else to_id
        raise ValueError(f"unknown snapshot id: {missing}")
    delta = _compute_delta(from_digest, to_digest)
    delta["from"] = from_id
    delta["to"] = to_id
    return delta
