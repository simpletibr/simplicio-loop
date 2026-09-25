"""simplicio.context-snapshot/v1 — the ecosystem's canonical observer output (issue #208).

The mapper becomes the canonical observer of the Simplicio ecosystem. Instead
of emitting a pile of loosely-related ``.simplicio/*.json`` artifacts that each
consumer re-parses ad hoc, it now emits a single versioned, content-addressed,
sufficiently-faithful ``ContextSnapshot`` plus a ``ContextGraph`` that links the
micro (symbols/spans), meso (modules/flows) and macro (subsystems/ADRs) scales.

This module is the *identity + schema + assembly* slice of issue #208 (Step 1:
"Schema e identidade"). It does not yet cover the incremental Merkle DAG, the
coarse-graining multi-scale engine, the task-conditioned selection, or the
fidelity gate — those are later steps that consume this stable foundation.

Design invariants (from the issue contract):

* Identity is content-addressed. ``snapshot_id`` is a sha256 over the canonical
  serialization of the *addressable* payload, never over mtime or absolute
  path. The same repo at the same revision with the same producer produces the
  same ``snapshot_id``; one changed source byte changes it.
* Every node and edge carries a ``content_hash`` and a reversible ``source``
  handle (``file`` + ``line``/``span``) so any summary can be expanded back to
  the exact source that justifies it. A summary without a source handle is
  invalid by construction — we never emit one.
* Serialization is canonical: sorted keys, stable separators, UTF-8. Two
  snapshots that describe the same content always produce byte-identical JSON.
* No new dependency is introduced: hashing/serialization use only the stdlib
  (``hashlib``).

The wheel *includes* these schemas (see ``pyproject.toml`` ``[tool.hatch.build
.targets.wheel.force-include]``), so ``from_package()`` resolves them from an
installed package — a clean install can validate a snapshot without a checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from typing import Any

from . import __version__
from .context_contract import MAX_SNAPSHOT_BYTES
from .mapper import ARTIFACT_VERSION, _now_iso
from .relations import canonicalize_relation, relation_coverage

CONTEXT_SNAPSHOT_SCHEMA = "simplicio.context-snapshot/v1"
CONTEXT_GRAPH_SCHEMA = "simplicio.context-graph/v1"
SCHEMA_VERSION = "v1"

# Where the shipped schemas live inside the installed package.
_PACKAGED_SCHEMAS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "contracts", "context-snapshot", "v1", "schemas"
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    """Canonical JSON serialization: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(value: Any) -> str:
    """Content hash of any JSON-serializable structure (canonical form)."""
    return _sha256_text(_stable_json(value))


def _content_hash_str(text: str) -> str:
    return _sha256_text(text)


# ---------------------------------------------------------------------------
# Source handles + reversible references
# ---------------------------------------------------------------------------


def source_handle(file: str, *, line: int | None = None, span: tuple[int, int] | None = None) -> dict:
    """Build a reversible source handle for a snapshot node/edge.

    Every emitted node/edge must carry one of these so a consumer can expand
    the summary back to the exact originating source (issue #208 contract:
    "handles reversíveis para expandir qualquer resumo até a fonte").
    """
    handle: dict[str, Any] = {"file": file.replace(os.sep, "/")}
    if span is not None:
        handle["span"] = [int(span[0]), int(span[1])]
    elif line is not None:
        handle["line"] = int(line)
    return handle


# ---------------------------------------------------------------------------
# ContextGraph — the multi-scale, content-addressed graph
# ---------------------------------------------------------------------------


