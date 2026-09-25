"""Explicit-scope cross-service, IaC and cross-repository projections."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .structural_graph import EdgeKind, GraphNode, NodeKind, StructuralGraph
from .structural_parser import build_structural_graph

_ROUTE = re.compile(r"(?:@(?:app|router)\.(?:get|post|put|patch|delete)|@(Get|Post|Put|Patch|Delete))\s*\(\s*['\"]([^'\"]+)", re.IGNORECASE)
_HTTP_CALL = re.compile(r"(?:requests|httpx|axios|fetch|client)\s*\.\s*(?:get|post|put|patch|delete|request)\s*\(\s*['\"]([^'\"]+)", re.IGNORECASE)
_CHANNEL = re.compile(r"\b(?:emit|publish|send|on|subscribe|consume|listen)\s*\(\s*['\"]([A-Za-z0-9_.:/-]+)['\"]", re.IGNORECASE)
_KIND = re.compile(r"^\s*kind\s*:\s*([A-Za-z0-9_-]+)", re.MULTILINE)
_TERRAFORM = re.compile(r"\bresource\s+['\"]([A-Za-z0-9_-]+)['\"]\s+['\"]([A-Za-z0-9_-]+)['\"]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FleetRepository:
    repository_id: str
    root: str
    generation_id: str
    graph: StructuralGraph


@dataclass(frozen=True, slots=True)
class FleetEdge:
    source_repo: str
    source_id: str
    target_repo: str
    target_id: str
    kind: EdgeKind
    confidence: float
    resolution_kind: str
    evidence: tuple[str, ...]


class FleetGraph:
    """A bounded collection of separately identified repository generations."""

    def __init__(self, repositories: Iterable[FleetRepository], edges: Iterable[FleetEdge] = ()) -> None:
        self.repositories = tuple(sorted(repositories, key=lambda item: item.repository_id))
        self.edges = tuple(sorted(edges, key=lambda item: (item.source_repo, item.source_id, item.kind.value, item.target_repo, item.target_id)))

    def find(self, repository_id: str, node_id: str) -> GraphNode | None:
        for repository in self.repositories:
            if repository.repository_id == repository_id:
                return repository.graph.get(node_id)
        return None

    def query(self, *, repository_id: str | None = None, kind: NodeKind | None = None) -> tuple[dict[str, object], ...]:
        rows = []
        for repository in self.repositories:
            if repository_id and repository.repository_id != repository_id:
                continue
            for node in repository.graph.nodes:
                if kind and node.kind != kind:
                    continue
                rows.append({"repository": repository.repository_id, "generation_id": repository.generation_id, "node": node.node_id, "kind": node.kind.value, "name": node.qualified_name, "path": node.path})
        return tuple(sorted(rows, key=lambda row: (str(row["repository"]), str(row["node"]))))


def _add_projection(graph: StructuralGraph, repository_id: str, files: Iterable[tuple[str, str]]) -> list[GraphNode]:
    service_nodes: list[GraphNode] = []
    for path, source in sorted(files):
        for match in _ROUTE.finditer(source):
            route = match.group(2)
            node = GraphNode.create(repository_id, NodeKind.ROUTE, route, path=path, language="protocol", generation_id=graph.generation_id, provenance="route-evidence", confidence=0.95, metadata={"method": (match.group(1) or "unknown").upper()})
            graph.add_node(node)
            service_nodes.append(node)
        for match in _CHANNEL.finditer(source):
            channel = GraphNode.create(repository_id, NodeKind.CHANNEL, match.group(1), path=path, language="protocol", generation_id=graph.generation_id, provenance="channel-evidence", confidence=0.75)
            if graph.get(channel.node_id) is None:
                graph.add_node(channel)
            service_nodes.append(channel)
        if path.lower().endswith(("dockerfile", ".yaml", ".yml", ".tf", ".hcl")):
            for match in _KIND.finditer(source):
                resource = GraphNode.create(repository_id, NodeKind.RESOURCE, match.group(1), path=path, language="iac", generation_id=graph.generation_id, provenance="iac-evidence", confidence=0.95)
                graph.add_node(resource)
                service_nodes.append(resource)
            for match in _TERRAFORM.finditer(source):
                resource = GraphNode.create(repository_id, NodeKind.RESOURCE, f"{match.group(1)}.{match.group(2)}", path=path, language="iac", generation_id=graph.generation_id, provenance="iac-evidence", confidence=0.95)
                graph.add_node(resource)
                service_nodes.append(resource)
    return service_nodes


def build_fleet(
    repositories: Mapping[str, Iterable[tuple[str, str]]], *, generations: Mapping[str, str], roots: Mapping[str, str] | None = None
) -> FleetGraph:
    """Build only from explicitly supplied repository file scopes.

    No network access, cloning or discovery is performed here. Each graph is
    independently generation-bound; only evidence-backed projection edges are
    added between them.
    """

    roots = dict(roots or {})
    fleet_repositories: list[FleetRepository] = []
    projections: dict[str, list[GraphNode]] = {}
    for repository_id in sorted(repositories):
        if repository_id not in generations:
            raise ValueError(f"missing generation for repository {repository_id}")
        files = tuple(repositories[repository_id])
        graph, _ = build_structural_graph(files, repo_identity=repository_id, generation_id=generations[repository_id])
        projection_nodes = _add_projection(graph, repository_id, files)
        for node in projection_nodes:
            if node.node_id not in {item.node_id for item in graph.nodes}:
                graph.add_node(node)
        projections[repository_id] = projection_nodes
        fleet_repositories.append(FleetRepository(repository_id, roots.get(repository_id, ""), generations[repository_id], graph))

    edges: list[FleetEdge] = []
    graph_by_repository = {item.repository_id: item.graph for item in fleet_repositories}
    routes: dict[str, list[tuple[str, str, str]]] = {}
    channels: dict[str, list[tuple[str, str, str]]] = {}
    for repository_id, nodes in projections.items():
        for node in nodes:
            bucket = routes if node.kind == NodeKind.ROUTE else channels if node.kind == NodeKind.CHANNEL else None
            if bucket is not None:
                bucket.setdefault(node.qualified_name, []).append((repository_id, node.node_id, node.path))

    for repository_id, files in repositories.items():
        for path, source in files:
            for match in _HTTP_CALL.finditer(source):
                target_candidates = routes.get(match.group(1), [])
                source_nodes = [node for node in graph_by_repository[repository_id].nodes if node.path == path]
                if len(target_candidates) == 1 and source_nodes:
                    target_repo, target_id, target_path = target_candidates[0]
                    edges.append(FleetEdge(repository_id, source_nodes[0].node_id, target_repo, target_id, EdgeKind.HTTP_CALLS, 0.9, "exact-semantic", (f"{path}:http:{match.group(1)}", target_path)))
                elif len(target_candidates) > 1 and source_nodes:
                    edges.append(FleetEdge(repository_id, source_nodes[0].node_id, "*", "*", EdgeKind.CALL_REFERENCE, 0.2, "ambiguous", (f"{path}:http:{match.group(1)}",)))
            for match in _CHANNEL.finditer(source):
                target_candidates = channels.get(match.group(1), [])
                source_nodes = [node for node in graph_by_repository[repository_id].nodes if node.path == path]
                if len(target_candidates) == 1 and source_nodes:
                    target_repo, target_id, target_path = target_candidates[0]
                    edges.append(FleetEdge(repository_id, source_nodes[0].node_id, target_repo, target_id, EdgeKind.EMITS, 0.8, "exact-lexical", (f"{path}:channel:{match.group(1)}", target_path)))
    return FleetGraph(fleet_repositories, edges)


__all__ = ["FleetEdge", "FleetGraph", "FleetRepository", "build_fleet"]
