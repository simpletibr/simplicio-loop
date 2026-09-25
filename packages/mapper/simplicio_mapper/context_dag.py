"""simplicio.context-dag/v1 — the incremental Merkle DAG (issue #208, Step 2).

Step 1 (``context_snapshot.py``) gives every node/edge in the ``ContextGraph``
its own, independent content hash. This module chains those hashes into a
Merkle DAG: a node's ``merkle_hash`` folds in the ``merkle_hash`` of every
node it depends on (its outgoing edges), so a change to a leaf dependency
propagates upward through every ancestor's hash without touching anything
outside that dependent cone.

Comparing two DAGs built from consecutive scans is then a pure hash
comparison: any node whose ``merkle_hash`` differs is in the affected cone
(either its own content changed, or something it depends on changed). Nodes
whose hash is unchanged are provably untouched — the counters in
:func:`diff_context_dag` exist precisely so a caller can prove "the cone was
N nodes, not the whole repo's M nodes" rather than assert it.

This module intentionally does not make the mapper's own symbol/call-graph
recomputation lazy (that remains a known, documented limitation — see
AGENTS.md's F10 native-delegation notes for the same shape of tradeoff). It
gives the *addressable, audited* incremental layer on top of whatever the
mapper produced this scan: persisted DAG, append-only change journal with
auditable reason codes, explicit full-invalidation on producer/parser/config
version bumps, and safe recovery from a corrupted DAG file or a truncated
journal (never silently serving stale context).
"""

from __future__ import annotations

import json
import os
from typing import Any

from .context_snapshot import _canonical_hash

CONTEXT_DAG_SCHEMA = "simplicio.context-dag/v1"
JOURNAL_SCHEMA = "simplicio.context-dag-journal/v1"
SCHEMA_VERSION = 1

REASON_NO_PREVIOUS = "no-previous-dag"
REASON_ADDED = "added"
REASON_REMOVED = "removed"
REASON_CONTENT_CHANGED = "content-changed"
REASON_DEPENDENCY_CHANGED = "dependency-changed"
REASON_PRODUCER_VERSION_CHANGED = "producer-version-changed"
REASON_BUILD_CONFIG_CHANGED = "build-config-changed"
REASON_CACHE_CORRUPTED = "cache-corrupted"


# ---------------------------------------------------------------------------
# Merkle hash propagation
# ---------------------------------------------------------------------------


def _dependency_map(graph_dict: dict) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {node["id"]: [] for node in graph_dict.get("nodes", [])}
    for edge in graph_dict.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source in deps and target is not None:
            deps[source].append(target)
    return deps


def _reverse_dependency_map(graph_dict: dict) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = {node["id"]: [] for node in graph_dict.get("nodes", [])}
    for edge in graph_dict.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source is None or target is None:
            continue
        reverse.setdefault(target, []).append(source)
    return reverse


def _scale_counters(nodes: list[dict]) -> dict[str, int]:
    counters = {"micro": 0, "meso": 0, "macro": 0}
    for node in nodes:
        scale = node.get("scale")
        if scale in counters:
            counters[scale] += 1
    return counters


def _event_details(node: dict | None) -> dict[str, Any]:
    if not node:
        return {}
    return {
        "scale": node.get("scale"),
        "source": node.get("source"),
        "content_hash": node.get("content_hash"),
        "merkle_hash": node.get("merkle_hash"),
    }


def compute_merkle_hashes(graph_dict: dict) -> tuple[dict[str, str], set[str]]:
    """Fold each node's content hash with its dependencies' merkle hashes.

    Returns ``(merkle_hash_by_id, degraded_ids)``. ``degraded_ids`` holds any
    node caught in a dependency cycle: it falls back to its own content hash
    (never crashes on a cyclic call graph) and is flagged so a consumer can
    treat its cone membership conservatively.
    """
    nodes_by_id = {node["id"]: node for node in graph_dict.get("nodes", [])}
    deps = _dependency_map(graph_dict)
    memo: dict[str, str] = {}
    in_progress: set[str] = set()
    degraded: set[str] = set()
    external_cache: dict[str, str] = {}

    def resolve(node_id: str) -> str:
        if node_id in memo:
            return memo[node_id]
        node = nodes_by_id.get(node_id)
        if node is None:
            # Dependency points outside the known node set (e.g. an external
            # import) — stable placeholder hash, not a crash.
            if node_id not in external_cache:
                external_cache[node_id] = _canonical_hash({"external": node_id})
            return external_cache[node_id]
        if node_id in in_progress:
            degraded.add(node_id)
            return node["content_hash"]
        in_progress.add(node_id)
        dep_hashes = sorted(resolve(dep_id) for dep_id in deps.get(node_id, []))
        result = _canonical_hash({"content_hash": node["content_hash"], "deps": dep_hashes})
        in_progress.discard(node_id)
        memo[node_id] = result
        return result

    for node_id in nodes_by_id:
        resolve(node_id)
    return memo, degraded


