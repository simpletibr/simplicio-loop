import hashlib

import pytest

from simplicio_fast.context_adapters import (
    ContextAdapterError,
    adapt_code,
    adapt_knowledge_result,
    adapt_operations_result,
    adapter_manifest,
    compile_context_sources,
)
from simplicio_fast.knowledge_projection import KnowledgeFact, KnowledgeProjection
from simplicio_fast.operations_projection import OperationReceipt, OperationsProjection
from simplicio_fast.projection import ProjectionEnvelope, ProjectionError


def _code() -> ProjectionEnvelope:
    return ProjectionEnvelope.create(
        "code",
        producer="fast-code",
        producer_schema="projection/v1",
        generation="code-g1",
        source_generation="source-g1",
        projection_generation="code-g1",
        stable_handle="code:symbol",
        repository_scope="repo",
        tenant_scope="tenant-a",
        payload={"repository": "repo", "tenant": "tenant-a", "name": "Symbol"},
    )


def test_typed_source_adapters_compose_one_bounded_cross_domain_packet() -> None:
    knowledge = KnowledgeProjection("repo", "tenant-a", "knowledge-g1")
    text = "parser contract"
    knowledge.apply_delta([
        KnowledgeFact(
            "adr", "mapper", "knowledge:contract", "v1", ("fixture:1",),
            "verified", "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            text, "repo", "tenant-a",
        )
    ])
    operations = OperationsProjection("repo", "operations-g1")
    operations.ingest([
        OperationReceipt(
            "operation:1", "attempt", "done", "operations-g1", 1,
            "runtime.receipt/v1", {"event": "validated"},
        )
    ])

    packet = compile_context_sources(
        code=[_code()],
        knowledge=knowledge.query("parser contract"),
        operations=operations.query(),
        repository_scope="repo",
        tenant_scope="tenant-a",
    )

    assert [item["projection_type"] for item in packet["projections"]] == [
        "code", "knowledge", "operations",
    ]
    assert packet["source_generations"] == ["knowledge-g1", "operations-g1", "source-g1"]
    assert packet["projection_generations"] == ["code-g1", "knowledge-g1", "operations-g1"]
    assert packet["authority"] == "facts_only"
    assert packet["instructions"] is False
    assert all("offset" not in str(item).lower() for item in packet["projections"])


def test_adapter_manifest_is_explicitly_read_only() -> None:
    manifest = adapter_manifest()
    assert manifest["schema"] == "simplicio.fast.context-source-adapters/v1"
    assert {name: value["status"] for name, value in manifest["sources"].items()} == {
        "code": "supported", "knowledge": "supported", "operations": "supported",
    }
    assert manifest["authority"] == "derived_read_only"


def test_adapters_reject_foreign_scope_and_untyped_code() -> None:
    with pytest.raises(ContextAdapterError, match="context_code_invalid"):
        adapt_code([ProjectionEnvelope.create(
            "knowledge", producer="p", producer_schema="p/v1", generation="g1",
            stable_handle="knowledge:x", payload={"repository": "repo"},
        )])
    with pytest.raises(ContextAdapterError, match="context_knowledge_schema_invalid"):
        adapt_knowledge_result({}, repository_scope="repo")
    with pytest.raises(ContextAdapterError, match="context_scope_mismatch"):
        adapt_knowledge_result(
            {
                "schema": "simplicio.fast.precedent-result/v1",
                "repository": "other",
                "scope": "tenant-a",
                "generation": "g1",
                "results": [],
            },
            repository_scope="repo",
        )


def test_operations_adapter_rejects_foreign_scope_and_private_layout() -> None:
    with pytest.raises(ContextAdapterError, match="context_scope_mismatch"):
        adapt_operations_result(
            [{
                "handle": "operation:foreign",
                "generation": "g1",
                "payload": {"repository": "other"},
            }],
            repository_scope="repo",
        )
    with pytest.raises(ProjectionError, match="projection_exposes_offset"):
        adapt_operations_result(
            [{
                "handle": "operation:private",
                "generation": "g1",
                "payload": {"offset": 4},
            }],
            repository_scope="repo",
        )


def test_compile_context_sources_preserves_compiler_budget_contract() -> None:
    packet = compile_context_sources(
        code=[_code()], repository_scope="repo", tenant_scope="tenant-a", max_items=1,
    )
    assert packet["projection_count"] == 1
    with pytest.raises(ContextAdapterError, match="context_repository_invalid"):
        compile_context_sources(code=[_code()])
