import pytest

from simplicio_fast.federation import FederatedEdge, FederationMember, compile_federation
from simplicio_fast.knowledge_projection import KnowledgeFact, KnowledgeProjection
from simplicio_fast.operations_projection import OperationReceipt, OperationsProjection
from simplicio_fast.projection import ProjectionEnvelope
from simplicio_fast.projection import ProjectionError
from simplicio_fast.semantic_diff import diff_generations
from simplicio_fast.universal_context import compile_context
from simplicio_fast.universal_context import UniversalContextError


def test_synthetic_cross_domain_e2e_is_deterministic_and_handle_only() -> None:
    code = ProjectionEnvelope.create("code", producer="mapper", producer_schema="mapper/v1", generation="g1", stable_handle="code:symbol", payload={"repository": "repo-a", "name": "Symbol"})
    knowledge_index = KnowledgeProjection("repo-a", "tenant-a", "g1")
    knowledge_index.apply_delta([KnowledgeFact("adr", "mapper", "knowledge:adr", "v1", ("fixture:adr",), "verified", "sha256:adr", "Symbol contract", "repo-a", "tenant-a")])
    knowledge_result = knowledge_index.query("Symbol")
    knowledge = ProjectionEnvelope.create("knowledge", producer="knowledge", producer_schema="knowledge/v1", generation="g1", stable_handle="knowledge:adr", payload={"repository": "repo-a", "handles": knowledge_result["handles"]})
    operations = ProjectionEnvelope.create("operations", producer="runtime", producer_schema="runtime.receipt/v1", generation="g1", stable_handle="operations:attempt", payload={"repository": "repo-a", "status": "done"})
    operation_index = OperationsProjection("repo-a", "g1")
    operation_index.ingest([OperationReceipt("operations:attempt", "attempt", "done", "g1", 1, "runtime.receipt/v1", {})])
    federation = compile_federation(
        [FederationMember("repo-a", "commit-a", "g1", "projection/v1", "sha256:" + "a" * 64), FederationMember("repo-b", "commit-b", "g1", "projection/v1", "sha256:" + "b" * 64)],
        [FederatedEdge("repo-a:contract", "repo-b:consumer", "depends", 1.0, ("fixture:e1",))],
    )
    context = compile_context([operations, knowledge, code], repository_scope="repo-a")
    diff = diff_generations({"code:symbol": {"name": "Symbol"}}, {"code:symbol": {"name": "Symbol2"}}, source_generation="g1", proposed_generation="g2")
    assert context["projection_count"] == 3
    assert context["instructions"] is False
    assert federation.generation == federation.manifest()["body"]["generation"]
    assert diff.records[0].kind == "update"
    assert all("offset" not in str(item).lower() for item in context["projections"])
    assert context == compile_context([code, knowledge, operations], repository_scope="repo-a")


def test_cross_domain_e2e_rejects_tamper_scope_revocation_and_causal_gap() -> None:
    code = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:symbol",
        tenant_scope="tenant-a",
        payload={"repository": "repo-a", "name": "Symbol"},
    )
    tampered = code.encode().replace(b'"name":"Symbol"', b'"name":"Tampered"')
    with pytest.raises(ProjectionError, match="payload_digest_mismatch"):
        ProjectionEnvelope.decode(tampered)
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([code], repository_scope="repo-a", tenant_scope="tenant-b")

    knowledge = KnowledgeProjection("repo-a", "tenant-a", "g1")
    fact = KnowledgeFact(
        "adr", "mapper", "knowledge:revoked", "v1", ("fixture:adr",),
        "verified", "sha256:revoked", "secret contract", "repo-a", "tenant-a",
    )
    knowledge.apply_delta([fact])
    revoked = KnowledgeFact(
        fact.source_type, fact.producer, fact.stable_handle, fact.version,
        fact.provenance, fact.trust, fact.digest, fact.text, fact.repository,
        fact.scope, state="revoked",
    )
    knowledge.apply_delta([revoked])
    assert knowledge.query("secret contract")["handles"] == []

    operations = OperationsProjection("repo-a", "g1")
    operations.ingest([
        OperationReceipt(
            "attempt:gap", "attempt", "complete", "g1", 2,
            "runtime.receipt/v1", {"causal_parent": "attempt:missing"},
        )
    ])
    assert operations.query(status="complete") == []