# ---------------------------------------------------------------------------
# Build the DAG
# ---------------------------------------------------------------------------


def build_context_dag(
    graph_dict: dict,
    *,
    build_config_hash: str = "",
    producer: dict | None = None,
    revision: str = "",
) -> dict:
    """Assemble a ``simplicio.context-dag/v1`` payload from a ContextGraph dict."""
    merkle, degraded = compute_merkle_hashes(graph_dict)
    nodes = []
    for node in graph_dict.get("nodes", []):
        nodes.append(
            {
                "id": node["id"],
                "scale": node["scale"],
                "content_hash": node["content_hash"],
                "merkle_hash": merkle[node["id"]],
                "source": node["source"],
                "degraded": node["id"] in degraded,
                "freshness": {
                    "revision": revision,
                    "content_hash": node["content_hash"],
                    "merkle_hash": merkle[node["id"]],
                },
                "fidelity": {
                    "status": "degraded" if node["id"] in degraded else "exact",
                    "reversible": bool(node.get("source")),
                },
            }
        )
    nodes.sort(key=lambda item: (item["scale"], item["id"]))
    edges = sorted(graph_dict.get("edges", []), key=lambda item: item["id"])
    dag_id = _canonical_hash([(node["id"], node["merkle_hash"]) for node in nodes])
    return {
        "schema": CONTEXT_DAG_SCHEMA,
        "version": SCHEMA_VERSION,
        "revision": revision,
        "build_config_hash": build_config_hash,
        "producer": dict(producer or {}),
        "dag_id": dag_id,
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges), **_scale_counters(nodes)},
        "freshness": {
            "revision": revision,
            "build_config_hash": build_config_hash,
            "dag_hash": dag_id,
        },
    }


# ---------------------------------------------------------------------------
# Diff two DAGs -> dependent-cone invalidation with auditable reason codes
# ---------------------------------------------------------------------------


