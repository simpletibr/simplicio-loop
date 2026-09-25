"""Bounded knowledge facade over host-authorized Fast skill handles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from typing import Any

from .skills import SkillCatalog
from .tokenizers import resolve_tokenizer

KNOWLEDGE_RESOLUTION_SCHEMA = "simplicio.fast.knowledge-resolution/v1"
KNOWLEDGE_MATERIALIZATION_SCHEMA = "simplicio.fast.knowledge-materialization/v1"
KNOWLEDGE_SOURCES = ("skills", "memory", "context")
_UNAVAILABLE_SOURCES = frozenset(("memory", "context"))


def _positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _scope(expected: str, actual: str | None) -> None:
    if actual is not None and actual != expected:
        raise ValueError("knowledge scope does not match catalog scope")


def _tokens(value: str, tokenizer: Callable[[str], int] | None = None) -> int:
    if tokenizer is None:
        return len(value.split())
    try:
        count = tokenizer(value)
    except Exception as error:
        raise ValueError("knowledge_tokenizer_failed") from error
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("knowledge_tokenizer_invalid")
    return count


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class KnowledgeFacade:
    """Expose bounded T0 discovery and explicit source availability.

    Skills are host-authorized and returned as opaque handles. Memory and context
    remain explicit Runtime-dependent unavailable sources in this standalone slice.
    """

    def __init__(self, catalog: SkillCatalog) -> None:
        self.catalog = catalog

    @property
    def repository(self) -> str:
        return str(self.catalog.repository)

    @property
    def generation(self) -> str:
        return self.catalog.generation

    @property
    def scope(self) -> str:
        return self.catalog.scope

    def register(self, skill: Any) -> str:
        return self.catalog.register(skill)

    def register_many(self, skills: Iterable[Any]) -> list[str]:
        return self.catalog.register_many(skills)

    def _sources(self, sources: Iterable[str]) -> tuple[str, ...]:
        selected = tuple(dict.fromkeys(sources))
        if not selected or any(source not in KNOWLEDGE_SOURCES for source in selected):
            raise ValueError("sources must contain only skills, memory, or context")
        return selected

    def resolve(
        self,
        task: str,
        *,
        sources: Iterable[str] = KNOWLEDGE_SOURCES,
        max_results: int = 32,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Return T0 metadata, handles, provenance, and source status."""
        _positive(max_results, "max_results")
        _scope(self.scope, scope)
        selected = self._sources(sources)
        skill_result = (
            self.catalog.resolve(task, max_results=max_results)
            if "skills" in selected
            else None
        )
        source_status: dict[str, dict[str, Any]] = {}
        for source in selected:
            if source == "skills":
                source_status[source] = {
                    "status": "available",
                    "runtime_required": False,
                    "reason_code": skill_result["reason_code"],
                }
            else:
                source_status[source] = {
                    "status": "unavailable",
                    "runtime_required": True,
                    "reason_code": "runtime_source_unavailable",
                }
        body: dict[str, Any] = {
            "schema": KNOWLEDGE_RESOLUTION_SCHEMA,
            "repository": self.repository,
            "generation": self.generation,
            "scope": self.scope,
            "query": {"task": task, "sources": list(selected)},
            "sources": source_status,
            "skills": skill_result["skills"] if skill_result else [],
            "handles": skill_result["handles"] if skill_result else [],
            "truncated": skill_result["truncated"] if skill_result else False,
        }
        return {
            **body,
            "provenance": {
                "repository": self.repository,
                "generation": self.generation,
                "scope": self.scope,
                "sources": list(selected),
            },
            "receipt_digest": _digest(body),
        }

    def expand_handles(
        self,
        handles: Iterable[str],
        *,
        max_entries: int = 16,
        max_bytes: int = 256 * 1024,
        max_tokens: int = 4096,
        scope: str | None = None,
        tokenizer_id: str | None = None,
        tokenizer: Callable[[str], int] | None = None,
    ) -> dict[str, Any]:
        """Materialize handles within byte and explicitly labelled token budgets."""
        _positive(max_entries, "max_entries")
        _positive(max_bytes, "max_bytes")
        _positive(max_tokens, "max_tokens")
        _scope(self.scope, scope)
        if tokenizer_id is not None and (
            not isinstance(tokenizer_id, str) or not tokenizer_id.strip()
        ):
            raise ValueError("knowledge_tokenizer_invalid")
        if tokenizer is not None and (not callable(tokenizer) or not tokenizer_id):
            raise ValueError("knowledge_tokenizer_invalid")
        resolved_tokenizer = tokenizer or resolve_tokenizer(tokenizer_id)
        effective_tokenizer_id = tokenizer_id or "estimated:word-split-v1"
        resolved = self.catalog.materialize(
            handles, max_entries=max_entries, max_bytes=max_bytes
        )
        materialized: list[dict[str, Any]] = []
        token_total = 0
        token_limited = False
        for item in resolved["materialized"]:
            measured_tokens = _tokens(item["content"], resolved_tokenizer)
            if token_total + measured_tokens > max_tokens:
                token_limited = True
                break
            enriched = dict(item)
            enriched["estimated_tokens"] = measured_tokens if resolved_tokenizer is None else None
            enriched["tokens"] = measured_tokens if resolved_tokenizer is not None else None
            materialized.append(enriched)
            token_total += measured_tokens
        bytes_total = sum(len(item["content"].encode("utf-8")) for item in materialized)
        truncated = bool(
            resolved["truncated"]
            or token_limited
            or len(materialized) < len(resolved["materialized"])
        )
        reason_code = (
            "token_budget_exceeded" if token_limited else resolved["reason_code"]
        )
        body: dict[str, Any] = {
            "schema": KNOWLEDGE_MATERIALIZATION_SCHEMA,
            "repository": self.repository,
            "generation": self.generation,
            "scope": self.scope,
            "source": {
                "kind": "skills",
                "status": "available",
                "runtime_required": False,
            },
            "references": [item["handle"] for item in materialized],
            "materialized": materialized,
            "entries_materialized": len(materialized),
            "bytes_materialized": bytes_total,
            "estimated_tokens": token_total if resolved_tokenizer is None else None,
            "tokens": token_total if resolved_tokenizer is not None else None,
            "token_measurement": "provider-exact" if resolved_tokenizer is not None else "whitespace-v1-estimate",
            "tokenizer": {
                "mode": "exact" if resolved_tokenizer is not None else "estimated",
                "id": effective_tokenizer_id,
                "reason": (
                    None
                    if resolved_tokenizer is not None
                    else "provider_tokenizer_unavailable"
                    if tokenizer_id
                    else "tokenizer_unconfigured"
                ),
            },
            "truncated": truncated,
            "reason_code": reason_code,
        }
        return {
            **body,
            "provenance": {
                "repository": self.repository,
                "generation": self.generation,
                "scope": self.scope,
                "source": "skills",
            },
            "receipt_digest": _digest(body),
        }

    def materialize(self, handles: Iterable[str], **kwargs: Any) -> dict[str, Any]:
        """Compatibility alias for callers that use the catalog vocabulary."""
        return self.expand_handles(handles, **kwargs)

    def projection(self, task: str, **kwargs: Any):
        """Return the bounded knowledge view in the shared projection ABI."""
        from .projection import ProjectionEnvelope

        resolved = self.resolve(task, **kwargs)
        return ProjectionEnvelope.create(
            "knowledge",
            producer="simplicio-fast.knowledge",
            producer_schema=KNOWLEDGE_RESOLUTION_SCHEMA,
            generation=self.generation,
            stable_handle=f"knowledge:{self.generation}:{resolved['receipt_digest']}",
            payload=resolved,
        )


__all__ = [
    "KNOWLEDGE_MATERIALIZATION_SCHEMA",
    "KNOWLEDGE_RESOLUTION_SCHEMA",
    "KNOWLEDGE_SOURCES",
    "KnowledgeFacade",
]
