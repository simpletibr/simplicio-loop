"""Canonical, deterministic structural graph primitives.

The graph is the authority for structural facts. Text, vector and coverage
indexes are projections owned by later modules; they must retain the same
node IDs and generation ID.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "simplicio.graph/v1"


class NodeKind(StrEnum):
    PROJECT = "project"
    PACKAGE = "package"
    FOLDER = "folder"
    FILE = "file"
    MODULE = "module"
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    STRUCT = "struct"
    TRAIT = "trait"
    INTERFACE = "interface"
    ENUM = "enum"
    TYPE = "type"
    CONSTANT = "constant"
    ROUTE = "route"
    RESOURCE = "resource"
    CHANNEL = "channel"


class EdgeKind(StrEnum):
    CONTAINS = "contains"
    DEFINES = "defines"
    IMPORTS = "imports"
    CALLS = "calls"
    CALL_REFERENCE = "call_reference"
    USAGE = "usage"
    IMPLEMENTS = "implements"
    INHERITS = "inherits"
    USES_TYPE = "uses_type"
    TESTS = "tests"
    CONFIGURES = "configures"
    WRITES = "writes"
    READS = "reads"
    FILE_CHANGES_WITH = "file_changes_with"
    DATA_FLOWS = "data_flows"
    HTTP_CALLS = "http_calls"
    ASYNC_CALLS = "async_calls"
    EMITS = "emits"
    LISTENS_ON = "listens_on"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(*parts: object) -> str:
    """Return a content-addressed ID independent of process/thread order."""

    payload = "\x1f".join(str(part).strip() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    qualified_name: str
    path: str = ""
    language: str = ""
    start_line: int = 0
    end_line: int = 0
    content_hash: str = ""
    generation_id: str = ""
    provenance: str = "static-inferred"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id must not be empty")
        if not self.qualified_name:
            raise ValueError("qualified_name must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.start_line < 0 or self.end_line < self.start_line:
            raise ValueError("invalid source range")

    @classmethod
    def create(
        cls,
        repo_identity: str,
        kind: NodeKind,
        qualified_name: str,
        *,
        path: str = "",
        language: str = "",
        start_line: int = 0,
        end_line: int = 0,
        content_hash: str = "",
        generation_id: str = "",
        provenance: str = "static-inferred",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> GraphNode:
        return cls(
            node_id=stable_id(repo_identity, kind.value, qualified_name, path, content_hash),
            kind=kind,
            qualified_name=qualified_name,
            path=path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash,
            generation_id=generation_id,
            provenance=provenance,
            confidence=confidence,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    kind: EdgeKind
    resolution_kind: str = "exact-semantic"
    confidence: float = 1.0
    provenance: str = "static-inferred"
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise ValueError("edge endpoints must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


class StructuralGraph:
    """In-memory canonical graph with deterministic publication semantics."""

    def __init__(self, repo_identity: str, generation_id: str) -> None:
        if not repo_identity or not generation_id:
            raise ValueError("repo_identity and generation_id are required")
        self.repo_identity = repo_identity
        self.generation_id = generation_id
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[tuple[str, str, str, str], GraphEdge] = {}

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(sorted(self._nodes.values(), key=lambda item: (item.kind.value, item.qualified_name, item.node_id)))

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._edges.values(), key=lambda item: (item.source_id, item.kind.value, item.target_id)))

    def add_node(self, node: GraphNode) -> GraphNode:
        if node.generation_id and node.generation_id != self.generation_id:
            raise ValueError("node generation does not match graph generation")
        if node.node_id in self._nodes and self._nodes[node.node_id] != node:
            raise ValueError(f"conflicting node definition: {node.node_id}")
        self._nodes[node.node_id] = node
        return node

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise KeyError("both edge endpoints must be present before adding an edge")
        key = (edge.source_id, edge.target_id, edge.kind.value, edge.resolution_kind)
        current = self._edges.get(key)
        if current is not None and current != edge:
            # Preserve ambiguity and the strongest evidence deterministically.
            edge = GraphEdge(
                source_id=current.source_id,
                target_id=current.target_id,
                kind=current.kind,
                resolution_kind=current.resolution_kind,
                confidence=max(current.confidence, edge.confidence),
                provenance=min(current.provenance, edge.provenance),
                evidence=tuple(sorted(set(current.evidence) | set(edge.evidence))),
                metadata={**current.metadata, **edge.metadata},
            )
        self._edges[key] = edge
        return edge

    def get(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def find(self, *, kind: NodeKind | None = None, name: str | None = None, path: str | None = None) -> tuple[GraphNode, ...]:
        return tuple(
            node
            for node in self.nodes
            if (kind is None or node.kind == kind)
            and (name is None or name.casefold() in node.qualified_name.casefold())
            and (path is None or node.path == path)
        )

    def neighbors(self, node_id: str, *, edge_kind: EdgeKind | None = None, inbound: bool = False) -> tuple[GraphNode, ...]:
        ids = {
            (edge.source_id if inbound else edge.target_id)
            for edge in self.edges
            if (edge.target_id if inbound else edge.source_id) == node_id
            and (edge_kind is None or edge.kind == edge_kind)
        }
        return tuple(sorted((self._nodes[item] for item in ids), key=lambda node: node.node_id))

    def digest(self) -> str:
        payload = {
            "schema": SCHEMA_VERSION,
            "repo_identity": self.repo_identity,
            "generation_id": self.generation_id,
            "nodes": [self._node_dict(node) for node in self.nodes],
            "edges": [self._edge_dict(edge) for edge in self.edges],
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "repo_identity": self.repo_identity,
            "generation_id": self.generation_id,
            "digest": self.digest(),
            "nodes": [self._node_dict(node) for node in self.nodes],
            "edges": [self._edge_dict(edge) for edge in self.edges],
        }

    @staticmethod
    def _node_dict(node: GraphNode) -> dict[str, Any]:
        data = asdict(node)
        data["kind"] = node.kind.value
        return data

    @staticmethod
    def _edge_dict(edge: GraphEdge) -> dict[str, Any]:
        data = asdict(edge)
        data["kind"] = edge.kind.value
        data["evidence"] = list(edge.evidence)
        return data

    def publish_json(self, target: str | os.PathLike[str]) -> Path:
        """Atomically publish a complete generation; readers see old or new."""

        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return destination


class SqliteGraphStore:
    """Single SQLite authority for graph generations, using WAL publication."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._create_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS graph_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schema TEXT NOT NULL,
                repo_identity TEXT NOT NULL,
                generation_id TEXT NOT NULL,
                graph_digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_nodes (
                node_id TEXT PRIMARY KEY,
                generation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                path TEXT NOT NULL,
                language TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                provenance TEXT NOT NULL,
                confidence REAL NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                generation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                resolution_kind TEXT NOT NULL,
                confidence REAL NOT NULL,
                provenance TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, kind, resolution_kind),
                FOREIGN KEY (source_id) REFERENCES graph_nodes(node_id),
                FOREIGN KEY (target_id) REFERENCES graph_nodes(node_id)
            );
            CREATE INDEX IF NOT EXISTS idx_graph_nodes_name ON graph_nodes(qualified_name);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id, kind);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id, kind);
            """
        )

    def publish(self, graph: StructuralGraph) -> str:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM graph_edges")
                connection.execute("DELETE FROM graph_nodes")
                connection.execute("DELETE FROM graph_meta")
                connection.executemany(
                    """INSERT INTO graph_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            node.node_id,
                            graph.generation_id,
                            node.kind.value,
                            node.qualified_name,
                            node.path,
                            node.language,
                            node.start_line,
                            node.end_line,
                            node.content_hash,
                            node.provenance,
                            node.confidence,
                            _canonical_json(node.metadata),
                        )
                        for node in graph.nodes
                    ],
                )
                connection.executemany(
                    """INSERT INTO graph_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            edge.source_id,
                            edge.target_id,
                            graph.generation_id,
                            edge.kind.value,
                            edge.resolution_kind,
                            edge.confidence,
                            edge.provenance,
                            _canonical_json(edge.evidence),
                            _canonical_json(edge.metadata),
                        )
                        for edge in graph.edges
                    ],
                )
                connection.execute(
                    "INSERT INTO graph_meta VALUES (1, ?, ?, ?, ?)",
                    (SCHEMA_VERSION, graph.repo_identity, graph.generation_id, graph.digest()),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return graph.digest()

    def load(self) -> StructuralGraph | None:
        with self._connect() as connection:
            meta = connection.execute("SELECT * FROM graph_meta WHERE id = 1").fetchone()
            if meta is None:
                return None
            if meta["schema"] != SCHEMA_VERSION:
                raise ValueError(f"unsupported graph schema: {meta['schema']}")
            graph = StructuralGraph(meta["repo_identity"], meta["generation_id"])
            for row in connection.execute("SELECT * FROM graph_nodes ORDER BY kind, qualified_name, node_id"):
                graph.add_node(
                    GraphNode(
                        node_id=row["node_id"],
                        kind=NodeKind(row["kind"]),
                        qualified_name=row["qualified_name"],
                        path=row["path"],
                        language=row["language"],
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        content_hash=row["content_hash"],
                        generation_id=row["generation_id"],
                        provenance=row["provenance"],
                        confidence=row["confidence"],
                        metadata=json.loads(row["metadata_json"]),
                    )
                )
            for row in connection.execute("SELECT * FROM graph_edges ORDER BY source_id, kind, target_id"):
                graph.add_edge(
                    GraphEdge(
                        source_id=row["source_id"],
                        target_id=row["target_id"],
                        kind=EdgeKind(row["kind"]),
                        resolution_kind=row["resolution_kind"],
                        confidence=row["confidence"],
                        provenance=row["provenance"],
                        evidence=tuple(json.loads(row["evidence_json"])),
                        metadata=json.loads(row["metadata_json"]),
                    )
                )
            if graph.digest() != meta["graph_digest"]:
                raise ValueError("graph digest mismatch; rebuild is required")
            return graph


def graph_from_dict(payload: dict[str, Any]) -> StructuralGraph:
    if payload.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"unsupported graph schema: {payload.get('schema')}")
    graph = StructuralGraph(str(payload["repo_identity"]), str(payload["generation_id"]))
    for raw in payload.get("nodes", []):
        raw = dict(raw)
        raw["kind"] = NodeKind(raw["kind"])
        graph.add_node(GraphNode(**raw))
    for raw in payload.get("edges", []):
        raw = dict(raw)
        raw["kind"] = EdgeKind(raw["kind"])
        raw["evidence"] = tuple(raw.get("evidence", ()))
        graph.add_edge(GraphEdge(**raw))
    if payload.get("digest") not in (None, graph.digest()):
        raise ValueError("graph digest mismatch")
    return graph


__all__ = [
    "SCHEMA_VERSION",
    "EdgeKind",
    "GraphEdge",
    "GraphNode",
    "NodeKind",
    "SqliteGraphStore",
    "StructuralGraph",
    "graph_from_dict",
    "stable_id",
]