class ContextGraph:
    """Assembles micro/meso/macro graph handles with per-node/edge content hashes.

    Not a full graph database: it is the *addressable index* the snapshot
    carries. Each node/edge records its logical id, its content hash, its
    source handle, and (for edges) the kind + endpoints. Consumers resolve a
    handle to the underlying mapper artifact (project-map / symbol-index /
    call-graph / architecture-inventory) to expand it.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, dict] = {}
        self._edges: dict[str, dict] = {}
        self._relation_coverage: dict[str, Any] = {}

    def set_relation_coverage(self, coverage: Mapping[str, Any] | None) -> None:
        """Attach producer coverage so omitted graph edges stay observable."""
        self._relation_coverage = dict(coverage or {})

    def add_node(self, scale: str, node_id: str, *, content: Any, source: dict) -> str:
        """Register a node; returns its content hash.

        ``scale`` is one of ``micro`` / ``meso`` / ``macro``. ``content`` is the
        JSON-serializable payload the node addresses (the consumer expands it by
        hashing the same content from the source artifact). ``source`` is a
        handle from :func:`source_handle`.
        """
        content_hash = _canonical_hash(content)
        key = f"{scale}:{node_id}"
        self._nodes[key] = {
            "id": node_id,
            "scale": scale,
            "content_hash": content_hash,
            "source": source,
        }
        return content_hash

    def add_edge(
        self,
        *,
        kind: str,
        source_id: str,
        target_id: str,
        content: Any,
        source: dict,
        confidence: float | None = None,
        relation_id: str | None = None,
        evidence_class: str | None = None,
        resolution_status: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        target_candidates: list[str] | None = None,
    ) -> str:
        """Register a causal/dependency edge; returns its content hash."""
        content_hash = _canonical_hash(content)
        edge_id = relation_id or _canonical_hash({"kind": kind, "source": source_id, "target": target_id})
        self._edges[edge_id] = {
            "id": edge_id,
            "kind": kind,
            "source": source_id,
            "target": target_id,
            "content_hash": content_hash,
            "source_handle": source,
        }
        if confidence is not None:
            self._edges[edge_id]["confidence"] = float(confidence)
        if relation_id is not None:
            self._edges[edge_id]["relation_id"] = relation_id
        if evidence_class is not None:
            self._edges[edge_id]["evidence_class"] = evidence_class
        if resolution_status is not None:
            self._edges[edge_id]["resolution_status"] = resolution_status
        if provenance is not None:
            self._edges[edge_id]["provenance"] = dict(provenance)
        if target_candidates is not None:
            self._edges[edge_id]["target_candidates"] = list(target_candidates)
        return content_hash

    def to_dict(self) -> dict:
        nodes = [self._nodes[key] for key in sorted(self._nodes)]
        edges = [self._edges[key] for key in sorted(self._edges)]
        return {
            "schema": CONTEXT_GRAPH_SCHEMA,
            "version": 1,
            "nodes": nodes,
            "edges": edges,
            "relation_coverage": dict(self._relation_coverage),
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "micro": sum(1 for n in nodes if n["scale"] == "micro"),
                "meso": sum(1 for n in nodes if n["scale"] == "meso"),
                "macro": sum(1 for n in nodes if n["scale"] == "macro"),
            },
            "scale_semantics": _scale_semantics(),
            "drilldown": {
                "reversible": True,
                "node_source_field": "source",
                "edge_source_field": "source_handle",
            },
        }


# ---------------------------------------------------------------------------
# Build from the canonical mapper artifacts
# ---------------------------------------------------------------------------

_MICRO_KINDS = {"symbol", "span"}
_MESO_KINDS = {"module", "flow", "file"}
_MACRO_KINDS = {"subsystem", "adr"}


def _scale_semantics() -> dict[str, dict[str, Any]]:
    return {
        "micro": {
            "kinds": sorted(_MICRO_KINDS),
            "summary": "symbol- and span-level anchors used for reversible drill-down",
        },
        "meso": {
            "kinds": sorted(_MESO_KINDS),
            "summary": "file/module/flow relationships that stitch local behavior together",
        },
        "macro": {
            "kinds": sorted(_MACRO_KINDS),
            "summary": "subsystem and ADR level structure for coarse-grained navigation",
        },
    }


def _artifact_fingerprint(payload: Mapping[str, Any] | None) -> str:
    return _canonical_hash(payload or {})


def _default_fidelity(omissions: list[str], graph_dict: Mapping[str, Any]) -> dict[str, Any]:
    counts = dict(graph_dict.get("counts", {}))
    return {
        "status": "partial" if omissions else "complete",
        "gate": "needs_broader_context" if omissions else "ready",
        "omissions": list(omissions),
        "coverage": {
            "addressable_nodes": counts.get("nodes", 0),
            "addressable_edges": counts.get("edges", 0),
            "micro": counts.get("micro", 0),
            "meso": counts.get("meso", 0),
            "macro": counts.get("macro", 0),
        },
    }


def _needs_broader_context(omissions: list[str], fidelity_payload: Mapping[str, Any]) -> bool:
    if omissions:
        return True
    if bool(fidelity_payload.get("abstained")):
        return True
    gate = str(fidelity_payload.get("gate", "")).strip().casefold()
    if gate and gate != "ready":
        return True
    status = str(fidelity_payload.get("status", "")).strip().casefold()
    return status in {"partial", "insufficient", "abstained"}


def build_context_graph(
    *,
    project_map: Mapping[str, Any] | None = None,
    symbol_index: Mapping[str, Any] | None = None,
    call_graph: Mapping[str, Any] | None = None,
    architecture_inventory: Mapping[str, Any] | None = None,
) -> ContextGraph:
    """Fold the canonical mapper artifacts into a multi-scale ContextGraph.

    Micro nodes = symbols (from symbol-index). Meso nodes = files + modules.
    Macro nodes = architecture layers/subsystems. Edges = call-graph
    imports/calls (causal/dependency) plus module->layer membership.

    Every node/edge carries a reversible source handle so the consumer can
    expand any summary back to the originating artifact.
    """
    project_map = project_map or {}
    symbol_index = symbol_index or {}
    call_graph = call_graph or {}
    architecture_inventory = architecture_inventory or {}

    graph = ContextGraph()

    # -- micro: symbols --------------------------------------------------
    for symbol in symbol_index.get("symbols", []):
        defined_in = symbol.get("defined_in") or ""
        line = symbol.get("line")
        handle = source_handle(defined_in, line=line) if defined_in else source_handle("<unknown>")
        graph.add_node(
            "micro",
            f"symbol:{symbol.get('qualified_name') or symbol.get('name')}",
            content={
                "name": symbol.get("name"),
                "kind": symbol.get("kind"),
                "defined_in": defined_in,
                "line": line,
            },
            source=handle,
        )
        if defined_in:
            graph.add_edge(
                kind="defined_in",
                source_id=f"symbol:{symbol.get('qualified_name') or symbol.get('name')}",
                target_id=f"file:{defined_in}",
                content={
                    "symbol": symbol.get("qualified_name") or symbol.get("name"),
                    "defined_in": defined_in,
                    "line": line,
                },
                source=handle,
                confidence=1.0,
            )

    # -- meso: files + modules ------------------------------------------
    for file_entry in project_map.get("files", []):
        path = file_entry.get("path", "")
        graph.add_node(
            "meso",
            f"file:{path}",
            content={
                "path": path,
                "language": file_entry.get("language"),
                "roles": file_entry.get("roles", []),
            },
            source=source_handle(path),
        )
    for module in architecture_inventory.get("modules", []):
        name = module.get("name", "")
        graph.add_node(
            "meso",
            f"module:{name}",
            content={
                "name": name,
                "file_count": module.get("file_count"),
                "layers": module.get("layers", []),
            },
            source=source_handle(f"module:{name}"),
        )

    # -- macro: layers/subsystems ---------------------------------------
    for layer in architecture_inventory.get("layers", []):
        name = layer.get("name", "")
        graph.add_node(
            "macro",
            f"subsystem:{name}",
            content={
                "name": name,
                "file_count": layer.get("file_count"),
                "modules": layer.get("modules", []),
            },
            source=source_handle(f"layer:{name}"),
        )
    for adr in architecture_inventory.get("adrs", []):
        adr_id = adr.get("id") or adr.get("path") or adr.get("title") or ""
        if not adr_id:
            continue
        graph.add_node(
            "macro",
            f"adr:{adr_id}",
            content={
                "id": adr.get("id"),
                "title": adr.get("title"),
                "status": adr.get("status"),
                "path": adr.get("path"),
            },
            source=source_handle(adr.get("path") or f"adr:{adr_id}"),
        )

    # -- edges: calls/imports (causal) ----------------------------------
    raw_edges = call_graph.get("edges", [])
    raw_edges = raw_edges if isinstance(raw_edges, list) else []
    graph_coverage = call_graph.get("coverage", {})
    graph_coverage = graph_coverage if isinstance(graph_coverage, Mapping) else {}
    canonical_edges = [
        canonicalize_relation(raw_edge)
        for raw_edge in raw_edges
        if isinstance(raw_edge, Mapping)
    ]
    canonical_edges = [edge for edge in canonical_edges if edge is not None]
    computed_coverage = relation_coverage(
        canonical_edges,
        observed_edges=max(len(raw_edges), int(graph_coverage.get("observed_edges", 0) or 0)),
        edge_limit=graph_coverage.get("edge_limit"),
        invalid_edges=max(
            max(0, len(raw_edges) - len(canonical_edges)),
            int(graph_coverage.get("invalid_edges", 0) or 0),
        ),
    )
    computed_coverage.update(
        {
            key: value
            for key, value in graph_coverage.items()
            if key not in computed_coverage
        }
    )
    if graph_coverage.get("status") == "degraded":
        computed_coverage["status"] = "degraded"
    graph.set_relation_coverage(computed_coverage)
    for edge in canonical_edges:
        etype = edge.get("type")
        src_file = edge.get("source_file")
        tgt_file = edge.get("target_file")
        tgt_symbol = edge.get("target_symbol")
        if not src_file:
            continue
        source_id = f"file:{src_file}"
        if not tgt_file:
            target_id = f"unknown:{edge.get('relation_id')}"
            graph.add_node(
                "meso",
                target_id,
                content={
                    "relation_id": edge.get("relation_id"),
                    "target_file": None,
                    "target_symbol": edge.get("target_symbol"),
                    "evidence_class": edge.get("evidence_class"),
                    "resolution_status": edge.get("resolution_status"),
                },
                source=source_handle(src_file, line=edge.get("line")),
            )
        elif tgt_symbol:
            target_id = f"symbol:{tgt_symbol}"
        else:
            target_id = f"file:{tgt_file}"
        if source_id == target_id:
            continue
        graph.add_edge(
            kind=etype or "depends_on",
            source_id=source_id,
            target_id=target_id,
            content=edge,
            source=source_handle(src_file, line=edge.get("line")),
            confidence=edge.get("confidence"),
            relation_id=edge.get("relation_id"),
            evidence_class=edge.get("evidence_class"),
            resolution_status=edge.get("resolution_status"),
            provenance=edge.get("provenance"),
            target_candidates=edge.get("target_candidates"),
        )

    # -- edges: module -> layer membership (structural) -----------------
    for layer in architecture_inventory.get("layers", []):
        layer_name = layer.get("name", "")
        for module_name in layer.get("modules", []) or []:
            graph.add_edge(
                kind="member_of",
                source_id=f"module:{module_name}",
                target_id=f"subsystem:{layer_name}",
                content={"module": module_name, "layer": layer_name},
                source=source_handle(f"layer:{layer_name}"),
            )

    return graph


# ---------------------------------------------------------------------------
# ContextSnapshot — the versioned, content-addressed envelope
# ---------------------------------------------------------------------------


def _bound_graph(
    graph_dict: dict, max_bytes: int, *, priority_paths: frozenset[str] = frozenset()
) -> tuple[dict, int, int]:
    """Keep a deterministic, relevance-ordered graph prefix within a byte cap.

    Ordering favors relevance over alphabetical id order: nodes whose source
    file is in ``priority_paths`` (the task's selected targets) come first,
    then ``symbol:`` nodes, then everything else — each tier sorted by id for
    determinism. Without this, an alphabetical-only prefix keeps ``file:``
    nodes (which sort before ``symbol:``) and starves the symbol nodes a
    downstream consumer (e.g. simplicio-fast) needs.
    """
    def valid_handle(handle: object) -> bool:
        if not isinstance(handle, dict) or not isinstance(handle.get("file"), str):
            return False
        path = handle["file"]
        try:
            encoded = path.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return (
            0 < len(encoded) <= 4096
            and "\\" not in path
            and not path.startswith("/")
            and ".." not in path.split("/")
        )

    def relevance_tier(node: dict) -> int:
        source = node.get("source")
        path = source.get("file") if isinstance(source, dict) else ""
        is_priority = bool(priority_paths) and path in priority_paths
        is_symbol = str(node.get("id", "")).startswith("symbol:")
        if is_priority and is_symbol:
            return 0
        if is_priority:
            return 1
        if is_symbol:
            return 2
        return 3

    raw_nodes = graph_dict.get("nodes", [])
    raw_nodes = raw_nodes if isinstance(raw_nodes, list) else []
    nodes = sorted(
        (
            node
            for node in raw_nodes
            if isinstance(node, dict)
            and isinstance(node.get("id"), str)
            and valid_handle(node.get("source"))
        ),
        key=lambda node: (relevance_tier(node), node["id"]),
    )
    kept: list[dict] = []
    used = 0
    for node in nodes:
        size = len(_stable_json(node).encode("utf-8")) + (1 if kept else 0)
        if used + size > max_bytes:
            break
        kept.append(node)
        used += size

    ids = {node["id"] for node in kept}
    raw_edges = graph_dict.get("edges", [])
    raw_edges = raw_edges if isinstance(raw_edges, list) else []
    edges: list[dict] = []
    for edge in sorted(
        (edge for edge in raw_edges if isinstance(edge, dict)),
        key=lambda edge: str(edge.get("id", "")),
    ):
        if (
            edge.get("source") not in ids
            or edge.get("target") not in ids
            or not valid_handle(edge.get("source_handle"))
        ):
            continue
        size = len(_stable_json(edge).encode("utf-8")) + (1 if edges else 0)
        if used + size > max_bytes:
            break
        edges.append(edge)
        used += size

    bounded = {**graph_dict, "nodes": kept, "edges": edges}
    bounded["counts"] = {
        "nodes": len(kept),
        "edges": len(edges),
        "micro": sum(node.get("scale") == "micro" for node in kept),
        "meso": sum(node.get("scale") == "meso" for node in kept),
        "macro": sum(node.get("scale") == "macro" for node in kept),
    }
    return bounded, len(raw_nodes) - len(kept), len(raw_edges) - len(edges)

def _bound_paths(paths: list[str], max_bytes: int) -> tuple[list[str], int]:
    """Return a sorted, schema-valid prefix within an incremental byte budget."""
    kept: list[str] = []
    used = 2
    for path in sorted(path for path in paths if isinstance(path, str)):
        encoded = path.encode("utf-8")
        if not encoded or len(encoded) > 4096 or len(kept) == 4096:
            continue
        addition = len(_stable_json(path).encode("utf-8")) + (1 if kept else 0)
        if used + addition > max_bytes:
            break
        kept.append(path)
        used += addition
    return kept, len(paths) - len(kept)

def build_context_snapshot(
    root: str,
    *,
    project_map: Mapping[str, Any] | None = None,
    symbol_index: Mapping[str, Any] | None = None,
    call_graph: Mapping[str, Any] | None = None,
    architecture_inventory: Mapping[str, Any] | None = None,
    revision: str = "",
    build_config_hash: str = "",
    source_set: Iterable[str] | None = None,
    exclusions: Iterable[str] | None = None,
    reason_codes: Mapping[str, str] | None = None,
    task_query: str = "",
    selection_policy: str = "",
    budget_tokens: int = 0,
    confidence: Mapping[str, Any] | None = None,
    fidelity: Mapping[str, Any] | None = None,
    priority_paths: Iterable[str] | None = None,
) -> dict:
    """Assemble a ``simplicio.context-snapshot/v1`` envelope.

    The returned dict is the *addressable* payload. ``snapshot_id`` is computed
    from its canonical serialization (minus ``snapshot_id`` itself), so it is
    content-addressed and deterministic for a given repo state + producer.

    Pass pre-built mapper artifacts; if any is missing we degrade honestly by
    emitting ``omissions`` and a ``needs_broader_context`` flag rather than
    fabricating a faithful snapshot.
    """
    project_map_missing = not bool(project_map)
    omissions: list[str] = []
    project_map = project_map or {}
    symbol_index = symbol_index or {}
    call_graph = call_graph or {}
    architecture_inventory = architecture_inventory or {}

    abs_root = os.path.abspath(root)
    repository_id = project_map.get("product", {}).get("name") or os.path.basename(abs_root)
    raw_sources = source_set or [f.get("path") for f in project_map.get("files", []) if isinstance(f, Mapping)]
    source_paths = sorted(path for path in raw_sources if isinstance(path, str) and 0 < len(path.encode("utf-8")) <= 4096 and "\\" not in path and not path.startswith("/") and ".." not in path.split("/"))
    invalid_sources = len(raw_sources) - len(source_paths)
    if invalid_sources:
        omissions.append(f"invalid-source-paths={invalid_sources}")
    if source_set is None:
        project_map = {**project_map, "files": [f for f in project_map.get("files", []) if isinstance(f, Mapping) and f.get("path") in source_paths]}
    # A clone's absolute path is runtime metadata, not repository identity.
    # Keep root_hash stable across worktrees and machines while still changing
    # when the addressed source/revision changes.
    root_hash = _canonical_hash(
        {
            "repository_id": repository_id,
            "revision": revision or project_map.get("generated_at", ""),
            "source_set": source_paths,
        }
    )

    if project_map_missing:
        omissions.append("project-map")
    if not symbol_index:
        omissions.append("symbol-index")
    if not call_graph:
        omissions.append("call-graph")
    if not architecture_inventory:
        omissions.append("architecture-inventory")

    graph = build_context_graph(
        project_map=project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        architecture_inventory=architecture_inventory,
    )
    graph_dict = graph.to_dict()
    if graph_dict.get("relation_coverage", {}).get("status") == "degraded":
        omissions.append("call-graph-relation-coverage-degraded")
    graph_bytes = len(_stable_json(graph_dict).encode("utf-8"))
    source_bytes = len(_stable_json(source_paths).encode("utf-8"))
    needs_bound = bool(budget_tokens) or len(source_paths) > 4096 or any(len(path) > 4096 for path in source_paths) or graph_bytes + source_bytes > 15 * 1024 * 1024
    omitted_nodes = omitted_edges = omitted_sources = 0
    byte_budget = (
        min(8 * 1024 * 1024, budget_tokens * 4)
        if needs_bound and budget_tokens
        else 8 * 1024 * 1024
        if needs_bound
        else MAX_SNAPSHOT_BYTES
    )
    priority_path_set = frozenset(
        path.replace("\\", "/").lstrip("./") for path in (priority_paths or ()) if isinstance(path, str)
    )
    graph_dict, omitted_nodes, omitted_edges = _bound_graph(
        graph_dict, byte_budget, priority_paths=priority_path_set
    )
    if needs_bound:
        source_paths, omitted_sources = _bound_paths(source_paths, min(7 * 1024 * 1024, byte_budget))
    if omitted_sources:
        omissions.append(f"source-pruned:sources={omitted_sources}")
    if omitted_nodes or omitted_edges:
        omissions.append(f"budget-pruned:nodes={omitted_nodes},edges={omitted_edges}")
    root_hash = _canonical_hash({"repository_id": repository_id, "revision": revision or project_map.get("generated_at", ""), "source_set": source_paths})
    freshness = {
        "root_hash": root_hash,
        "artifact_hashes": {
            "project_map": _artifact_fingerprint(project_map),
            "symbol_index": _artifact_fingerprint(symbol_index),
            "call_graph": _artifact_fingerprint(call_graph),
            "architecture_inventory": _artifact_fingerprint(architecture_inventory),
        },
        "source_count": len(source_paths),
        "graph_hash": _canonical_hash(graph_dict),
    }
    fidelity_payload = _default_fidelity(omissions, graph_dict)
    fidelity_payload.update(dict(fidelity or {}))
    needs_broader_context = _needs_broader_context(omissions, fidelity_payload)

    payload: dict[str, Any] = {
        "schema": CONTEXT_SNAPSHOT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "repository_id": repository_id,
        "revision": revision or project_map.get("generated_at", ""),
        "root_hash": root_hash,
        "build_config_hash": build_config_hash,
        "producer": {
            "name": "simplicio-mapper",
            "version": __version__,
            "artifact_version": ARTIFACT_VERSION,
        },
        "source_set": source_paths,
        "exclusions": sorted(exclusions or []),
        "reason_codes": dict(reason_codes or {}),
        "graph": graph_dict,
        "scale_semantics": _scale_semantics(),
        "drilldown": {
            "reversible": True,
            "preferred_order": ["macro", "meso", "micro"],
            "source_handle_contract": {"node": "source", "edge": "source_handle"},
        },
        "task": {
            "query": task_query,
            "selection_policy": selection_policy,
            "budget_tokens": int(budget_tokens),
            "omissions": omissions,
        },
        "confidence": dict(confidence or {}),
        "fidelity": fidelity_payload,
        "freshness": freshness,
        "generated_at": _now_iso(),
        "needs_broader_context": needs_broader_context,
    }

    # Content-addressed identity: hash the canonical serialization of the
    # addressable payload (everything except snapshot_id), then stamp it in.
    addressable = {key: value for key, value in payload.items() if key not in {"snapshot_id", "generated_at"}}
    payload["snapshot_id"] = _sha256_text(_stable_json(addressable))
    if len(_stable_json(payload).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("context snapshot exceeds 16 MiB contract limit")
    return payload


# ---------------------------------------------------------------------------
# Schema resolution (works from a clean install, not just a checkout)
# ---------------------------------------------------------------------------


def from_package(schema_id: str) -> dict:
    """Return the shipped JSON Schema for ``schema_id``.

    Resolves from the installed-package vendored dir (``simplicio_mapper/
    contracts/context-snapshot``) when present, falling back to the repo's
    source ``contracts/context-snapshot`` when running from a checkout that
    has not been installed yet. This is the clean-install validation path
    required by issue #208 AC ("Wheel e sdist incluem schemas; clean install
    consegue validá-los").
    """
    filename = {
        CONTEXT_SNAPSHOT_SCHEMA: "context-snapshot.schema.json",
        CONTEXT_GRAPH_SCHEMA: "context-graph.schema.json",
    }.get(schema_id)
    if not filename:
        raise FileNotFoundError(f"unknown context-snapshot schema id: {schema_id!r}")
    packaged = os.path.join(_PACKAGED_SCHEMAS_DIR, filename)
    if os.path.isfile(packaged):
        path = packaged
    else:
        repo_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contracts",
            "context-snapshot",
            "v1",
            "schemas",
            filename,
        )
        path = repo_dir
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def snapshot_id_of(payload: dict) -> str:
    """Recompute the content-addressed ``snapshot_id`` for a payload dict.

    Idempotent: stripping any existing ``snapshot_id`` and re-hashing yields the
    same value. Use this to verify a payload has not been tampered with.
    """
    addressable = {k: v for k, v in dict(payload).items() if k not in {"snapshot_id", "generated_at"}}
    return _sha256_text(_stable_json(addressable))


__all__ = [
    "CONTEXT_GRAPH_SCHEMA",
    "CONTEXT_SNAPSHOT_SCHEMA",
    "SCHEMA_VERSION",
    "ContextGraph",
    "build_context_graph",
    "build_context_snapshot",
    "from_package",
    "snapshot_id_of",
    "source_handle",
]
