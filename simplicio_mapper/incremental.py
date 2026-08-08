"""Deterministic snapshot and graph-delta API (issue #191).

The existing mapper remains the source of graph facts.  This module adds a
small, versioned consumer contract around those facts: snapshots have stable
IDs, and a delta is an ordered set of add/update/remove/invalidate operations.
It deliberately treats a move or rename as remove+add because the path is
part of an entity's identity; this is predictable for consumers and avoids
silently attaching history to the wrong symbol.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .mapper import build_artifacts
from .mapper.file_lock import acquire_lock_at, release_lock_at

SNAPSHOT_SCHEMA = "simplicio.graph-snapshot/v1"
DELTA_SCHEMA = "simplicio.graph-delta/v1"
CONTRACT_VERSION = 1


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(kind: str, path: str, name: str = "") -> str:
    return f"{kind}:{path}:{name}" if name else f"{kind}:{path}"


def _snapshot_entities(artifacts: dict) -> list[dict]:
    project = artifacts["project_map"]
    entities: list[dict] = []
    for file in project.get("files", []):
        path = str(file["path"])
        entities.append({
            "id": _stable_id("file", path),
            "kind": "file",
            "path": path,
            "name": os.path.basename(path),
            "language": file.get("language", ""),
            "content_hash": file.get("file_hash", ""),
            "attributes": {"roles": sorted(file.get("roles") or []), "imports": sorted(file.get("imports") or [])},
        })
    for symbol in artifacts["symbol_index"].get("symbols", []):
        path = str(symbol.get("defined_in", ""))
        qualified = str(symbol.get("qualified_name") or symbol.get("name") or "")
        entities.append({
            "id": _stable_id("symbol", path, qualified),
            "kind": "symbol",
            "path": path,
            "name": symbol.get("name", ""),
            "qualified_name": qualified,
            "language": symbol.get("language", ""),
            "line": symbol.get("line", 0),
            "attributes": {"kind": symbol.get("kind", "")},
        })
    return sorted(entities, key=lambda item: (item["kind"], item["id"]))


def _snapshot_edges(artifacts: dict) -> list[dict]:
    edges = []
    for edge in artifacts["call_graph"].get("edges", []):
        source = edge.get("source_symbol") or edge.get("source_file") or ""
        target = edge.get("target_symbol") or edge.get("target_file") or edge.get("import") or ""
        # Source/target identity, not source position, defines an edge. A
        # harmless line shift must be an update, never remove+add.
        edge_id = _digest({"type": edge.get("type", ""), "source": source, "target": target,
                           "import": edge.get("import", "")})
        edges.append({
            "id": edge_id,
            "type": edge.get("type", ""),
            "source": source,
            "target": target,
            "path": edge.get("source_file", ""),
            "attributes": {key: edge[key] for key in ("confidence", "line", "import") if key in edge},
        })
    return sorted(edges, key=lambda item: item["id"])


def _fingerprint(root: str) -> str:
    entries = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {".git", ".simplicio", "__pycache__", "node_modules"})
        for name in sorted(files):
            path = Path(current, name)
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return _digest(entries)


def initial_snapshot(root: str, *, revision: int | str = 1, meta: dict | None = None) -> dict:
    """Build the initial graph snapshot from the canonical mapper artifacts."""
    root = os.path.abspath(root)
    artifacts = build_artifacts(root, meta=meta)
    entities = _snapshot_entities(artifacts)
    edges = _snapshot_edges(artifacts)
    body = {"entities": entities, "edges": edges}
    return {
        "schema": SNAPSHOT_SCHEMA,
        "version": CONTRACT_VERSION,
        "revision": str(revision) if str(revision).startswith("r") else f"r{int(revision):06d}",
        "snapshot_id": _digest(body),
        "root": root.replace(os.sep, "/"),
        "source_fingerprint": _fingerprint(root),
        "entities": entities,
        "edges": edges,
        "diagnostics": [],
    }


def _event(op: str, item_type: str, item_id: str, *, before=None, after=None, paths=None, reason="") -> dict:
    result = {"order": 0, "op": op, "entity_type": item_type, "id": item_id,
              "affected_paths": sorted(set(paths or [])), "reason": reason}
    if before is not None:
        result["before"] = before
    if after is not None:
        result["after"] = after
    return result


def compute_delta(previous: dict, current: dict, *, changed_paths: list[str] | None = None,
                  diagnostics: list[dict] | None = None) -> dict:
    """Compute a stable, ordered delta between two compatible snapshots."""
    old_entities = {item["id"]: item for item in previous.get("entities", [])}
    new_entities = {item["id"]: item for item in current.get("entities", [])}
    old_edges = {item["id"]: item for item in previous.get("edges", [])}
    new_edges = {item["id"]: item for item in current.get("edges", [])}
    events = []
    for item_id in sorted(old_entities.keys() - new_entities.keys()):
        item = old_entities[item_id]
        events.append(_event("remove", "entity", item_id, before=item, paths=[item.get("path", "")], reason="missing"))
    for item_id in sorted(new_entities.keys() - old_entities.keys()):
        item = new_entities[item_id]
        events.append(_event("add", "entity", item_id, after=item, paths=[item.get("path", "")], reason="new"))
    for item_id in sorted(old_entities.keys() & new_entities.keys()):
        if old_entities[item_id] != new_entities[item_id]:
            item = new_entities[item_id]
            events.append(_event("update", "entity", item_id, before=old_entities[item_id], after=item,
                                 paths=[item.get("path", "")], reason="content-or-metadata-changed"))
    for item_id in sorted(old_edges.keys() - new_edges.keys()):
        item = old_edges[item_id]
        events.append(_event("remove", "edge", item_id, before=item, paths=[item.get("path", "")], reason="missing"))
    for item_id in sorted(new_edges.keys() - old_edges.keys()):
        item = new_edges[item_id]
        events.append(_event("add", "edge", item_id, after=item, paths=[item.get("path", "")], reason="new"))
    for item_id in sorted(old_edges.keys() & new_edges.keys()):
        if old_edges[item_id] != new_edges[item_id]:
            item = new_edges[item_id]
            events.append(_event("update", "edge", item_id, before=old_edges[item_id], after=item,
                                 paths=[item.get("path", "")], reason="relationship-changed"))

    direct_ids = {event["id"] for event in events}
    changed = set(changed_paths or [])
    if changed:
        impacted = set()
        entity_ids_by_reference = {}
        for item in new_entities.values():
            entity_ids_by_reference[item.get("path", "")] = item["id"]
            if item.get("qualified_name"):
                entity_ids_by_reference[item["qualified_name"]] = item["id"]
        for edge in new_edges.values():
            if edge.get("path") in changed or edge.get("target") in changed:
                impacted.update(
                    entity_ids_by_reference[reference]
                    for reference in (edge.get("source"), edge.get("target"))
                    if reference in entity_ids_by_reference
                )
        for item in sorted(new_entities.values(), key=lambda value: value["id"]):
            if item["id"] not in direct_ids and item["id"] in impacted:
                events.append(_event("invalidate", "entity", item["id"], paths=[item.get("path", "")],
                                     reason="dependent-analysis-invalidated"))
    events.sort(key=lambda item: (item["op"], item["entity_type"], item["id"]))
    for order, event in enumerate(events, 1):
        event["order"] = order
    raw_revision = str(previous.get("revision", "r000000"))
    base_revision = raw_revision
    return {
        "schema": DELTA_SCHEMA,
        "version": CONTRACT_VERSION,
        "event_type": "delta",
        "mode": "incremental",
        "base_revision": base_revision,
        "scan_revision": current.get("revision", _next_revision(previous)),
        "full_rescan": False,
        "revision": current.get("revision", _next_revision(previous)),
        "base_snapshot_id": previous.get("snapshot_id", ""),
        "snapshot_id": current.get("snapshot_id", ""),
        "ordering": {"strategy": "op,entity_type,id", "deterministic": True},
        "events": events,
        "affected_paths": sorted(set(changed) | {path for event in events for path in event["affected_paths"] if path}),
        "diagnostics": diagnostics or [],
        "snapshot": current,
        "fallback": {"required": False, "resync": "replace snapshot with the next full snapshot"},
    }


def scan_delta(root: str, previous: dict | None = None, *, changed_paths: list[str] | None = None,
               full_rescan: bool = False) -> dict:
    """Return an initial snapshot or a delta; invalid bases request resync."""
    if previous is None or full_rescan:
        snapshot = initial_snapshot(root)
        snapshot["diagnostics"] = [{"code": "full-rescan", "message": "initial or explicitly requested full snapshot"}]
        return snapshot
    if previous.get("schema") != SNAPSHOT_SCHEMA or previous.get("version") != CONTRACT_VERSION:
        return {"schema": DELTA_SCHEMA, "version": CONTRACT_VERSION, "base_revision": previous.get("revision", "r000000"),
                "revision": _next_revision(previous), "events": [], "affected_paths": [],
                "diagnostics": [{"code": "incompatible-base", "message": "snapshot contract/version is not supported"}],
                "fallback": {"required": True, "command": "simplicio-mapper delta <root> --full-rescan"}}
    current = initial_snapshot(root, revision=_next_revision(previous))
    return compute_delta(previous, current, changed_paths=changed_paths)


def _next_revision(previous: dict | None) -> str:
    value = str((previous or {}).get("revision", "r000000"))
    try:
        return f"r{int(value[1:] if value.startswith('r') else value) + 1:06d}"
    except ValueError:
        return "r000001"


def _run_incremental_scan_locked(root: str, *, out: str = ".simplicio", meta: dict | None = None,
                                  full_rescan: bool = False, changed_paths: list[str] | None = None) -> dict:
    """Persist the consumer base snapshot and emit the v1 event envelope.

    A corrupt or incompatible base is never guessed at: the caller receives a
    ``resync_required`` event and can request ``--full-rescan``.
    """
    root = os.path.abspath(root)
    state_path = os.path.join(root, out, "graph-snapshot.json")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    previous = None
    try:
        with open(state_path, encoding="utf-8") as handle:
            previous = json.load(handle)
    except (OSError, ValueError):
        pass
    if previous is not None and previous.get("schema") != SNAPSHOT_SCHEMA and not full_rescan:
        return {
            "schema": DELTA_SCHEMA, "version": CONTRACT_VERSION,
            "event_type": "resync_required", "mode": "incremental",
            "base_revision": previous.get("revision"), "scan_revision": _next_revision(previous),
            "full_rescan": False, "ordering": {"strategy": "op,entity_type,id", "deterministic": True},
            "resync": {"required": True, "action": "replace_snapshot"}, "events": [], "affected_paths": [],
            "diagnostics": ["incompatible-base"],
            "snapshot": {}, "fallback": {"required": True, "command": "simplicio-mapper delta <root> --full-rescan"},
        }
    if full_rescan or previous is None:
        snapshot = initial_snapshot(root, revision=_next_revision(previous), meta=meta)
        write_json(state_path, snapshot)
        is_resync = bool(full_rescan and previous)
        return {
            "schema": DELTA_SCHEMA, "version": CONTRACT_VERSION,
            "event_type": "resync_required" if is_resync else "initial_snapshot",
            "mode": "full-rescan" if full_rescan else "initial",
            "base_revision": previous.get("revision") if previous else None,
            "scan_revision": snapshot["revision"], "full_rescan": bool(full_rescan),
            "ordering": {"strategy": "op,entity_type,id", "deterministic": True},
            "resync": {"required": is_resync, "action": "replace_snapshot" if is_resync else "store_snapshot"},
            "events": [_event("add", "entity", item["id"], after=item, paths=[item.get("path", "")], reason="initial") for item in snapshot["entities"]],
            "affected_paths": sorted(item["path"] for item in snapshot["entities"] if item.get("path")),
            "diagnostics": ["full-rescan" if full_rescan else "initial-snapshot"], "snapshot": snapshot,
        }
    current = initial_snapshot(root, revision=_next_revision(previous), meta=meta)
    if changed_paths is None:
        probe = compute_delta(previous, current)
        changed_paths = sorted({path for event in probe["events"] for path in event.get("affected_paths", []) if path})
    delta = compute_delta(previous, current, changed_paths=changed_paths)
    write_json(state_path, current)
    return {
        "schema": DELTA_SCHEMA, "version": CONTRACT_VERSION, "event_type": "delta", "mode": "incremental",
        "base_revision": previous["revision"], "scan_revision": current["revision"], "full_rescan": False,
        "ordering": delta["ordering"], "resync": {"required": False, "action": "apply_events"},
        "events": delta["events"], "affected_paths": delta["affected_paths"],
        "diagnostics": delta["diagnostics"], "snapshot": current,
    }


def run_incremental_scan(root: str, *, out: str = ".simplicio", meta: dict | None = None,
                         full_rescan: bool = False, changed_paths: list[str] | None = None) -> dict:
    """Serialize incremental writers and return a truthful lock receipt."""
    resolved = os.path.abspath(root)
    lock_path = os.path.join(resolved, out, "graph-snapshot.lock")
    lock = acquire_lock_at(lock_path, operation="incremental-scan")
    if lock is None:
        return {
            "schema": DELTA_SCHEMA,
            "version": CONTRACT_VERSION,
            "event_type": "blocked",
            "mode": "incremental",
            "full_rescan": bool(full_rescan),
            "ordering": {"strategy": "op,entity_type,id", "deterministic": True},
            "events": [],
            "affected_paths": [],
            "diagnostics": [{"code": "incremental_lock_held", "lock_path": lock_path.replace(os.sep, "/")}],
            "fallback": {"required": True, "action": "retry_after_lock_release"},
        }
    try:
        return _run_incremental_scan_locked(
            resolved, out=out, meta=meta, full_rescan=full_rescan, changed_paths=changed_paths
        )
    finally:
        release_lock_at(lock)


def write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