def diff_context_dag(previous: dict | None, current: dict) -> dict:
    """Compare two DAGs; return the affected cone with per-node reason codes.

    A producer/parser-version or build-config change is always a full,
    explicit invalidation (item 4 of the issue #208 Step 2 contract) — it is
    never inferred from node hashes, because a changed producer can affect
    every node's meaning without changing a single content byte.
    """
    if previous is None:
        events = [
            {"op": "add", "id": node["id"], "reason": REASON_NO_PREVIOUS, **_event_details(node)}
            for node in sorted(current.get("nodes", []), key=lambda item: item["id"])
        ]
        return {
            "full_invalidation": True,
            "reason": REASON_NO_PREVIOUS,
            "events": events,
            "counters": {
                "total_nodes": len(current.get("nodes", [])),
                "invalidated": len(events),
                **_scale_counters(current.get("nodes", [])),
            },
        }

    prev_producer = previous.get("producer", {})
    cur_producer = current.get("producer", {})
    if previous.get("build_config_hash", "") != current.get("build_config_hash", ""):
        full_reason = REASON_BUILD_CONFIG_CHANGED
    elif prev_producer.get("version") != cur_producer.get("version") or prev_producer.get(
        "artifact_version"
    ) != cur_producer.get("artifact_version"):
        full_reason = REASON_PRODUCER_VERSION_CHANGED
    else:
        full_reason = None

    cur_nodes = {node["id"]: node for node in current.get("nodes", [])}
    if full_reason is not None:
        events = [
            {"op": "invalidate", "id": node_id, "reason": full_reason, **_event_details(cur_nodes[node_id])}
            for node_id in sorted(cur_nodes)
        ]
        return {
            "full_invalidation": True,
            "reason": full_reason,
            "events": events,
            "counters": {
                "total_nodes": len(cur_nodes),
                "invalidated": len(cur_nodes),
                **_scale_counters(list(cur_nodes.values())),
            },
        }

    prev_nodes = {node["id"]: node for node in previous.get("nodes", [])}
    prev_deps = _dependency_map(previous)
    cur_deps = _dependency_map(current)
    reverse_cur = _reverse_dependency_map(current)
    prev_by_hash: dict[str, list[str]] = {}
    for node_id, node in prev_nodes.items():
        prev_by_hash.setdefault(node["content_hash"], []).append(node_id)

    removed_ids = sorted(prev_nodes.keys() - cur_nodes.keys())
    added_ids = sorted(cur_nodes.keys() - prev_nodes.keys())
    common_ids = prev_nodes.keys() & cur_nodes.keys()

    removed_set = set(removed_ids)
    rename_hints: dict[str, str] = {}
    for added_id in added_ids:
        candidates = [
            rid for rid in prev_by_hash.get(cur_nodes[added_id]["content_hash"], []) if rid in removed_set
        ]
        if candidates:
            rename_hints[added_id] = candidates[0]
            removed_set.discard(candidates[0])

    events = []
    for node_id in removed_ids:
        events.append(
            {"op": "remove", "id": node_id, "reason": REASON_REMOVED, **_event_details(prev_nodes[node_id])}
        )
    for node_id in added_ids:
        event: dict[str, Any] = {
            "op": "add",
            "id": node_id,
            "reason": REASON_ADDED,
            **_event_details(cur_nodes[node_id]),
        }
        if node_id in rename_hints:
            event["rename_hint"] = rename_hints[node_id]
            event["caused_by"] = [{"op": "rename", "id": rename_hints[node_id]}]
        events.append(event)

    invalidated = []
    for node_id in sorted(common_ids):
        prev_node, cur_node = prev_nodes[node_id], cur_nodes[node_id]
        if prev_node["merkle_hash"] == cur_node["merkle_hash"]:
            continue
        invalidated.append(node_id)
        reason = (
            REASON_CONTENT_CHANGED
            if prev_node["content_hash"] != cur_node["content_hash"]
            else REASON_DEPENDENCY_CHANGED
        )
        causes: list[dict[str, Any]] = []
        if reason == REASON_CONTENT_CHANGED:
            causes.append(
                {
                    "op": "content-change",
                    "previous_content_hash": prev_node["content_hash"],
                    "current_content_hash": cur_node["content_hash"],
                }
            )
        else:
            previous_dependencies = set(prev_deps.get(node_id, []))
            current_dependencies = set(cur_deps.get(node_id, []))
            for dep_id in sorted(previous_dependencies - current_dependencies):
                causes.append({"op": "dependency-removed", "id": dep_id})
            for dep_id in sorted(current_dependencies - previous_dependencies):
                cause: dict[str, Any] = {"op": "dependency-added", "id": dep_id}
                if dep_id in rename_hints:
                    cause["rename_hint"] = rename_hints[dep_id]
                causes.append(cause)
            for dep_id in sorted(previous_dependencies & current_dependencies):
                prev_dep = prev_nodes.get(dep_id)
                cur_dep = cur_nodes.get(dep_id)
                if prev_dep is None or cur_dep is None:
                    continue
                if prev_dep["merkle_hash"] != cur_dep["merkle_hash"]:
                    causes.append(
                        {
                            "op": "dependency-invalidated",
                            "id": dep_id,
                            "reason": (
                                REASON_CONTENT_CHANGED
                                if prev_dep["content_hash"] != cur_dep["content_hash"]
                                else REASON_DEPENDENCY_CHANGED
                            ),
                        }
                    )
            if not causes:
                for parent_id in sorted(reverse_cur.get(node_id, [])):
                    causes.append({"op": "reachable-from", "id": parent_id})
        events.append(
            {
                "op": "invalidate",
                "id": node_id,
                "reason": reason,
                "caused_by": causes,
                **_event_details(cur_node),
            }
        )

    events.sort(key=lambda item: (item["op"], item["id"]))
    return {
        "full_invalidation": False,
        "reason": None,
        "events": events,
        "counters": {
            "total_nodes": len(cur_nodes),
            "invalidated": len(invalidated),
            "added": len(added_ids),
            "removed": len(removed_ids),
            **_scale_counters(list(cur_nodes.values())),
        },
    }


# ---------------------------------------------------------------------------
# Persistence — atomic writes, fail-closed reads (never trust a corrupt file)
# ---------------------------------------------------------------------------


