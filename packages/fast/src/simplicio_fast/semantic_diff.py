"""Deterministic, read-only semantic diff and what-if overlays."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


DIFF_SCHEMA = "simplicio.fast.semantic-diff/v1"
OVERLAY_SCHEMA = "simplicio.fast.what-if-overlay/v1"
RECEIPT_SCHEMA = "simplicio.fast.simulation-receipt/v1"
_KINDS = {"add", "remove", "update"}
MAX_IMPACT_NODES = 100_000
MAX_IMPACT_EDGES = 100_000
MAX_IMPACT_DEPTH = 1_024
MAX_IMPACT_BYTES = 8 * 1024 * 1024


class SemanticDiffError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SemanticDiffError("diff_not_json") from error


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _impact_budget(value: object, reason: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SemanticDiffError(reason)
    return value


@dataclass(frozen=True, slots=True)
class DiffRecord:
    handle: str
    kind: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    source_generation: str
    proposed_generation: str
    reason_code: str
    confidence: float = 1.0
    derived: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.handle, str) or not self.handle.strip():
            raise SemanticDiffError("stable_handle_invalid")
        if self.kind not in _KINDS:
            raise SemanticDiffError("diff_kind_invalid")
        if (
            (self.before is not None and not isinstance(self.before, Mapping))
            or (self.after is not None and not isinstance(self.after, Mapping))
        ):
            raise SemanticDiffError("diff_payload_invalid")
        if (
            (self.kind == "add" and (self.before is not None or self.after is None))
            or (self.kind == "remove" and (self.before is None or self.after is not None))
            or (self.kind == "update" and (self.before is None or self.after is None))
        ):
            raise SemanticDiffError("diff_shape_invalid")
        if (
            not isinstance(self.source_generation, str)
            or not self.source_generation.strip()
            or not isinstance(self.proposed_generation, str)
            or not self.proposed_generation.strip()
        ):
            raise SemanticDiffError("generation_invalid")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise SemanticDiffError("confidence_invalid")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise SemanticDiffError("reason_code_invalid")
        if self.derived and self.confidence >= 1.0:
            raise SemanticDiffError("derived_confidence_invalid")
        try:
            before = deepcopy(self.before) if self.before is not None else None
            after = deepcopy(self.after) if self.after is not None else None
        except (TypeError, ValueError) as error:
            raise SemanticDiffError("diff_payload_invalid") from error
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "kind": self.kind,
            "before": dict(self.before) if self.before is not None else None,
            "after": dict(self.after) if self.after is not None else None,
            "source_generation": self.source_generation,
            "proposed_generation": self.proposed_generation,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "derived": self.derived,
        }


class WhatIfOverlay:
    """Immutable proposal view; no source or base records are modified."""

    def __init__(self, base_generation: str, records: Sequence[DiffRecord]) -> None:
        if not isinstance(base_generation, str) or not base_generation.strip():
            raise SemanticDiffError("generation_invalid")
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise SemanticDiffError("records_invalid")
        if any(not isinstance(item, DiffRecord) for item in records):
            raise SemanticDiffError("records_invalid")
        if any(item.source_generation != base_generation for item in records):
            raise SemanticDiffError("overlay_generation_mismatch")
        keys = [(item.handle, item.kind) for item in records]
        if len(keys) != len(set(keys)):
            raise SemanticDiffError("duplicate_diff_record")
        self.base_generation = base_generation
        self.records = tuple(sorted(records, key=lambda item: (item.handle, item.kind)))

    @property
    def digest(self) -> str:
        return _digest({"base_generation": self.base_generation, "records": [item.to_dict() for item in self.records]})

    def encode(self) -> bytes:
        return _canonical(self.to_dict()) + b"\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OVERLAY_SCHEMA,
            "base_generation": self.base_generation,
            "overlay_digest": self.digest,
            "records": [item.to_dict() for item in self.records],
        }


class SemanticDiff:
    def __init__(self, source_generation: str, proposed_generation: str, records: Sequence[DiffRecord], *, complete: bool = True, truncation_reasons: Sequence[str] = ()) -> None:
        if (
            not isinstance(source_generation, str)
            or not source_generation.strip()
            or not isinstance(proposed_generation, str)
            or not proposed_generation.strip()
        ):
            raise SemanticDiffError("generation_invalid")
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise SemanticDiffError("records_invalid")
        if any(not isinstance(item, DiffRecord) for item in records):
            raise SemanticDiffError("records_invalid")
        if not isinstance(complete, bool):
            raise SemanticDiffError("complete_invalid")
        if (
            not isinstance(truncation_reasons, Sequence)
            or isinstance(truncation_reasons, (str, bytes))
            or any(
                not isinstance(reason, str) or not reason.strip()
                for reason in truncation_reasons
            )
        ):
            raise SemanticDiffError("truncation_reasons_invalid")
        self.source_generation = source_generation
        self.proposed_generation = proposed_generation
        self.records = tuple(sorted(records, key=lambda item: (item.handle, item.kind)))
        self.complete = complete
        self.truncation_reasons = tuple(truncation_reasons)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value = {
            "schema": DIFF_SCHEMA,
            "source_generation": self.source_generation,
            "proposed_generation": self.proposed_generation,
            "records": [item.to_dict() for item in self.records],
            "complete": self.complete,
            "truncation_reasons": list(self.truncation_reasons),
        }
        if include_digest:
            value["diff_digest"] = self.digest
        return value

    def encode(self) -> bytes:
        return _canonical(self.to_dict()) + b"\n"

    def overlay(self) -> WhatIfOverlay:
        return WhatIfOverlay(self.source_generation, self.records)

    def impact(
        self,
        adjacency: Mapping[str, Sequence[str]],
        *,
        max_nodes: int = 1000,
        max_depth: int = MAX_IMPACT_DEPTH,
        max_edges: int = MAX_IMPACT_EDGES,
        max_bytes: int = MAX_IMPACT_BYTES,
    ) -> dict[str, Any]:
        _impact_budget(max_nodes, "impact_budget_invalid", minimum=1, maximum=MAX_IMPACT_NODES)
        _impact_budget(max_depth, "impact_depth_invalid", minimum=0, maximum=MAX_IMPACT_DEPTH)
        _impact_budget(max_edges, "impact_edge_budget_invalid", minimum=0, maximum=MAX_IMPACT_EDGES)
        _impact_budget(max_bytes, "impact_byte_budget_invalid", minimum=1, maximum=MAX_IMPACT_BYTES)
        changed = {item.handle for item in self.records}
        queue: list[tuple[str, int]] = [(handle, 0) for handle in sorted(changed)]
        included: set[str] = set()
        reasons: dict[str, str] = {}
        truncation_reasons: set[str] = set()
        traversed_edges = 0
        used_bytes = 0
        while queue and len(included) < max_nodes:
            node, depth = queue.pop(0)
            if node in included:
                continue
            included.add(node)
            reasons[node] = "direct_change" if node in changed else "dependency_closure"
            targets = sorted(adjacency.get(node, ()))
            if depth >= max_depth and targets:
                truncation_reasons.add("max_depth")
                continue
            for target in targets:
                traversed_edges += 1
                if traversed_edges > max_edges:
                    truncation_reasons.add("max_edges")
                    break
                edge_bytes = len(_canonical({"source": node, "target": target}))
                if used_bytes + edge_bytes > max_bytes:
                    truncation_reasons.add("max_bytes")
                    break
                used_bytes += edge_bytes
                queue.append((target, depth + 1))
        if queue:
            truncation_reasons.add("max_nodes")
        return {
            "schema": "simplicio.fast.impact-explanation/v1",
            "nodes": sorted(included),
            "reasons": reasons,
            "complete": not queue and not truncation_reasons,
            "truncation_reasons": sorted(truncation_reasons),
        }

    def impact_federated(
        self,
        federation: Any,
        *,
        max_nodes: int = 1000,
        max_depth: int = MAX_IMPACT_DEPTH,
        max_edges: int = MAX_IMPACT_EDGES,
        max_bytes: int = MAX_IMPACT_BYTES,
    ) -> dict[str, Any]:
        """Traverse pinned federation consumers; implicit latest is impossible."""
        _impact_budget(max_nodes, "impact_budget_invalid", minimum=1, maximum=MAX_IMPACT_NODES)
        _impact_budget(max_depth, "impact_depth_invalid", minimum=0, maximum=MAX_IMPACT_DEPTH)
        _impact_budget(max_edges, "impact_edge_budget_invalid", minimum=0, maximum=MAX_IMPACT_EDGES)
        _impact_budget(max_bytes, "impact_byte_budget_invalid", minimum=1, maximum=MAX_IMPACT_BYTES)
        queue: list[tuple[str, int]] = [(item.handle, 0) for item in self.records]
        included: set[str] = set()
        reasons: dict[str, str] = {}
        paths: dict[str, list[str]] = {handle: [handle] for handle, _ in queue}
        truncation_reasons: set[str] = set()
        traversed_edges = 0
        used_bytes = 0
        while queue and len(included) < max_nodes:
            current, depth = queue.pop(0)
            if current in included:
                continue
            included.add(current)
            reasons[current] = "direct_change" if current in paths and len(paths[current]) == 1 else "federated_consumer"
            if depth >= max_depth:
                if federation.dependencies(current):
                    truncation_reasons.add("max_depth")
                continue
            for edge in federation.dependencies(current):
                traversed_edges += 1
                if traversed_edges > max_edges:
                    truncation_reasons.add("max_edges")
                    break
                target = edge["target_handle"]
                edge_bytes = len(_canonical({"source": current, "target": target}))
                if used_bytes + edge_bytes > max_bytes:
                    truncation_reasons.add("max_bytes")
                    break
                used_bytes += edge_bytes
                if target not in paths:
                    paths[target] = paths[current] + [target]
                    queue.append((target, depth + 1))
        if queue:
            truncation_reasons.add("max_nodes")
        return {
            "schema": "simplicio.fast.impact-explanation/v1",
            "federation_generation": federation.generation,
            "nodes": sorted(included),
            "reasons": reasons,
            "paths": paths,
            "complete": not queue and not truncation_reasons and self.complete,
            "truncation_reasons": sorted(set(self.truncation_reasons).union(truncation_reasons)) if not self.complete or truncation_reasons else [],
        }


def diff_generations(source: Mapping[str, Mapping[str, Any]], proposed: Mapping[str, Mapping[str, Any]], *, source_generation: str, proposed_generation: str) -> SemanticDiff:
    if not isinstance(source, Mapping) or not isinstance(proposed, Mapping):
        raise SemanticDiffError("diff_input_invalid")
    if any(not isinstance(handle, str) or not handle.strip() for handle in (*source, *proposed)):
        raise SemanticDiffError("stable_handle_invalid")
    records: list[DiffRecord] = []
    for handle in sorted(set(source) | set(proposed)):
        before = source.get(handle)
        after = proposed.get(handle)
        if before is None:
            kind, reason = "add", "handle_added"
        elif after is None:
            kind, reason = "remove", "handle_removed"
        elif _canonical(before) != _canonical(after):
            kind, reason = "update", "payload_changed"
        else:
            continue
        records.append(DiffRecord(handle, kind, before, after, source_generation, proposed_generation, reason))
    return SemanticDiff(source_generation, proposed_generation, records)


__all__ = [
    "DIFF_SCHEMA", "DiffRecord", "MAX_IMPACT_BYTES", "MAX_IMPACT_DEPTH",
    "MAX_IMPACT_EDGES", "MAX_IMPACT_NODES", "SemanticDiff", "SemanticDiffError",
    "WhatIfOverlay", "diff_generations",
]
