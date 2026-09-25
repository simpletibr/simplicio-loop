"""Canonical, read-only adapters from typed projection results to context envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .operations_projection import PROJECTION_SCHEMA as OPERATIONS_SCHEMA
from .projection import ProjectionEnvelope
from .universal_context import UniversalContextError, compile_context


ADAPTER_MANIFEST_SCHEMA = "simplicio.fast.context-source-adapters/v1"
KNOWLEDGE_RESULT_SCHEMA = "simplicio.fast.precedent-result/v1"


class ContextAdapterError(ValueError):
    """Raised when a typed source result cannot be adapted safely."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def adapter_manifest() -> dict[str, Any]:
    """Return the promoted source-adapter contract without claiming parity."""
    return {
        "schema": ADAPTER_MANIFEST_SCHEMA,
        "sources": {
            "code": {"input": "projection-envelope/v1", "status": "supported"},
            "knowledge": {"input": KNOWLEDGE_RESULT_SCHEMA, "status": "supported"},
            "operations": {"input": OPERATIONS_SCHEMA, "status": "supported"},
        },
        "authority": "derived_read_only",
        "forbidden": ["source_mutation", "mcp_authority", "mmap_offsets"],
    }


def adapt_code(projections: Sequence[ProjectionEnvelope]) -> tuple[ProjectionEnvelope, ...]:
    """Validate and preserve the bounded Code/#240 envelope output."""
    items = _bounded_sequence(projections, "context_code_invalid")
    if any(not isinstance(item, ProjectionEnvelope) or item.projection_type != "code" for item in items):
        raise ContextAdapterError("context_code_invalid")
    return items  # type: ignore[return-value]


def adapt_knowledge_result(
    result: Mapping[str, Any],
    *,
    repository_scope: str,
    tenant_scope: str | None = None,
) -> tuple[ProjectionEnvelope, ...]:
    """Adapt a bounded KnowledgeProjection query result without source access."""
    _require_scope(repository_scope, "context_repository_invalid")
    if not isinstance(result, Mapping) or result.get("schema") != KNOWLEDGE_RESULT_SCHEMA:
        raise ContextAdapterError("context_knowledge_schema_invalid")
    if result.get("repository") != repository_scope:
        raise ContextAdapterError("context_scope_mismatch")
    result_scope = result.get("scope")
    if not isinstance(result_scope, str) or not result_scope.strip():
        raise ContextAdapterError("context_knowledge_scope_invalid")
    if tenant_scope is not None and tenant_scope != result_scope:
        raise ContextAdapterError("context_scope_mismatch")
    generation = result.get("generation")
    if not isinstance(generation, str) or not generation.strip():
        raise ContextAdapterError("context_generation_invalid")
    items = _bounded_sequence(result.get("results"), "context_knowledge_results_invalid")
    adapted: list[ProjectionEnvelope] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ContextAdapterError("context_knowledge_item_invalid")
        handle = item.get("stable_handle")
        if not isinstance(handle, str) or not handle.strip():
            raise ContextAdapterError("context_knowledge_item_invalid")
        explain = item.get("explain", {})
        if not isinstance(explain, Mapping):
            raise ContextAdapterError("context_knowledge_item_invalid")
        payload = {
            "repository": repository_scope,
            "tenant": result_scope,
            "content_class": "fact",
            "freshness": explain.get("freshness", "generation_pinned"),
            "trust": item.get("trust", "derived_fact"),
            "source_type": item.get("source_type"),
            "version": item.get("version"),
            "provenance": item.get("provenance"),
            "source_digest": item.get("digest"),
            "result": dict(item),
        }
        adapted.append(
            ProjectionEnvelope.create(
                "knowledge",
                producer="knowledge_projection",
                producer_schema=KNOWLEDGE_RESULT_SCHEMA,
                generation=generation,
                source_generation=generation,
                projection_generation=generation,
                stable_handle=handle,
                repository_scope=repository_scope,
                tenant_scope=result_scope,
                payload=payload,
            )
        )
    return tuple(adapted)


