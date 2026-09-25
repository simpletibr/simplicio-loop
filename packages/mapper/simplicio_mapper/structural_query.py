"""Bounded, read-only queries over the canonical structural graph."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .structural_graph import EdgeKind, GraphNode, NodeKind, StructuralGraph
from .structural_parser import Coverage


QUERY_SCHEMA = "simplicio.graph-query/v1"
_MATCH = re.compile(
    r"^MATCH\s*\(n(?::(?P<nkind>[a-z_]+))?\)\s*(?:-\[:(?P<edge>[a-z_]+)\]->\s*\(m(?::(?P<mkind>[a-z_]+))?\))?\s*"
    r"(?:WHERE\s+n\.name\s*=\s*['\"](?P<name>[^'\"]+)['\"]\s*)?"
    r"RETURN\s+(?P<return>.+?)(?:\s+LIMIT\s+(?P<limit>\d+))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QueryResponse:
    operation: str
    generation_id: str
    results: tuple[dict[str, Any], ...]
    truncated: bool = False
    omitted_count: int = 0
    coverage: dict[str, Any] | None = None
    explain: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUERY_SCHEMA,
            "operation": self.operation,
            "generation_id": self.generation_id,
            "results": list(self.results),
            "truncated": self.truncated,
            "omitted_count": self.omitted_count,
            "coverage": self.coverage,
            "explain": self.explain,
        }


class StructuralQueryEngine:
    def __init__(self, graph: StructuralGraph, coverage: Iterable[Coverage] = ()) -> None:
        self.graph = graph
        self.coverage = tuple(coverage)
        self._coverage_by_path = {item.path: item for item in self.coverage}

    def _coverage_summary(self) -> dict[str, Any]:
        if not self.coverage:
            return {"files": 0, "complete": False, "confidence": 0.0, "negative_claims_allowed": False}
        confidence = sum(item.confidence for item in self.coverage) / len(self.coverage)
        complete = all(item.complete for item in self.coverage)
        return {
            "files": len(self.coverage),
            "complete": complete,
            "confidence": round(confidence, 6),
            "negative_claims_allowed": complete,
            "syntax_errors": sum(len(item.syntax_errors) for item in self.coverage),
            "unsupported_constructs": sorted({value for item in self.coverage for value in item.unsupported_constructs}),
        }

    @staticmethod
    def _node(node: GraphNode) -> dict[str, Any]:
        return {
            "id": node.node_id,
            "kind": node.kind.value,
            "name": node.qualified_name,
            "path": node.path,
            "language": node.language,
            "range": [node.start_line, node.end_line],
            "confidence": node.confidence,
            "provenance": node.provenance,
        }

    def _response(self, operation: str, rows: Iterable[dict[str, Any]], *, limit: int = 20, explain: dict[str, Any] | None = None) -> QueryResponse:
        ordered = sorted(rows, key=lambda row: (str(row.get("id", "")), json.dumps(row, sort_keys=True, ensure_ascii=False)))
        selected = tuple(ordered[: max(0, limit)])
        return QueryResponse(operation, self.graph.generation_id, selected, len(ordered) > len(selected), max(0, len(ordered) - len(selected)), self._coverage_summary(), explain)

    def search_graph(self, *, kind: NodeKind | None = None, name: str | None = None, path: str | None = None, language: str | None = None, limit: int = 20, offset: int = 0) -> QueryResponse:
        rows = [self._node(node) for node in self.graph.nodes if (kind is None or node.kind == kind) and (name is None or name.casefold() in node.qualified_name.casefold()) and (path is None or node.path == path) and (language is None or node.language == language)]
        rows.sort(key=lambda row: (row["name"], row["id"]))
        selected = rows[max(0, offset) : max(0, offset) + max(0, limit)]
        return QueryResponse("search_graph", self.graph.generation_id, tuple(selected), len(rows) > len(selected) + max(0, offset), max(0, len(rows) - len(selected) - max(0, offset)), self._coverage_summary(), {"candidate_count": len(rows), "offset": offset, "limit": limit})

    def trace_path(self, start_id: str, *, target_id: str | None = None, edge_kind: EdgeKind | None = None, inbound: bool = False, depth: int = 3, limit: int = 20) -> QueryResponse:
        if self.graph.get(start_id) is None:
            return self._response("trace_path", (), limit=limit, explain={"error": "unknown_start_id"})
        paths: list[dict[str, Any]] = []
        queue: deque[tuple[str, tuple[str, ...]]] = deque([(start_id, (start_id,))])
        while queue and len(paths) < max(limit * 4, limit):
            current, path = queue.popleft()
            if len(path) > 1 and (target_id is None or current == target_id):
                paths.append({"id": hashlib.sha256("/".join(path).encode()).hexdigest()[:32], "path": list(path), "depth": len(path) - 1})
                if target_id is not None and current == target_id:
                    continue
            if len(path) - 1 >= max(0, depth):
                continue
            for neighbor in self.graph.neighbors(current, edge_kind=edge_kind, inbound=inbound):
                if neighbor.node_id not in path:
                    queue.append((neighbor.node_id, (*path, neighbor.node_id)))
        return self._response("trace_path", paths, limit=limit, explain={"depth": depth, "cycle_safe": True, "bounded": True})

    def architecture(self, *, limit: int = 20) -> QueryResponse:
        node_counts = Counter(node.kind.value for node in self.graph.nodes)
        edge_counts = Counter(edge.kind.value for edge in self.graph.edges)
        languages = Counter(node.language for node in self.graph.nodes if node.language)
        rows = [{"id": "architecture", "nodes": dict(sorted(node_counts.items())), "edges": dict(sorted(edge_counts.items())), "languages": dict(sorted(languages.items())), "generation_id": self.graph.generation_id}]
        return self._response("architecture", rows, limit=limit, explain={"bounded": True})

    def impact(self, *, changed_paths: Iterable[str] = (), changed_ids: Iterable[str] = (), depth: int = 3, limit: int = 20) -> QueryResponse:
        roots = {node.node_id for node in self.graph.nodes if node.path in set(changed_paths)} | set(changed_ids)
        queue: deque[tuple[str, int]] = deque((item, 0) for item in sorted(roots))
        seen = set(roots)
        rows: list[dict[str, Any]] = []
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for node in self.graph.neighbors(current, inbound=True):
                if node.node_id in seen:
                    continue
                seen.add(node.node_id)
                queue.append((node.node_id, current_depth + 1))
                rows.append({**self._node(node), "impact_depth": current_depth + 1, "risk": "high" if self._coverage_summary()["complete"] else "unknown"})
        return self._response("impact", rows, limit=limit, explain={"roots": sorted(roots), "depth": depth, "negative_claims": False})

    def dead_code(self, *, limit: int = 20) -> QueryResponse:
        incoming = {edge.target_id for edge in self.graph.edges if edge.kind in {EdgeKind.CALLS, EdgeKind.TESTS}}
        rows = []
        for node in self.graph.nodes:
            if node.kind not in {NodeKind.FUNCTION, NodeKind.METHOD} or node.node_id in incoming:
                continue
            excluded = bool(node.metadata.get("entrypoint") or node.metadata.get("exported") or node.metadata.get("dynamic"))
            rows.append({**self._node(node), "candidate": not excluded, "proven": False, "reason": "no-proven-inbound-call" if not excluded else "entrypoint-or-dynamic-exclusion"})
        return self._response("dead_code", rows, limit=limit, explain={"negative_claims": False, "coverage_required": True})

    def code_snippet(self, node_id: str, sources: Mapping[str, str]) -> QueryResponse:
        node = self.graph.get(node_id)
        if node is None:
            return self._response("code_snippet", (), explain={"error": "unknown_node_id"})
        source = sources.get(node.path)
        if source is None:
            return self._response("code_snippet", (), explain={"error": "source_not_provided"})
        actual_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if node.content_hash and node.content_hash != actual_hash:
            return self._response("code_snippet", (), explain={"error": "content_hash_mismatch", "fail_closed": True})
        lines = source.splitlines()
        snippet = "\n".join(lines[max(0, node.start_line - 1) : node.end_line])
        row = {"id": node.node_id, "path": node.path, "range": [node.start_line, node.end_line], "content_hash": actual_hash, "generation_id": self.graph.generation_id, "snippet": snippet}
        return self._response("code_snippet", [row], limit=1)

    def execute(self, query: str) -> QueryResponse:
        if any(token in query.upper() for token in ("CREATE", "DELETE", "UPDATE", "INSERT", "MERGE", "SET")):
            raise ValueError("graph DSL is read-only")
        match = _MATCH.match(" ".join(query.split()))
        if not match:
            raise ValueError("invalid graph query; expected bounded MATCH ... RETURN ... [LIMIT n]")
        groups = match.groupdict()
        kind = NodeKind(groups["nkind"]) if groups.get("nkind") else None
        name = groups.get("name")
        limit = int(groups.get("limit") or 20)
        if not groups.get("edge"):
            return self.search_graph(kind=kind, name=name, limit=limit)
        edge_kind = EdgeKind(groups["edge"])
        rows = []
        for source in self.graph.find(kind=kind, name=name):
            for target in self.graph.neighbors(source.node_id, edge_kind=edge_kind):
                if groups.get("mkind") and target.kind != NodeKind(groups["mkind"]):
                    continue
                rows.append({"id": f"{source.node_id}:{target.node_id}", "source": self._node(source), "target": self._node(target), "edge": edge_kind.value})
        return self._response("dsl_match", rows, limit=limit, explain={"read_only": True, "bounded": True})


__all__ = ["QUERY_SCHEMA", "QueryResponse", "StructuralQueryEngine"]
