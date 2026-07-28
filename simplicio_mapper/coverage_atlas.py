"""Deterministic ecosystem Coverage Atlas and incremental gap deltas."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

ATLAS_SCHEMA = "simplicio.coverage-atlas/v1"
DELTA_SCHEMA = "simplicio.coverage-delta/v1"
NODE_KINDS = frozenset({
    "requirement", "acceptance_criterion", "repository", "module", "contract",
    "producer", "consumer", "capability", "agent_address", "test", "evidence", "release",
})
EDGE_KINDS = frozenset({
    "OWNS", "IMPLEMENTS", "PRODUCES", "CONSUMES", "VERIFIES",
    "DEPENDS_ON", "SUPERSEDES", "DELIVERS",
})


class AtlasError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def node(kind: str, subject: str, *, source_hash: str, owner: str, valid_from: str,
         provenance: Sequence[str] = ()) -> dict[str, Any]:
    if kind not in NODE_KINDS or not all((subject, source_hash, owner, valid_from)):
        raise AtlasError("invalid node")
    body = {
        "kind": kind, "subject": subject, "source_hash": source_hash,
        "owner": owner, "valid_from": valid_from, "provenance": sorted(set(provenance)),
    }
    return {"node_id": digest({"kind": kind, "subject": subject}), **body}


def edge(kind: str, source: str, target: str, *, source_hash: str,
         valid_from: str, provenance: Sequence[str] = ()) -> dict[str, Any]:
    if kind not in EDGE_KINDS or not all((source, target, source_hash, valid_from)):
        raise AtlasError("invalid edge")
    body = {
        "kind": kind, "source": source, "target": target, "source_hash": source_hash,
        "valid_from": valid_from, "provenance": sorted(set(provenance)),
    }
    return {"edge_id": digest({"kind": kind, "source": source, "target": target}), **body}


def build_atlas(nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]],
                *, source: str, revision: str, complete: bool = True,
                suppressions: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    if not complete:
        raise AtlasError("partial atlas cannot be treated as complete")
    normalized_nodes = sorted((dict(item) for item in nodes), key=lambda item: item["node_id"])
    normalized_edges = sorted((dict(item) for item in edges), key=lambda item: item["edge_id"])
    if len({item["node_id"] for item in normalized_nodes}) != len(normalized_nodes):
        raise AtlasError("duplicate node")
    node_ids = {item["node_id"] for item in normalized_nodes}
    if any(item["source"] not in node_ids or item["target"] not in node_ids for item in normalized_edges):
        raise AtlasError("orphan edge")
    body = {
        "schema": ATLAS_SCHEMA, "source": source, "revision": revision,
        "nodes": normalized_nodes, "edges": normalized_edges,
        "suppressions": sorted((dict(item) for item in suppressions), key=lambda item: item["gap_id"]),
        "complete": True,
    }
    body["atlas_digest"] = digest(body)
    return body


def _gap(base: str, kind: str, subject: str, evidence: Sequence[str]) -> dict[str, Any]:
    return {
        "gap_id": digest({"base_atlas_digest": base, "kind": kind, "subject": subject}),
        "kind": kind, "subject": subject, "evidence_refs": sorted(set(evidence)),
        "acceptance_criteria": "rescan proves the gap absent",
    }


def detect_gaps(atlas: Mapping[str, Any], *, now_revision: str | None = None) -> list[dict[str, Any]]:
    if atlas.get("schema") != ATLAS_SCHEMA or atlas.get("atlas_digest") != digest({
        key: atlas[key] for key in atlas if key != "atlas_digest"
    }):
        raise AtlasError("invalid atlas digest/schema")
    nodes = {item["node_id"]: item for item in atlas["nodes"]}
    outgoing: dict[tuple[str, str], set[str]] = {}
    incoming: dict[tuple[str, str], set[str]] = {}
    for item in atlas["edges"]:
        outgoing.setdefault((item["source"], item["kind"]), set()).add(item["target"])
        incoming.setdefault((item["target"], item["kind"]), set()).add(item["source"])
    gaps = []
    for item in nodes.values():
        nid, kind, subject = item["node_id"], item["kind"], item["subject"]
        evidence = item.get("provenance", [])
        if kind in {"requirement", "acceptance_criterion"} and not outgoing.get((nid, "OWNS")):
            gaps.append(_gap(atlas["atlas_digest"], "missing_owner", subject, evidence))
        if kind == "contract":
            if not incoming.get((nid, "PRODUCES")):
                gaps.append(_gap(atlas["atlas_digest"], "missing_producer", subject, evidence))
            if not outgoing.get((nid, "CONSUMES")):
                gaps.append(_gap(atlas["atlas_digest"], "missing_consumer", subject, evidence))
        if kind in {"module", "contract"} and not incoming.get((nid, "VERIFIES")):
            gaps.append(_gap(atlas["atlas_digest"], "missing_test", subject, evidence))
        if kind == "capability" and not incoming.get((nid, "OWNS")):
            gaps.append(_gap(atlas["atlas_digest"], "missing_owner", subject, evidence))
        if kind == "agent_address" and not item.get("provenance"):
            gaps.append(_gap(atlas["atlas_digest"], "missing_integration", subject, evidence))
        if kind == "evidence" and ":ac:" not in subject:
            gaps.append(_gap(atlas["atlas_digest"], "missing_evidence", subject, evidence))
    active_suppressions = {
        item["gap_id"] for item in atlas.get("suppressions", ())
        if item.get("owner") and item.get("reason")
        and (now_revision is None or str(item.get("expires_after", "")) >= now_revision)
    }
    return sorted((item for item in gaps if item["gap_id"] not in active_suppressions),
                  key=lambda item: item["gap_id"])


def coverage_delta(atlas: Mapping[str, Any], previous_gap_ids: Sequence[str] = (),
                   *, now_revision: str | None = None) -> dict[str, Any]:
    gaps = detect_gaps(atlas, now_revision=now_revision)
    previous = set(previous_gap_ids)
    body = {
        "schema": DELTA_SCHEMA, "source": atlas["source"],
        "base_atlas_digest": atlas["atlas_digest"], "gaps": gaps,
        "opened_gap_ids": sorted(item["gap_id"] for item in gaps if item["gap_id"] not in previous),
        "closed_gap_ids": sorted(previous - {item["gap_id"] for item in gaps}),
    }
    # Loop v1 validates the digest over its projection, excluding incremental metadata.
    projection = {key: body[key] for key in ("schema", "source", "base_atlas_digest", "gaps")}
    body["delta_digest"] = digest(projection)
    return body


__all__ = ["AtlasError", "build_atlas", "coverage_delta", "detect_gaps", "digest",
           "edge", "node", "ATLAS_SCHEMA", "DELTA_SCHEMA"]
