"""Stable public ContextGraph contract used by all Mapper channels.

The contract is deliberately a projection: callers depend on identity, ordering,
relations, and digest, not parser/storage representations.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CONTRACT_SCHEMA = "simplicio.context-graph-contract/v1"
GRAPH_SCHEMA = "simplicio.context-graph/v1"
CONTRACT_VERSION = 1


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _public_projection(graph: Mapping[str, Any]) -> dict[str, Any]:
    nodes = sorted(
        [{"id": str(node["id"]), "scale": str(node.get("scale", ""))} for node in graph.get("nodes", []) if isinstance(node, Mapping) and node.get("id")],
        key=lambda item: item["id"],
    )
    relations = sorted(
        [
            {
                "id": str(edge["id"]),
                "kind": str(edge.get("kind", "")),
                "source": str(edge.get("source", "")),
                "target": str(edge.get("target", "")),
            }
            for edge in graph.get("edges", [])
            if isinstance(edge, Mapping) and edge.get("id")
        ],
        key=lambda item: item["id"],
    )
    return {
        "stable_ids": {
            "nodes": [node["id"] for node in nodes],
            "edges": [relation["id"] for relation in relations],
        },
        "nodes": nodes,
        "relations": relations,
    }


def build_public_contract(graph: Mapping[str, Any], *, repository_id: str, generation: str) -> dict[str, Any]:
    if not isinstance(graph, Mapping) or graph.get("schema") != GRAPH_SCHEMA:
        raise ValueError("graph_schema_invalid")
    if not repository_id or not generation:
        raise ValueError("identity_missing")
    body = {
        "schema": CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "repository_id": repository_id,
        "generation": generation,
        **_public_projection(graph),
    }
    return {**body, "digest": canonical_digest(body)}


def validate_public_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, Mapping) or contract.get("schema") != CONTRACT_SCHEMA:
        return {"valid": False, "reason": "schema_unsupported"}
    if contract.get("version") != CONTRACT_VERSION:
        return {"valid": False, "reason": "version_unsupported"}
    supplied = contract.get("digest")
    body = {key: value for key, value in contract.items() if key != "digest"}
    if supplied != canonical_digest(body):
        return {"valid": False, "reason": "digest_mismatch"}
    if not isinstance(contract.get("repository_id"), str) or not contract["repository_id"]:
        return {"valid": False, "reason": "repository_identity_missing"}
    if not isinstance(contract.get("generation"), str) or not contract["generation"]:
        return {"valid": False, "reason": "generation_missing"}
    return {"valid": True, "reason": None}


def contract_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return build_public_contract(
        snapshot["graph"],
        repository_id=str(snapshot["repository_id"]),
        generation=str(snapshot.get("snapshot_id") or snapshot.get("revision") or ""),
    )


__all__ = [
    "CONTRACT_SCHEMA",
    "CONTRACT_VERSION",
    "GRAPH_SCHEMA",
    "build_public_contract",
    "canonical_digest",
    "canonical_json",
    "contract_from_snapshot",
    "validate_public_contract",
]
