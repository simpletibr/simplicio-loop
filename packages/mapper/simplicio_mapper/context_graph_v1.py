"""Canonical repository facts and provenance contract."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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
    unsigned = dict(graph)
    supplied = unsigned.pop("graph_digest", "")
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
        "public_offsets_null_reason": "INTERNAL_OFFSETS_NOT_PUBLIC",
    }


def impact_query(graph: Mapping[str, Any], changed_fact_ids: Sequence[str], *,
                 direction: str = "forward", max_depth: int = 4,
                 max_nodes: int = 100) -> dict[str, Any]:
    clean = validate_graph(graph)
    if direction not in {"forward", "reverse"} or max_depth < 0 or max_nodes < 1:
        raise ContextGraphError("impact_budget_invalid", direction)
    facts = {item["fact_id"]: item for item in clean["facts"]}
    if any(item not in facts for item in changed_fact_ids):
        raise ContextGraphError("impact_seed_unknown", "")
    adjacency: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for edge in clean["relations"]:
        source, target = (
            (edge["source_id"], edge["target_id"])
            if direction == "forward" else (edge["target_id"], edge["source_id"])
        )
        adjacency.setdefault(source, []).append((target, edge))
    for values in adjacency.values():
        values.sort(key=lambda item: (item[0], item[1]["relation_id"]))
    queue = [(item, 0) for item in sorted(set(changed_fact_ids))]
    visited: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    truncated = False
    while queue:
        current, depth = queue.pop(0)
        if current in visited and visited[current] <= depth:
            continue
        if len(visited) >= max_nodes:
            truncated = True
            break
        visited[current] = depth
        if depth >= max_depth:
            if adjacency.get(current):
                truncated = True
            continue
        for target, edge in adjacency.get(current, ()):
            evidence.setdefault(target, []).append(edge["relation_id"])
            queue.append((target, depth + 1))
    impacted = [
        {
            "fact_id": fact_id, "kind": facts[fact_id]["kind"],
            "classification": "direct" if depth <= 1 else "transitive",
            "depth": depth, "evidence_relation_ids": sorted(set(evidence.get(fact_id, ()))),
        }
        for fact_id, depth in sorted(visited.items(), key=lambda item: (item[1], item[0]))
    ]
    tests = [item["fact_id"] for item in impacted if item["kind"] == "test"]
    write_set = sorted({
        facts[item["fact_id"]]["provenance"]["path"] for item in impacted
        if item["kind"] in {"symbol", "rule", "route", "screen"}
    })
    return {
        "schema": "simplicio.impact-query/v1", "graph_digest": clean["graph_digest"],
        "direction": direction, "seeds": sorted(set(changed_fact_ids)),
        "max_depth": max_depth, "max_nodes": max_nodes, "impacted": impacted,
        "verification_hints": {"test_fact_ids": tests},
        "write_set_hints": write_set, "truncated": truncated,
        "native_resolution": True, "fallback_reason": None,
    }


_RISK_THRESHOLDS = {"low": 0.55, "medium": 0.72, "high": 0.88}
_EVIDENCE_CAPS = {"measured": 1.0, "inferred": 0.75, "asserted": 0.50}


def evaluate_evidence(graph: Mapping[str, Any], *, risk: str = "medium",
                      evidence_kinds: Mapping[str, str] | None = None,
                      measured_scores: Mapping[str, float | None] | None = None,
                      threshold: float | None = None) -> dict[str, Any]:
    """Produce a conservative, explainable evidence receipt.

    Unknown measurements remain null with a reason; they are never converted to
    zero or presented as successful evidence.
    """
    clean = validate_graph(graph)
    if risk not in _RISK_THRESHOLDS:
        raise ContextGraphError("evidence_risk_invalid", risk)
    required = _RISK_THRESHOLDS[risk] if threshold is None else float(threshold)
    if not 0 <= required <= 1:
        raise ContextGraphError("evidence_threshold_invalid", str(required))
    kinds, scores = evidence_kinds or {}, measured_scores or {}
    rows: list[dict[str, Any]] = []
    for item in clean["facts"]:
        fact_id = item["fact_id"]
        kind = kinds.get(fact_id, "asserted")
        if kind not in _EVIDENCE_CAPS:
            raise ContextGraphError("evidence_kind_invalid", kind)
        raw = scores.get(fact_id)
        reason = None
        if raw is None:
            score = _EVIDENCE_CAPS[kind] if kind != "measured" else None
            reason = "MEASUREMENT_UNAVAILABLE" if kind == "measured" else None
        else:
            if not 0 <= float(raw) <= 1:
                raise ContextGraphError("evidence_score_invalid", fact_id)
            score = min(float(raw), _EVIDENCE_CAPS[kind])
        rows.append({
            "fact_id": fact_id, "evidence_kind": kind, "score": score,
            "score_null_reason": reason, "source": item["provenance"],
            "cap": _EVIDENCE_CAPS[kind],
        })
    known = [row["score"] for row in rows if row["score"] is not None]
    coverage = len(known) / len(rows) if rows else 0.0
    fidelity = sum(known) / len(known) if known else None
    confidence = coverage * fidelity if fidelity is not None else None
    if not rows or confidence is None:
        verdict, verdict_reason = "abstain", "NO_USABLE_EVIDENCE"
    elif confidence >= required:
        verdict, verdict_reason = "sufficient", None
    else:
        verdict, verdict_reason = "partial", "BELOW_RISK_THRESHOLD"
    return {
        "schema": "simplicio.evidence-receipt/v1",
        "graph_digest": clean["graph_digest"], "risk": risk,
        "threshold": required, "coverage": coverage, "fidelity": fidelity,
        "confidence": confidence, "verdict": verdict,
        "verdict_reason": verdict_reason, "facts": rows,
        "explain": {
            "formula": "confidence=coverage*fidelity",
            "included_fact_ids": [row["fact_id"] for row in rows if row["score"] is not None],
            "excluded": [
                {"fact_id": row["fact_id"], "reason": row["score_null_reason"]}
                for row in rows if row["score"] is None
            ],
        },
    }


def context_delta(base_graph: Mapping[str, Any], target_graph: Mapping[str, Any], *,
                  renames: Mapping[str, str] | None = None) -> dict[str, Any]:
    base, target = validate_graph(base_graph), validate_graph(target_graph)
    if base["repo_id"] != target["repo_id"]:
        raise ContextGraphError("delta_repo_mismatch", target["repo_id"])
    before = {(f["kind"], f["key"]): f for f in base["facts"]}
    after = {(f["kind"], f["key"]): f for f in target["facts"]}
    rename_map = dict(sorted((renames or {}).items()))
    renamed: list[dict[str, Any]] = []
    consumed_before, consumed_after = set(), set()
    for old_key, new_key in rename_map.items():
        candidates = sorted(k for k in before if k[1] == old_key)
        if len(candidates) != 1:
            raise ContextGraphError("delta_rename_source_invalid", old_key)
        old = candidates[0]
        new = (old[0], new_key)
        if new not in after:
            raise ContextGraphError("delta_rename_target_invalid", new_key)
        renamed.append({"from_fact_id": before[old]["fact_id"],
                        "to_fact_id": after[new]["fact_id"],
                        "from_key": old_key, "to_key": new_key})
        consumed_before.add(old)
        consumed_after.add(new)
    common = (set(before) & set(after)) - consumed_before - consumed_after
    updated = [
        {"from_fact_id": before[k]["fact_id"], "fact": after[k]}
        for k in sorted(common)
        if before[k]["value"] != after[k]["value"]
        or before[k]["provenance"] != after[k]["provenance"]
    ]
    created = [after[k] for k in sorted(set(after) - set(before) - consumed_after)]
    deleted = [
        {"fact_id": before[k]["fact_id"], "key": k[1], "status": "TOMBSTONE"}
        for k in sorted(set(before) - set(after) - consumed_before)
    ]
    changed_ids = {
        x["fact_id"] for x in created
    } | {x["fact"]["fact_id"] for x in updated} | {
        x["to_fact_id"] for x in renamed
    }
    affected_relations = sorted(
        r["relation_id"] for r in target["relations"]
        if r["source_id"] in changed_ids or r["target_id"] in changed_ids
    )
    body = {
        "schema": "simplicio.context-delta/v1", "repo_id": base["repo_id"],
        "base_generation": base["generation"], "target_generation": target["generation"],
        "base_graph_digest": base["graph_digest"],
        "target_graph_digest": target["graph_digest"],
        "created": created, "updated": updated, "renamed": renamed,
        "deleted": deleted, "affected_relation_ids": affected_relations,
        # Canonical target is included so application is transactional and exact.
        "target_graph": target,
    }
    body["delta_digest"] = digest(body)
    return body


def apply_delta(base_graph: Mapping[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    base = validate_graph(base_graph)
    unsigned = dict(delta)
    supplied = unsigned.pop("delta_digest", "")
    if supplied != digest(unsigned):
        raise ContextGraphError("delta_corrupt", supplied)
    if delta.get("schema") != "simplicio.context-delta/v1":
        raise ContextGraphError("delta_schema_invalid", "")
    if base["graph_digest"] != delta.get("base_graph_digest"):
        raise ContextGraphError("delta_base_mismatch", base["graph_digest"])
    target = validate_graph(delta["target_graph"])
    if target["graph_digest"] != delta.get("target_graph_digest"):
        raise ContextGraphError("delta_target_mismatch", target["graph_digest"])
    return target


def batch_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Debounce by logical key: last sequence wins, output order is stable."""
    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    for position, event in enumerate(events):
        key = str(event.get("key", ""))
        if not key:
            raise ContextGraphError("event_key_missing", str(position))
        sequence = int(event.get("sequence", position))
        previous = latest.get(key)
        if previous is None or sequence >= previous[0]:
            latest[key] = (sequence, dict(event))
    return [value[1] for _, value in sorted(latest.items())]


