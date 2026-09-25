"""Bounded, provenance-preserving Knowledge facts and precedent queries."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence


FACT_SCHEMA = "simplicio.fast.knowledge-fact/v1"
PROJECTION_SCHEMA = "simplicio.fast.knowledge-projection/v1"
QUERY_SCHEMA = "simplicio.fast.precedent-query/v1"
RESULT_SCHEMA = "simplicio.fast.precedent-result/v1"
HANDOFF_SCHEMA = "simplicio.fast.knowledge-handoff/v1"
AUTHORIZED_PRODUCERS = frozenset({"mapper", "runtime"})
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*")
_ACTIVE = "active"
_INACTIVE = frozenset({"revoked", "expired", "conflicted", "tombstoned"})
_TRUST_RANK = {
    "untrusted": 0,
    "derived_fact": 1,
    "advisory": 2,
    "verified": 3,
    "authoritative": 4,
}
MAX_FACTS = 100_000
MAX_QUERY_RESULTS = 10_000
MAX_QUERY_BYTES = 8 * 1024 * 1024
MAX_QUERY_TOKENS = 1_000_000


class KnowledgeProjectionError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(value.casefold()))


def _string_sequence(value: object, reason: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise KnowledgeProjectionError(reason)
    if required and not value:
        raise KnowledgeProjectionError(reason)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise KnowledgeProjectionError(reason)
    return tuple(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class KnowledgeFact:
    source_type: str
    producer: str
    stable_handle: str
    version: str
    provenance: tuple[str, ...]
    trust: str
    digest: str
    text: str
    repository: str
    scope: str
    valid_from: int | None = None
    valid_until: int | None = None
    state: str = _ACTIVE
    applicability: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = (self.source_type, self.producer, self.stable_handle, self.version, self.trust, self.digest, self.repository, self.scope)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise KnowledgeProjectionError("fact_identity_invalid")
        provenance = _string_sequence(self.provenance, "fact_provenance_invalid", required=True)
        applicability = _string_sequence(self.applicability, "fact_applicability_invalid")
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "applicability", applicability)
        if not isinstance(self.text, str):
            raise KnowledgeProjectionError("fact_text_invalid")
        for value in (self.valid_from, self.valid_until):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise KnowledgeProjectionError("fact_temporal_bounds_invalid")
        if self.state not in {_ACTIVE, *_INACTIVE}:
            raise KnowledgeProjectionError("fact_state_invalid")
        if self.valid_from is not None and self.valid_until is not None and self.valid_from > self.valid_until:
            raise KnowledgeProjectionError("fact_temporal_bounds_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FACT_SCHEMA,
            "source_type": self.source_type,
            "producer": self.producer,
            "stable_handle": self.stable_handle,
            "version": self.version,
            "provenance": list(self.provenance),
            "trust": self.trust,
            "digest": self.digest,
            "text": self.text,
            "repository": self.repository,
            "scope": self.scope,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "state": self.state,
            "applicability": list(self.applicability),
        }


class KnowledgeProjection:
    """Derived index fed by producer adapters; no direct database access."""

    def __init__(self, repository: str, scope: str, generation: str) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (repository, scope, generation)):
            raise KnowledgeProjectionError("projection_scope_invalid")
        self.repository = repository
        self.scope = scope
        self.generation = generation
        self._facts: dict[str, KnowledgeFact] = {}
        self._conflicts: set[str] = set()
        self._tombstones: set[str] = set()
        self._lock = RLock()

    def apply_delta(self, facts: Iterable[KnowledgeFact] = (), tombstones: Iterable[str] = ()) -> dict[str, Any]:
        try:
            incoming = tuple(facts)
            deleted = sorted(_string_sequence(tuple(tombstones), "tombstone_invalid"))
        except TypeError as error:
            raise KnowledgeProjectionError("delta_input_invalid") from error
        if any(not isinstance(fact, KnowledgeFact) for fact in incoming):
            raise KnowledgeProjectionError("fact_type_invalid")
        with self._lock:
            if any(fact.repository != self.repository or fact.scope != self.scope for fact in incoming):
                raise KnowledgeProjectionError("fact_scope_mismatch")
            prospective = set(self._facts)
            prospective.update(fact.stable_handle for fact in incoming)
            prospective.difference_update(deleted)
            if len(prospective) > MAX_FACTS:
                raise KnowledgeProjectionError("fact_count_limit")
            changed: list[str] = []
            for fact in incoming:
                previous = self._facts.get(fact.stable_handle)
                if previous is not None:
                    if previous.digest == fact.digest and previous.version == fact.version:
                        if previous.state != fact.state:
                            self._facts[fact.stable_handle] = fact
                            self._conflicts.discard(fact.stable_handle)
                            changed.append(fact.stable_handle)
                            continue
                        self._tombstones.discard(fact.stable_handle)
                        continue
                    self._conflicts.add(fact.stable_handle)
                    changed.append(fact.stable_handle)
                    continue
                self._facts[fact.stable_handle] = fact
                self._tombstones.discard(fact.stable_handle)
                changed.append(fact.stable_handle)
            for handle in deleted:
                self._facts.pop(handle, None)
                self._conflicts.discard(handle)
                self._tombstones.add(handle)
            return {"schema": "simplicio.fast.knowledge-delta/v1", "generation": self.generation, "changed_handles": sorted(set(changed)), "tombstones": deleted, "conflicts": sorted(self._conflicts)}

    def apply_handoff(self, handoff: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a bounded Mapper/Runtime handoff without opening producer storage."""
        if not isinstance(handoff, Mapping) or handoff.get("schema") != HANDOFF_SCHEMA:
            raise KnowledgeProjectionError("handoff_schema_invalid")
        producer = handoff.get("producer")
        producer_schema = handoff.get("producer_schema")
        if producer not in AUTHORIZED_PRODUCERS:
            raise KnowledgeProjectionError("handoff_producer_untrusted")
        if not isinstance(producer_schema, str) or not producer_schema.strip():
            raise KnowledgeProjectionError("handoff_producer_schema_invalid")
        if any(handoff.get(key) != expected for key, expected in (
            ("repository", self.repository),
            ("scope", self.scope),
            ("generation", self.generation),
        )):
            raise KnowledgeProjectionError("handoff_scope_mismatch")
        raw_facts = handoff.get("facts")
        raw_tombstones = handoff.get("tombstones", [])
        if not isinstance(raw_facts, list) or not isinstance(raw_tombstones, list):
            raise KnowledgeProjectionError("handoff_payload_invalid")
        if any(not isinstance(item, Mapping) for item in raw_facts):
            raise KnowledgeProjectionError("handoff_fact_invalid")
        if any(not isinstance(item, str) or not item.strip() for item in raw_tombstones):
            raise KnowledgeProjectionError("handoff_tombstone_invalid")
        facts: list[KnowledgeFact] = []
        for item in raw_facts:
            if item.get("producer") != producer:
                raise KnowledgeProjectionError("handoff_producer_mismatch")
            try:
                fact_payload = dict(item)
                if fact_payload.pop("schema", FACT_SCHEMA) != FACT_SCHEMA:
                    raise KnowledgeProjectionError("handoff_fact_invalid")
                facts.append(KnowledgeFact(**fact_payload))
            except (KnowledgeProjectionError, TypeError) as error:
                raise KnowledgeProjectionError("handoff_fact_invalid") from error
        delta = self.apply_delta(facts, raw_tombstones)
        return {
            **delta,
            "producer": producer,
            "producer_schema": producer_schema,
            "handoff_schema": HANDOFF_SCHEMA,
        }

    def query(
        self,
        task: str,
        *,
        max_results: int = 32,
        max_bytes: int = 256 * 1024,
        max_tokens: int = 4096,
        source_types: Sequence[str] = (),
        as_of: int | None = None,
        trust_floor: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(task, str):
            raise KnowledgeProjectionError("query_task_invalid")
        if source_types:
            _string_sequence(source_types, "query_source_types_invalid")
        if trust_floor is not None and trust_floor not in _TRUST_RANK:
            raise KnowledgeProjectionError("query_trust_invalid")
        if (
            not task
            or isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 0 < max_results <= MAX_QUERY_RESULTS
            or isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 0 < max_bytes <= MAX_QUERY_BYTES
            or isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 0 < max_tokens <= MAX_QUERY_TOKENS
            or (as_of is not None and (isinstance(as_of, bool) or not isinstance(as_of, int) or as_of < 0))
        ):
            raise KnowledgeProjectionError("query_budget_invalid")
        with self._lock:
            task_terms = _tokens(task)
            candidates: list[dict[str, Any]] = []
            for fact in self._facts.values():
                if fact.stable_handle in self._conflicts or fact.stable_handle in self._tombstones or fact.state in _INACTIVE or (source_types and fact.source_type not in source_types):
                    continue
                if trust_floor is not None and _TRUST_RANK.get(fact.trust, -1) < _TRUST_RANK[trust_floor]:
                    continue
                if as_of is not None and ((fact.valid_from is not None and as_of < fact.valid_from) or (fact.valid_until is not None and as_of > fact.valid_until)):
                    continue
                matched = sorted(task_terms.intersection(_tokens(fact.text)))
                relevance = len(matched)
                if not relevance:
                    continue
                item = {
                    "stable_handle": fact.stable_handle,
                    "source_type": fact.source_type,
                    "producer": fact.producer,
                    "version": fact.version,
                    "provenance": list(fact.provenance),
                    "trust": fact.trust,
                    "digest": fact.digest,
                    "repository": fact.repository,
                    "scope": fact.scope,
                    "explain": {"relevance": relevance, "trust": fact.trust, "freshness": "as_of" if as_of is not None else "current", "applicability": list(fact.applicability), "matched_terms": matched, "ranking": "lexical-fallback"},
                }
                item["_sort"] = (-relevance, fact.stable_handle, fact.version)
                candidates.append(item)
            candidates.sort(key=lambda item: item.pop("_sort"))
            selected: list[dict[str, Any]] = []
            bytes_used = 0
            tokens_used = 0
            reasons: list[str] = []
            for item in candidates[:max_results]:
                encoded_size = len(json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                estimated = len(json.dumps(item).split())
                if bytes_used + encoded_size > max_bytes:
                    reasons.append("byte_budget")
                    break
                if tokens_used + estimated > max_tokens:
                    reasons.append("token_budget")
                    break
                selected.append(item)
                bytes_used += encoded_size
                tokens_used += estimated
            return {"schema": RESULT_SCHEMA, "query_schema": QUERY_SCHEMA, "projection_schema": PROJECTION_SCHEMA, "repository": self.repository, "scope": self.scope, "generation": self.generation, "trust_floor": trust_floor, "handles": [item["stable_handle"] for item in selected], "results": selected, "truncated": bool(reasons) or len(candidates) > len(selected), "truncation_reasons": sorted(set(reasons))}

    def snapshot(self) -> dict[str, Any]:
        """Return a bounded metadata snapshot without exposing producer storage."""
        with self._lock:
            return {
                "schema": PROJECTION_SCHEMA,
                "repository": self.repository,
                "scope": self.scope,
                "generation": self.generation,
                "handles": sorted(self._facts),
                "conflicts": sorted(self._conflicts),
                "tombstones": sorted(self._tombstones),
            }


__all__ = [
    "FACT_SCHEMA", "KnowledgeFact", "KnowledgeProjection", "KnowledgeProjectionError",
    "AUTHORIZED_PRODUCERS", "HANDOFF_SCHEMA",
    "MAX_FACTS", "MAX_QUERY_BYTES", "MAX_QUERY_RESULTS", "MAX_QUERY_TOKENS",
    "PROJECTION_SCHEMA", "QUERY_SCHEMA", "RESULT_SCHEMA",
]
