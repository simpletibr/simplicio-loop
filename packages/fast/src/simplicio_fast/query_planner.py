"""Deterministic, budget-aware query planning over a validated Fast snapshot."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any

from .snapshot import SYMBOL_RECORD, Snapshot


PLAN_SCHEMA = "simplicio.fast.query-plan/v1"
CACHE_SCHEMA = "simplicio.fast.query-plan-cache/v1"


@dataclass(frozen=True, slots=True)
class QueryPlan:
    schema: str
    generation: str
    operation: str
    term: str
    selected_index: str
    candidate_records: int
    estimated_bytes: int
    max_results: int
    max_bytes: int
    max_tokens: int
    prefetch: tuple[str, ...]
    reason: str
    request_digest: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["prefetch"] = list(self.prefetch)
        return value


class QueryPlanCache:
    """Bounded cache whose key is exactly (snapshot generation, request digest)."""

    def __init__(self, max_entries: int = 128) -> None:
        if max_entries < 1:
            raise ValueError("query-plan cache capacity must be positive")
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str], QueryPlan] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, generation: str, request_digest: str) -> QueryPlan | None:
        key = (generation, request_digest)
        plan = self._entries.get(key)
        if plan is None:
            self._misses += 1
            return None
        self._hits += 1
        self._entries.move_to_end(key)
        return plan

    def put(self, plan: QueryPlan) -> QueryPlan:
        key = (plan.generation, plan.request_digest)
        self._entries[key] = plan
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return plan

    def invalidate_generation(self, generation: str) -> int:
        keys = [key for key in self._entries if key[0] == generation]
        for key in keys:
            del self._entries[key]
        return len(keys)

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "schema": CACHE_SCHEMA,
            "size": len(self._entries),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total else 0.0,
            "generations": sorted({generation for generation, _ in self._entries}),
        }


def _request_digest(
    term: str,
    *,
    operation: str,
    prefix: bool,
    path: str | None,
    kind: str | None,
    max_results: int,
    max_bytes: int,
    max_tokens: int,
) -> str:
    request = {
        "schema": PLAN_SCHEMA,
        "term": term,
        "operation": operation,
        "prefix": prefix,
        "path": path,
        "kind": kind,
        "max_results": max_results,
        "max_bytes": max_bytes,
        "max_tokens": max_tokens,
    }
    encoded = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _intersection(*values: list[int]) -> list[int]:
    if not values:
        return []
    result = set(values[0])
    for value in values[1:]:
        result.intersection_update(value)
    return sorted(result)


def _causal_prefetch(
    snapshot: Snapshot, indices: list[int], max_items: int
) -> tuple[str, ...]:
    if not indices or max_items < 1:
        return ()
    origins = {snapshot._symbol_at(index).qualified_name for index in indices}
    ranked = sorted(
        (
            (relation.confidence, relation.destination)
            for relation in snapshot.relations()
            if relation.origin in origins and relation.destination
        ),
        key=lambda item: (-item[0], item[1]),
    )
    result: list[str] = []
    seen: set[str] = set()
    for _confidence, destination in ranked:
        if destination in seen:
            continue
        seen.add(destination)
        result.append(destination)
        if len(result) >= max_items:
            break
    return tuple(result)


def plan_query(
    snapshot: Snapshot,
    term: str,
    *,
    operation: str = "query",
    prefix: bool = False,
    path: str | None = None,
    kind: str | None = None,
    max_results: int = 50,
    max_bytes: int = 32_000,
    max_tokens: int = 8_000,
    cache: QueryPlanCache | None = None,
) -> QueryPlan:
    if operation not in {"query", "search", "context", "impact"}:
        raise ValueError("unsupported query-plan operation")
    if min(max_results, max_bytes, max_tokens) < 1:
        raise ValueError("query-plan budgets must be positive")
    request_digest = _request_digest(
        term,
        operation=operation,
        prefix=prefix,
        path=path,
        kind=kind,
        max_results=max_results,
        max_bytes=max_bytes,
        max_tokens=max_tokens,
    )
    if cache is not None:
        cached = cache.get(snapshot.generation, request_digest)
        if cached is not None:
            return cached

    candidate_indices: list[int] = []
    if snapshot.format_version == 1:
        selected = "legacy-linear-scan"
        candidate_records = (
            snapshot.symbol_count if operation != "impact" else snapshot.relation_count
        )
        reason = "legacy_snapshot_has_no_direct_indexes"
    elif operation == "impact":
        selected = "relation-scan"
        candidate_records = snapshot.relation_count
        reason = "impact_requires_typed_relation_filter"
    else:
        indexes = snapshot._indexes()
        exact_values = indexes["exact"].get(term.casefold(), [])
        filters: list[list[int]] = []
        if exact_values and not prefix:
            selected = "exact"
            filters.append(exact_values)
            reason = "exact_index_hit"
        elif prefix:
            selected = "name-prefix"
            filters.append(
                [
                    index
                    for name, values in indexes["names"].items()
                    if name.startswith(term.casefold())
                    for index in values
                ]
            )
            reason = "prefix_index_scan"
        else:
            selected = "name-substring"
            filters.append(
                [
                    index
                    for name, values in indexes["names"].items()
                    if term.casefold() in name
                    for index in values
                ]
            )
            filters.append(
                [
                    index
                    for name, values in indexes["exact"].items()
                    if term.casefold() in name
                    for index in values
                ]
            )
            reason = "bounded_name_indexes"
        if path is not None:
            selected += "+path"
            filters.append(indexes["paths"].get(path, []))
        if kind is not None:
            selected += "+kind"
            filters.append(indexes["kinds"].get(kind, []))
        candidate_indices = _intersection(*filters) if filters else []
        candidate_records = len(candidate_indices)
    plan = QueryPlan(
        schema=PLAN_SCHEMA,
        generation=snapshot.generation,
        operation=operation,
        term=term,
        selected_index=selected,
        candidate_records=candidate_records,
        estimated_bytes=min(max_bytes, candidate_records * SYMBOL_RECORD.size),
        max_results=max_results,
        max_bytes=max_bytes,
        max_tokens=max_tokens,
        prefetch=_causal_prefetch(snapshot, candidate_indices, min(max_results, 8))
        if operation in {"query", "search", "context"}
        else (),
        reason=reason,
        request_digest=request_digest,
    )
    return cache.put(plan) if cache is not None else plan
