"""Stable public ContextGraph contract used by all Mapper channels.

The contract is deliberately a projection: callers depend on identity, ordering,
relations, and digest, not parser/storage representations.
"""
from __future__ import annotations

import hashlib
import json
import re
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


_SCHEMA_PATTERN = re.compile(r"^simplicio[.]context-graph-contract/v(?P<major>[1-9][0-9]*)(?:[.][0-9]+)*$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _diagnostic(reason: str, path: str, message: str, **details: Any) -> dict[str, Any]:
    return {"valid": False, "reason": reason, "path": path, "message": message, **details}


def _valid_contract() -> dict[str, Any]:
    return {"valid": True, "reason": None, "path": None, "message": None}


def validate_public_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, Mapping):
        return _diagnostic("contract_not_object", "$", "ContextGraph contract must be an object")

    schema = contract.get("schema")
    match = _SCHEMA_PATTERN.fullmatch(schema) if isinstance(schema, str) else None
    if match is None:
        return _diagnostic(
            "schema_invalid",
            "$.schema",
            f"schema must match {CONTRACT_SCHEMA} or a compatible minor version",
            received=schema,
            supported=[CONTRACT_SCHEMA],
        )
    major = int(match.group("major"))
    if major != CONTRACT_VERSION:
        return _diagnostic(
            "schema_major_unsupported",
            "$.schema",
            f"schema major v{major} is unsupported; supported major is v{CONTRACT_VERSION}",
            received=schema,
            supported=[CONTRACT_SCHEMA],
        )

    version = contract.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != CONTRACT_VERSION:
        return _diagnostic(
            "version_unsupported",
            "$.version",
            f"version must be integer {CONTRACT_VERSION} for schema major v{CONTRACT_VERSION}",
        )
    repository_id = contract.get("repository_id")
    if not isinstance(repository_id, str) or not repository_id:
        return _diagnostic(
            "repository_identity_missing",
            "$.repository_id",
            "repository_id must be a non-empty string",
        )
    generation = contract.get("generation")
    if not isinstance(generation, str) or not generation:
        return _diagnostic("generation_missing", "$.generation", "generation must be a non-empty string")

    stable_ids = contract.get("stable_ids")
    if not isinstance(stable_ids, Mapping):
        return _diagnostic("stable_ids_invalid", "$.stable_ids", "stable_ids must be an object")
    for key in ("nodes", "edges"):
        values = stable_ids.get(key)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return _diagnostic(
                "stable_ids_invalid",
                f"$.stable_ids.{key}",
                f"stable_ids.{key} must be an array of strings",
            )

    nodes = contract.get("nodes")
    if not isinstance(nodes, list):
        return _diagnostic("nodes_invalid", "$.nodes", "nodes must be an array")
    node_ids: list[str] = []
    for index, node in enumerate(nodes):
        path = f"$.nodes[{index}]"
        if not isinstance(node, Mapping):
            return _diagnostic("node_invalid", path, "node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            return _diagnostic("node_id_invalid", f"{path}.id", "node id must be a non-empty string")
        if node_id in node_ids:
            return _diagnostic("node_id_duplicate", f"{path}.id", f"duplicate node id: {node_id}")
        if not isinstance(node.get("scale"), str) or not node["scale"]:
            return _diagnostic("node_scale_invalid", f"{path}.scale", "node scale must be a string")
        node_ids.append(node_id)

    relations = contract.get("relations")
    if not isinstance(relations, list):
        return _diagnostic("relations_invalid", "$.relations", "relations must be an array")
    relation_ids: list[str] = []
    for index, relation in enumerate(relations):
        path = f"$.relations[{index}]"
        if not isinstance(relation, Mapping):
            return _diagnostic("relation_invalid", path, "relation must be an object")
        relation_id = relation.get("id")
        if not isinstance(relation_id, str) or not relation_id:
            return _diagnostic(
                "relation_id_invalid", f"{path}.id", "relation id must be a non-empty string"
            )
        if relation_id in relation_ids:
            return _diagnostic("relation_id_duplicate", f"{path}.id", f"duplicate relation id: {relation_id}")
        for field in ("kind", "source", "target"):
            if not isinstance(relation.get(field), str) or not relation[field]:
                return _diagnostic(
                    "relation_field_invalid",
                    f"{path}.{field}",
                    f"relation {field} must be a non-empty string",
                )
        relation_ids.append(relation_id)

    if node_ids != sorted(node_ids):
        return _diagnostic("node_ids_not_canonical", "$.nodes", "nodes must be ordered by id")
    if relation_ids != sorted(relation_ids):
        return _diagnostic("relation_ids_not_canonical", "$.relations", "relations must be ordered by id")
    if stable_ids["nodes"] != node_ids:
        return _diagnostic(
            "stable_ids_mismatch", "$.stable_ids.nodes", "stable node ids must exactly match ordered nodes"
        )
    if stable_ids["edges"] != relation_ids:
        return _diagnostic(
            "stable_ids_mismatch",
            "$.stable_ids.edges",
            "stable edge ids must exactly match ordered relations",
        )

    supplied = contract.get("digest")
    if not isinstance(supplied, str) or _DIGEST_PATTERN.fullmatch(supplied) is None:
        return _diagnostic("digest_invalid", "$.digest", "digest must be a lowercase SHA-256 hex string")
    body = {key: value for key, value in contract.items() if key != "digest"}
    try:
        expected = canonical_digest(body)
    except (TypeError, ValueError):
        return _diagnostic(
            "contract_not_canonical_json", "$", "contract body must contain only canonical JSON values"
        )
    if supplied != expected:
        return _diagnostic(
            "digest_mismatch",
            "$.digest",
            "digest does not match the canonical contract body",
            expected=expected,
            received=supplied,
        )
    return _valid_contract()


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