_PACKET_PRIORITY = {"signature": 0, "symbol": 0, "relation": 1, "rule": 2,
                    "test": 3, "route": 4, "screen": 5, "body": 9}


def build_context_packet(graph: Mapping[str, Any], *, max_bytes: int = 8192,
                         max_items: int = 64,
                         ancestor_packet_hash: str | None = None) -> dict[str, Any]:
    clean = validate_graph(graph)
    if max_bytes < 512 or max_items < 1:
        raise ContextGraphError("packet_budget_invalid", str(max_bytes))
    candidates = sorted(clean["facts"], key=lambda f: (
        _PACKET_PRIORITY.get(f["kind"], 6), f["fact_id"]))
    selected, used_content = [], set()
    for item in candidates:
        content_hash = digest({"kind": item["kind"], "value": item["value"],
                               "source": item["provenance"]["source_sha256"]})
        if content_hash in used_content:
            continue
        packet_item = {
            "fact_id": item["fact_id"], "kind": item["kind"],
            "value": item["value"], "content_sha256": content_hash,
            "provenance": item["provenance"],
            "handle": f"mapper://context/{clean['graph_digest']}/{item['fact_id']}",
        }
        candidate = selected + [packet_item]
        probe = {
            "schema": "simplicio.context-packet/v1",
            "graph_digest": clean["graph_digest"], "generation": clean["generation"],
            "items": candidate,
        }
        if len(candidate) > max_items or len(canonical(probe)) > max_bytes:
            break
        selected, used_content = candidate, used_content | {content_hash}
    body = {
        "schema": "simplicio.context-packet/v1",
        "repo_id": clean["repo_id"], "generation": clean["generation"],
        "graph_digest": clean["graph_digest"], "items": selected,
        "coverage": len(selected) / len(candidates) if candidates else 1.0,
        "truncated": len(selected) < len(candidates),
        "omitted_items": len(candidates) - len(selected),
        "budget": {
            "max_bytes": max_bytes, "max_items": max_items,
            "token_count": None, "token_count_null_reason": "TOKENIZER_UNAVAILABLE",
        },
        "ancestor_packet_hash": ancestor_packet_hash,
        "lineage_reason": "INITIAL" if ancestor_packet_hash is None else "EXPANSION",
    }
    body["packet_hash"] = digest(body)
    body["encoded_bytes"] = len(canonical(body))
    return body


