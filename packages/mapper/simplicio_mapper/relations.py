"""Canonical Mapper v1 relation helpers.

Call-graph edges are deliberately kept in their artifact vocabulary here:
``source_file`` and ``target_file`` are the only endpoint fields accepted by
Mapper consumers.  Generic graph shapes such as ``from``/``to`` are not
aliases for this contract; accepting them would make a missing canonical
relationship indistinguishable from a dropped relationship.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CALL_GRAPH_RELATION_EVIDENCE = (
    "semantic_resolved",
    "import_resolved",
    "lexical_unique",
    "lexical_ambiguous",
    "heuristic",
    "runtime_observed",
)

RELATION_RESOLUTION_STATUSES = ("resolved", "inferred", "ambiguous", "unknown")


def normalize_relation_path(value: object) -> str | None:
    """Return a repository-relative POSIX path, or ``None`` for unknown."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.replace("\\", "/").lstrip("./")


def _resolution_status(evidence_class: str, target_file: str | None) -> str:
    if not target_file:
        return "unknown"
    if evidence_class in {"semantic_resolved", "import_resolved", "lexical_unique", "runtime_observed"}:
        return "resolved"
    if evidence_class == "lexical_ambiguous":
        return "ambiguous"
    return "inferred" if target_file else "unknown"


def relation_identity(edge: Mapping[str, Any]) -> dict[str, Any]:
    """Return the identity-bearing fields for a relation.

    Candidate targets and the call-site line participate in identity.  This
    prevents two ambiguous candidates (or two call sites) from collapsing to
    one edge in a downstream projection.
    """
    return {
        "type": edge.get("type"),
        "source_file": normalize_relation_path(edge.get("source_file")),
        "source_symbol": edge.get("source_symbol"),
        "target_file": normalize_relation_path(edge.get("target_file")),
        "target_symbol": edge.get("target_symbol"),
        "import": edge.get("import"),
        "line": edge.get("line"),
        "target_candidates": edge.get("target_candidates", []),
    }


def relation_id(edge: Mapping[str, Any]) -> str:
    """Create a deterministic identity for a canonical relation."""
    encoded = json.dumps(
        relation_identity(edge), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonicalize_relation(
    edge: Mapping[str, Any],
    *,
    default_evidence_class: str = "heuristic",
    default_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize one Mapper v1 relation without translating vocabularies.

    ``None`` means the input is not a canonical relation (notably, an edge
    with only ``from``/``to``).  Callers must report that omission as degraded
    coverage rather than silently using a legacy shape.
    """
    if not isinstance(edge, Mapping):
        return None
    if "from" in edge or "to" in edge:
        return None
    source_file = normalize_relation_path(edge.get("source_file"))
    if not source_file or "target_file" not in edge:
        return None
    raw_target_file = edge.get("target_file")
    if raw_target_file is not None and not isinstance(raw_target_file, str):
        return None
    if isinstance(raw_target_file, str) and not raw_target_file.strip():
        return None
    target_file = normalize_relation_path(raw_target_file)
    raw_evidence_class = edge.get("evidence_class")
    evidence_class = str(raw_evidence_class or default_evidence_class)
    if raw_evidence_class and evidence_class not in CALL_GRAPH_RELATION_EVIDENCE:
        return None
    if evidence_class not in CALL_GRAPH_RELATION_EVIDENCE:
        return None
    raw_candidates = edge.get("target_candidates", [])
    if not isinstance(raw_candidates, list) or any(not isinstance(item, str) for item in raw_candidates):
        return None
    provenance = edge.get("provenance")
    if provenance is None and "provenance" in edge:
        return None
    if provenance is None:
        provenance = dict(default_provenance or {"method": "unspecified", "status": "degraded"})
    elif not isinstance(provenance, Mapping):
        return None
    if "confidence" in edge and (
        edge["confidence"] is not None
        and (not isinstance(edge["confidence"], (int, float)) or isinstance(edge["confidence"], bool))
    ):
        return None

    normalized = dict(edge)
    normalized["source_file"] = source_file
    normalized["target_file"] = target_file
    normalized["target_candidates"] = list(raw_candidates)
    normalized["evidence_class"] = evidence_class
    normalized["resolution_status"] = _resolution_status(evidence_class, target_file)
    declared_status = edge.get("resolution_status")
    if declared_status is not None and (
        not isinstance(declared_status, str) or declared_status not in RELATION_RESOLUTION_STATUSES
    ):
        return None
    if target_file and declared_status in RELATION_RESOLUTION_STATUSES and not (
        evidence_class == "lexical_ambiguous" and declared_status == "resolved"
    ):
        normalized["resolution_status"] = declared_status
    if normalized["resolution_status"] not in RELATION_RESOLUTION_STATUSES:
        normalized["resolution_status"] = _resolution_status(evidence_class, target_file)
    normalized["provenance"] = dict(provenance)
    if "relation_id" in edge and (
        not isinstance(edge["relation_id"], str) or not edge["relation_id"]
    ):
        return None
    normalized["relation_id"] = edge.get("relation_id") or relation_id(normalized)
    return normalized


def relation_summary(edge: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the bounded identity/evidence record used by retrieval paths."""
    normalized = canonicalize_relation(edge)
    if normalized is None:
        return None
    summary = {
        "relation_id": normalized["relation_id"],
        "type": normalized.get("type"),
        "source_file": normalized["source_file"],
        "target_file": normalized["target_file"],
        "source_symbol": normalized.get("source_symbol"),
        "target_symbol": normalized.get("target_symbol"),
        "import": normalized.get("import"),
        "line": normalized.get("line"),
        "target_candidates": normalized.get("target_candidates", []),
        "evidence_class": normalized["evidence_class"],
        "resolution_status": normalized["resolution_status"],
        "provenance": normalized["provenance"],
    }
    if "confidence" in normalized:
        summary["confidence"] = normalized.get("confidence")
    return summary


def relation_coverage(
    relations: list[Mapping[str, Any]],
    *,
    observed_edges: int | None = None,
    edge_limit: int | None = None,
    invalid_edges: int = 0,
) -> dict[str, Any]:
    """Describe emitted, omitted and degraded relation evidence."""
    emitted = len(relations)
    observed = emitted if observed_edges is None else max(emitted, int(observed_edges))
    limit = None if edge_limit is None else max(0, int(edge_limit))
    omitted = max(0, observed - emitted)
    truncated = omitted > 0
    by_evidence: dict[str, int] = {}
    unknown = ambiguous = 0
    for relation in relations:
        evidence = str(relation.get("evidence_class") or "heuristic")
        by_evidence[evidence] = by_evidence.get(evidence, 0) + 1
        if evidence == "lexical_ambiguous" or relation.get("resolution_status") == "ambiguous":
            ambiguous += 1
        if not relation.get("target_file") or relation.get("resolution_status") == "unknown":
            unknown += 1
    return {
        "status": "degraded" if truncated or invalid_edges or unknown or ambiguous else "complete",
        "edge_limit": limit,
        "observed_edges": observed,
        "emitted_edges": emitted,
        "omitted_edges": omitted,
        "truncated": truncated,
        "invalid_edges": max(0, int(invalid_edges)),
        "unknown_relations": unknown,
        "ambiguous_relations": ambiguous,
        "evidence_classes": {key: by_evidence[key] for key in sorted(by_evidence)},
    }


__all__ = [
    "CALL_GRAPH_RELATION_EVIDENCE",
    "RELATION_RESOLUTION_STATUSES",
    "canonicalize_relation",
    "normalize_relation_path",
    "relation_coverage",
    "relation_id",
    "relation_identity",
    "relation_summary",
]