def adapt_operations_result(
    result: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    *,
    repository_scope: str,
    tenant_scope: str | None = None,
) -> tuple[ProjectionEnvelope, ...]:
    """Adapt OperationsProjection query/snapshot receipts to evidence envelopes."""
    _require_scope(repository_scope, "context_repository_invalid")
    if isinstance(result, Mapping):
        if result.get("schema") != OPERATIONS_SCHEMA:
            raise ContextAdapterError("context_operations_schema_invalid")
        receipts = result.get("receipts")
        default_generation = result.get("generation")
    else:
        receipts = result
        default_generation = None
    items = _bounded_sequence(receipts, "context_operations_results_invalid")
    adapted: list[ProjectionEnvelope] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ContextAdapterError("context_operations_item_invalid")
        handle = item.get("handle")
        item_generation = item.get("generation", default_generation)
        if (
            not isinstance(handle, str)
            or not handle.strip()
            or not isinstance(item_generation, str)
            or not item_generation.strip()
        ):
            raise ContextAdapterError("context_operations_item_invalid")
        payload = item.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ContextAdapterError("context_operations_item_invalid")
        payload_copy = dict(payload)
        if payload_copy.get("repository") not in {None, repository_scope}:
            raise ContextAdapterError("context_scope_mismatch")
        if tenant_scope is not None and payload_copy.get("tenant") not in {None, tenant_scope}:
            raise ContextAdapterError("context_scope_mismatch")
        payload_copy.update(
            {
                "repository": repository_scope,
                "content_class": "evidence",
                "trust": payload_copy.get("trust", "advisory"),
                "freshness": payload_copy.get("freshness", "generation_pinned"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "sequence": item.get("sequence"),
                "source_schema": item.get("source_schema"),
                "consistency": item.get("consistency", "consistent"),
            }
        )
        if tenant_scope is not None:
            payload_copy["tenant"] = tenant_scope
        adapted.append(
            ProjectionEnvelope.create(
                "operations",
                producer="operations_projection",
                producer_schema=OPERATIONS_SCHEMA,
                generation=item_generation,
                source_generation=item_generation,
                projection_generation=item_generation,
                stable_handle=handle,
                repository_scope=repository_scope,
                tenant_scope=tenant_scope or "*",
                payload=payload_copy,
            )
        )
    return tuple(adapted)


def compile_context_sources(
    *,
    code: Sequence[ProjectionEnvelope] = (),
    knowledge: Mapping[str, Any] | None = None,
    operations: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    repository_scope: str | None = None,
    tenant_scope: str | None = None,
    **budget_options: Any,
) -> dict[str, Any]:
    """Compose typed Code, Knowledge and Operations results into one packet."""
    if repository_scope is None or not isinstance(repository_scope, str) or not repository_scope.strip():
        raise ContextAdapterError("context_repository_invalid")
    envelopes = list(adapt_code(code))
    if knowledge is not None:
        envelopes.extend(
            adapt_knowledge_result(
                knowledge,
                repository_scope=repository_scope,
                tenant_scope=tenant_scope,
            )
        )
    if operations is not None:
        envelopes.extend(
            adapt_operations_result(
                operations,
                repository_scope=repository_scope,
                tenant_scope=tenant_scope,
            )
        )
    try:
        return compile_context(
            envelopes,
            repository_scope=repository_scope,
            tenant_scope=tenant_scope,
            **budget_options,
        )
    except UniversalContextError:
        raise


def _bounded_sequence(value: object, reason: str) -> tuple[Any, ...]:
    if value is None or isinstance(value, (str, bytes)):
        raise ContextAdapterError(reason)
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise ContextAdapterError(reason) from error
    if len(items) > 100_000:
        raise ContextAdapterError(reason)
    return items


def _require_scope(value: object, reason: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContextAdapterError(reason)


__all__ = [
    "ADAPTER_MANIFEST_SCHEMA",
    "ContextAdapterError",
    "adapt_code",
    "adapt_knowledge_result",
    "adapt_operations_result",
    "adapter_manifest",
    "compile_context_sources",
]
