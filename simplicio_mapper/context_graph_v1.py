"""Canonical repository facts and provenance contract."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

GRAPH_SCHEMA = "simplicio.context-graph/v1"


class ContextGraphError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Provenance:
    path: str
    start_line: int
    end_line: int
    source_sha256: str
    tool: str
    tool_version: str
    evidence_kind: str = "measured"

    def __post_init__(self) -> None:
        if (
            not self.path or self.start_line < 1 or self.end_line < self.start_line
            or len(self.source_sha256) != 64
            or self.evidence_kind not in {"measured", "inferred", "asserted"}
        ):
            raise ContextGraphError("provenance_invalid", self.path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "span": [self.start_line, self.end_line],
            "source_sha256": self.source_sha256, "tool": self.tool,
            "tool_version": self.tool_version, "evidence_kind": self.evidence_kind,
        }


def fact(repo_id: str, generation: str, kind: str, key: str, value: Any,
         provenance: Provenance, *, confidence: float | None = None) -> dict[str, Any]:
    if not repo_id or not generation or not kind or not key:
        raise ContextGraphError("fact_invalid", key)
    if confidence is not None and not 0 <= confidence <= 1:
        raise ContextGraphError("confidence_invalid", key)
    identity = {"repo_id": repo_id, "generation": generation, "kind": kind, "key": key}
    return {
        "fact_id": digest(identity), **identity, "value": value,
        "provenance": provenance.as_dict(), "confidence": confidence,
        "status": "ACTIVE",
    }


def relation(repo_id: str, generation: str, kind: str, source_id: str,
             target_id: str, provenance: Provenance) -> dict[str, Any]:
    identity = {
        "repo_id": repo_id, "generation": generation, "kind": kind,
        "source_id": source_id, "target_id": target_id,
    }
    return {"relation_id": digest(identity), **identity, "provenance": provenance.as_dict()}


def build_graph(*, repo_id: str, generation: str, config_hash: str,
                facts: Iterable[Mapping[str, Any]], relations: Iterable[Mapping[str, Any]],
                complete: bool = True) -> dict[str, Any]:
    if not complete:
        raise ContextGraphError("graph_incomplete", generation)
    ordered_facts = sorted((dict(item) for item in facts), key=lambda item: item["fact_id"])
    ordered_relations = sorted((dict(item) for item in relations), key=lambda item: item["relation_id"])
    ids = {item["fact_id"] for item in ordered_facts}
    if len(ids) != len(ordered_facts):
        raise ContextGraphError("fact_collision", repo_id)
    if any(item["source_id"] not in ids or item["target_id"] not in ids for item in ordered_relations):
        raise ContextGraphError("relation_orphan", repo_id)
    body = {
        "schema": GRAPH_SCHEMA, "repo_id": repo_id, "generation": generation,
        "config_hash": config_hash, "facts": ordered_facts,
        "relations": ordered_relations, "complete": True,
    }
    body["graph_digest"] = digest(body)
    return body


def validate_graph(graph: Mapping[str, Any], *, expected_repo: str | None = None,
                   expected_generation: str | None = None) -> dict[str, Any]:
    if graph.get("schema") != GRAPH_SCHEMA:
        raise ContextGraphError("graph_schema_invalid", "")
    unsigned = dict(graph); supplied = unsigned.pop("graph_digest", "")
    if supplied != digest(unsigned):
        raise ContextGraphError("graph_corrupt", "")
    if expected_repo and graph.get("repo_id") != expected_repo:
        raise ContextGraphError("repo_mismatch", str(graph.get("repo_id")))
    if expected_generation and graph.get("generation") != expected_generation:
        raise ContextGraphError("generation_stale", str(graph.get("generation")))
    return dict(graph)


def tombstone(previous: Mapping[str, Any], target_generation: str) -> dict[str, Any]:
    result = dict(previous)
    result["generation"] = target_generation
    result["status"] = "TOMBSTONE"
    result["supersedes"] = previous["fact_id"]
    result["fact_id"] = digest({
        "repo_id": result["repo_id"], "generation": target_generation,
        "kind": result["kind"], "key": result["key"],
    })
    return result


def limited_export(graph: Mapping[str, Any], *, max_facts: int) -> dict[str, Any]:
    clean = validate_graph(graph)
    if max_facts < 0:
        raise ContextGraphError("budget_invalid", str(max_facts))
    selected = clean["facts"][:max_facts]
    ids = {item["fact_id"] for item in selected}
    return {
        "schema": "simplicio.context-graph-export/v1",
        "repo_id": clean["repo_id"], "generation": clean["generation"],
        "graph_digest": clean["graph_digest"], "facts": selected,
        "relations": [item for item in clean["relations"]
                      if item["source_id"] in ids and item["target_id"] in ids],
        "truncated": len(selected) < len(clean["facts"]),
        "omitted_facts": len(clean["facts"]) - len(selected),
        "public_offsets": None,
        "public_offsets_null_reason": "FAST_INTERNAL_OFFSETS_NOT_PUBLIC",
    }


__all__ = ["ContextGraphError", "Provenance", "build_graph", "digest", "fact",
           "limited_export", "relation", "tombstone", "validate_graph"]