def save_context_dag(path: str, dag: dict) -> None:
    """Write the DAG atomically: a crash mid-write leaves the old file intact."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(dag, handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp_path, path)


def load_context_dag(path: str) -> tuple[dict | None, str | None]:
    """Load a persisted DAG. Returns ``(dag, None)`` or ``(None, reason_code)``.

    Never raises and never returns a malformed payload: a missing, truncated,
    non-JSON, or schema-mismatched file all degrade to ``(None,
    "cache-corrupted")`` (or ``"no-previous-dag"`` when simply absent) so the
    caller falls back to a full rebuild instead of trusting stale/broken data.
    """
    if not os.path.isfile(path):
        return None, REASON_NO_PREVIOUS
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None, REASON_CACHE_CORRUPTED
    if not isinstance(payload, dict) or payload.get("schema") != CONTEXT_DAG_SCHEMA:
        return None, REASON_CACHE_CORRUPTED
    if not isinstance(payload.get("nodes"), list) or not isinstance(payload.get("edges"), list):
        return None, REASON_CACHE_CORRUPTED
    return payload, None


# ---------------------------------------------------------------------------
# Append-only change journal
# ---------------------------------------------------------------------------


def append_journal_entry(path: str, entry: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        json.dump(entry, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        handle.write("\n")


def read_journal(path: str) -> tuple[list[dict], list[dict]]:
    """Read journal entries, tolerating a truncated trailing line.

    A crash mid-append leaves at most one partial final line; that line is
    skipped and reported in ``diagnostics`` rather than discarding (or
    failing to read) the rest of the journal.
    """
    if not os.path.isfile(path):
        return [], []
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()
    entries: list[dict] = []
    diagnostics: list[dict] = []
    last_index = len(lines) - 1
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            code = "journal-line-truncated" if index == last_index else "journal-line-corrupted"
            diagnostics.append({"code": code, "line": index + 1})
    return entries, diagnostics


# ---------------------------------------------------------------------------
# Orchestration: build + diff + persist in one call
# ---------------------------------------------------------------------------


def update_context_dag(
    root: str,
    graph_dict: dict,
    *,
    out: str = ".simplicio",
    build_config_hash: str = "",
    producer: dict | None = None,
    revision: str = "",
) -> dict:
    """Build the current DAG, diff it against the persisted one, and persist.

    Returns ``{"dag": <current dag>, "diff": <diff_context_dag result>,
    "journal_entry": <appended entry>}``. The journal entry is appended
    before the new DAG is written, so a crash between the two leaves the
    journal as the more complete record (the old DAG on disk is still valid
    and :func:`load_context_dag` will simply treat it as "no newer diff yet").
    """
    abs_root = os.path.abspath(root)
    dag_path = os.path.join(abs_root, out, "context-dag.json")
    journal_path = os.path.join(abs_root, out, "context-dag-journal.jsonl")

    previous, load_reason = load_context_dag(dag_path)
    current = build_context_dag(
        graph_dict, build_config_hash=build_config_hash, producer=producer, revision=revision
    )
    if previous is None:
        diff = diff_context_dag(None, current)
        if load_reason == REASON_CACHE_CORRUPTED:
            diff = dict(diff, reason=REASON_CACHE_CORRUPTED)
    else:
        diff = diff_context_dag(previous, current)

    entry = {
        "schema": JOURNAL_SCHEMA,
        "version": SCHEMA_VERSION,
        "revision": revision,
        "base_dag_id": (previous or {}).get("dag_id", ""),
        "dag_id": current["dag_id"],
        "full_invalidation": diff["full_invalidation"],
        "reason": diff["reason"],
        "counters": diff["counters"],
        "events": diff["events"],
    }
    append_journal_entry(journal_path, entry)
    save_context_dag(dag_path, current)
    return {"dag": current, "diff": diff, "journal_entry": entry}


__all__ = [
    "CONTEXT_DAG_SCHEMA",
    "JOURNAL_SCHEMA",
    "REASON_ADDED",
    "REASON_BUILD_CONFIG_CHANGED",
    "REASON_CACHE_CORRUPTED",
    "REASON_CONTENT_CHANGED",
    "REASON_DEPENDENCY_CHANGED",
    "REASON_NO_PREVIOUS",
    "REASON_PRODUCER_VERSION_CHANGED",
    "REASON_REMOVED",
    "append_journal_entry",
    "build_context_dag",
    "compute_merkle_hashes",
    "diff_context_dag",
    "load_context_dag",
    "read_journal",
    "save_context_dag",
    "update_context_dag",
]
