"""Architectural decisions and observed runtime evidence for graph projections."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from .structural_graph import EdgeKind, StructuralGraph


EVIDENCE_SCHEMA = "simplicio.graph-evidence/v1"
_SENSITIVE_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|request[_-]?body|response[_-]?body)", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if _SENSITIVE_KEY.search(str(key)) else _redact(item) for key, item in value.items() if not _SENSITIVE_KEY.search(str(key))}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ArchitecturalDecision:
    decision_id: str
    title: str
    status: str
    date: str
    context: str
    decision: str
    consequences: str
    affected_node_ids: tuple[str, ...]
    source_path: str
    source_hash: str
    generation_id: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    evidence_id: str
    generation_id: str
    source_version: str
    source_kind: str
    source_id: str
    target_id: str
    edge_kind: EdgeKind
    observed_at_start: str
    observed_at_end: str
    count: int
    evidence_digest: str
    attributes: dict[str, Any]


class EvidenceStore:
    """SQLite-backed evidence projection; static and observed facts never overwrite."""

    def __init__(self, path: str) -> None:
        self.path = path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS graph_adr (
                    decision_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                    date TEXT NOT NULL, context TEXT NOT NULL, decision TEXT NOT NULL,
                    consequences TEXT NOT NULL, affected_json TEXT NOT NULL,
                    source_path TEXT NOT NULL, source_hash TEXT NOT NULL,
                    generation_id TEXT NOT NULL, tags_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS graph_runtime_evidence (
                    evidence_id TEXT PRIMARY KEY, generation_id TEXT NOT NULL,
                    source_version TEXT NOT NULL, source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL, target_id TEXT NOT NULL, edge_kind TEXT NOT NULL,
                    observed_start TEXT NOT NULL, observed_end TEXT NOT NULL,
                    count INTEGER NOT NULL, evidence_digest TEXT NOT NULL, attributes_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def put_adr(self, adr: ArchitecturalDecision, *, graph: StructuralGraph) -> str:
        if any(graph.get(node_id) is None for node_id in adr.affected_node_ids):
            raise ValueError("ADR references a node outside the active generation")
        if adr.generation_id != graph.generation_id:
            raise ValueError("ADR generation is stale")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO graph_adr VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(decision_id) DO UPDATE SET title=excluded.title, status=excluded.status, context=excluded.context, decision=excluded.decision, consequences=excluded.consequences, affected_json=excluded.affected_json, source_path=excluded.source_path, source_hash=excluded.source_hash, generation_id=excluded.generation_id, tags_json=excluded.tags_json",
                (adr.decision_id, adr.title, adr.status, adr.date, adr.context, adr.decision, adr.consequences, json.dumps(sorted(adr.affected_node_ids)), adr.source_path, adr.source_hash, adr.generation_id, json.dumps(sorted(adr.tags))),
            )
            connection.commit()
        return adr.decision_id

    def ingest_trace(self, evidence: RuntimeEvidence, *, graph: StructuralGraph) -> str:
        if evidence.generation_id != graph.generation_id:
            raise ValueError("runtime evidence generation is stale")
        if graph.get(evidence.source_id) is None or graph.get(evidence.target_id) is None:
            raise ValueError("runtime evidence references an unknown node")
        if evidence.count < 0:
            raise ValueError("evidence count must be non-negative")
        attributes = _redact(evidence.attributes)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO graph_runtime_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(evidence_id) DO NOTHING",
                (evidence.evidence_id, evidence.generation_id, evidence.source_version, evidence.source_kind, evidence.source_id, evidence.target_id, evidence.edge_kind.value, evidence.observed_at_start, evidence.observed_at_end, evidence.count, evidence.evidence_digest, json.dumps(attributes, sort_keys=True)),
            )
            connection.commit()
        return evidence.evidence_id

    def list_adrs(self, generation_id: str) -> tuple[ArchitecturalDecision, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM graph_adr WHERE generation_id = ? ORDER BY decision_id", (generation_id,)).fetchall()
        return tuple(ArchitecturalDecision(row["decision_id"], row["title"], row["status"], row["date"], row["context"], row["decision"], row["consequences"], tuple(json.loads(row["affected_json"])), row["source_path"], row["source_hash"], row["generation_id"], tuple(json.loads(row["tags_json"]))) for row in rows)

    def list_runtime_evidence(self, generation_id: str) -> tuple[RuntimeEvidence, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM graph_runtime_evidence WHERE generation_id = ? ORDER BY evidence_id", (generation_id,)).fetchall()
        return tuple(RuntimeEvidence(row["evidence_id"], row["generation_id"], row["source_version"], row["source_kind"], row["source_id"], row["target_id"], EdgeKind(row["edge_kind"]), row["observed_start"], row["observed_end"], row["count"], row["evidence_digest"], json.loads(row["attributes_json"])) for row in rows)

    def reconcile_edge(self, source_id: str, target_id: str, edge_kind: EdgeKind, *, graph: StructuralGraph) -> dict[str, object]:
        static = any(edge.source_id == source_id and edge.target_id == target_id and edge.kind == edge_kind for edge in graph.edges)
        observed = any(item.source_id == source_id and item.target_id == target_id and item.edge_kind == edge_kind for item in self.list_runtime_evidence(graph.generation_id))
        return {"source_id": source_id, "target_id": target_id, "edge_kind": edge_kind.value, "static": static, "observed": observed, "conflict": False if static == observed else "static-only" if static else "observed-only", "provenance": [kind for kind, present in (("static-inferred", static), ("runtime-observed", observed)) if present]}


def evidence_id(source_version: str, source_id: str, target_id: str, edge_kind: EdgeKind, digest: str) -> str:
    payload = "\x1f".join((source_version, source_id, target_id, edge_kind.value, digest))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


__all__ = ["ArchitecturalDecision", "EVIDENCE_SCHEMA", "EvidenceStore", "RuntimeEvidence", "evidence_id"]