def validate_context_packet(packet: Mapping[str, Any], *,
                            expected_generation: str | None = None) -> dict[str, Any]:
    if packet.get("schema") != "simplicio.context-packet/v1":
        raise ContextGraphError("packet_schema_invalid", "")
    unsigned = dict(packet)
    supplied_bytes = unsigned.pop("encoded_bytes", None)
    supplied_hash = unsigned.pop("packet_hash", "")
    if supplied_hash != digest(unsigned):
        raise ContextGraphError("packet_corrupt", supplied_hash)
    if supplied_bytes != len(canonical(packet)):
        # encoded_bytes is informative because including itself changes byte size.
        if not isinstance(supplied_bytes, int) or supplied_bytes < 1:
            raise ContextGraphError("packet_size_invalid", str(supplied_bytes))
    if expected_generation is not None and packet.get("generation") != expected_generation:
        raise ContextGraphError("packet_generation_stale", str(packet.get("generation")))
    return dict(packet)


def expand_context_packet(graph: Mapping[str, Any], packet: Mapping[str, Any], *,
                          max_bytes: int = 16384, max_items: int = 128) -> dict[str, Any]:
    prior = validate_context_packet(packet)
    clean = validate_graph(graph, expected_generation=prior["generation"])
    if clean["graph_digest"] != prior["graph_digest"]:
        raise ContextGraphError("packet_graph_stale", clean["graph_digest"])
    return build_context_packet(
        clean, max_bytes=max_bytes, max_items=max_items,
        ancestor_packet_hash=prior["packet_hash"],
    )


__all__ = ["ContextGraphError", "Provenance", "build_graph", "digest", "fact",
           "apply_delta", "batch_events", "context_delta", "evaluate_evidence",
           "build_context_packet", "expand_context_packet", "limited_export",
           "impact_query", "relation", "tombstone", "validate_context_packet",
           "validate_graph"]
