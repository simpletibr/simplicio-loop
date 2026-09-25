import pytest

from simplicio_fast.projection import ProjectionEnvelope
from simplicio_fast.universal_context import UniversalContextError, compile_context


def projection(kind: str, handle: str) -> ProjectionEnvelope:
    return ProjectionEnvelope.create(
        kind,
        producer="producer",
        producer_schema="producer/v1",
        generation="g1",
        stable_handle=handle,
        payload={"repository": "repo", "value": handle},
    )


def test_universal_context_is_deterministic_and_marks_facts_not_instructions() -> None:
    result = compile_context([projection("operations", "o"), projection("code", "c"), projection("knowledge", "k")], repository_scope="repo")
    assert [item["projection_type"] for item in result["projections"]] == ["code", "knowledge", "operations"]
    assert result["authority"] == "facts_only"
    assert result["instructions"] is False
    assert result["truncated"] is False


def test_universal_context_budget_and_scope_fail_closed() -> None:
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([projection("code", "c")], repository_scope="other")
    result = compile_context([projection("code", "c"), projection("knowledge", "k")], max_items=1)
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["item_budget"]
    with pytest.raises(UniversalContextError, match="context_budget_invalid"):
        compile_context([], max_tokens=0)


def test_universal_context_exposes_boundaries_and_wrapper_accounting() -> None:
    untrusted = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g2",
        stable_handle="k",
        domain_scope="knowledge",
        payload={
            "repository": "repo",
            "value": "retrieved text",
            "trust": "untrusted",
            "content_class": "untrusted_text",
            "freshness": "stale",
        },
    )
    result = compile_context(
        [untrusted, projection("operations", "o")],
        repository_scope="repo",
        domain_caps={"knowledge": 1},
        wrapper_bytes=7,
        wrapper_tokens=3,
    )
    item = next(item for item in result["projections"] if item["projection_type"] == "knowledge")
    assert item["digest"].startswith("sha256:")
    assert item["trust"] == "untrusted"
    assert item["freshness"] == "stale"
    assert item["trusted_for_instruction"] is False
    assert result["wrapper_bytes"] == 7
    assert result["wrapper_tokens"] == 3
    assert result["source_generations"] == ["g1", "g2"]
    assert item["source_generation"] == "g2"
    assert item["projection_generation"] == "g2"


def test_universal_context_receipt_pins_source_and_projection_generations() -> None:
    item = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="projection-g2",
        source_generation="source-g1",
        projection_generation="projection-g2",
        stable_handle="versioned",
        payload={"repository": "repo", "value": "versioned"},
    )
    result = compile_context([item], repository_scope="repo")
    assert result["source_generations"] == ["source-g1"]
    assert result["projection_generations"] == ["projection-g2"]


def test_universal_context_rejects_conflicting_duplicate_and_impossible_wrapper() -> None:
    first = projection("knowledge", "same")
    second = ProjectionEnvelope.create(
        "knowledge",
        producer="producer",
        producer_schema="producer/v1",
        generation="g1",
        stable_handle="same",
        payload={"repository": "repo", "value": "different"},
    )
    with pytest.raises(UniversalContextError, match="context_conflict"):
        compile_context([first, second])
    with pytest.raises(UniversalContextError, match="context_budget_invalid"):
        compile_context([], max_bytes=3, wrapper_bytes=4)


def test_universal_context_rejects_tenant_scope_mismatch() -> None:
    item = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="tenant-fact",
        tenant_scope="tenant-a",
        payload={"repository": "repo", "value": "scoped"},
    )
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([item], repository_scope="repo", tenant_scope="tenant-b")


def test_universal_context_rejects_foreign_or_unbound_tenant_payload() -> None:
    foreign = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="foreign-tenant",
        payload={"repository": "repo", "tenant": "tenant-b", "value": "foreign"},
    )
    unbound = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="unbound-tenant",
        payload={"repository": "repo", "value": "unbound"},
    )
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([foreign], repository_scope="repo", tenant_scope="tenant-a")
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([unbound], repository_scope="repo", tenant_scope="tenant-a")


def test_universal_context_rejects_unbound_or_foreign_repository_metadata() -> None:
    foreign = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="foreign",
        repository_scope="other",
        payload={"repository": "repo", "value": "foreign"},
    )
    unbound = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="unbound",
        payload={"value": "unbound"},
    )
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([foreign], repository_scope="repo")
    with pytest.raises(UniversalContextError, match="context_scope_mismatch"):
        compile_context([unbound], repository_scope="repo")


def test_universal_context_rejects_boolean_budget_values() -> None:
    with pytest.raises(UniversalContextError, match="context_budget_invalid"):
        compile_context([], max_tokens=True)
    with pytest.raises(UniversalContextError, match="context_budget_invalid"):
        compile_context([], wrapper_bytes=False)


def test_universal_context_rejects_untyped_projection_and_scope_inputs() -> None:
    with pytest.raises(UniversalContextError, match="context_projections_invalid"):
        compile_context([object()])
    with pytest.raises(UniversalContextError, match="context_scope_invalid"):
        compile_context([], repository_scope=1)
    with pytest.raises(UniversalContextError, match="context_domain_budget_invalid"):
        compile_context([], domain_caps=[("knowledge", 1)])


def test_universal_context_rejects_invalid_domain_caps_and_records_duplicate() -> None:
    for caps in ({"": 1}, {"knowledge": True}, {"knowledge": -1}, {1: 1}):
        with pytest.raises(UniversalContextError, match="context_domain_budget_invalid"):
            compile_context([], domain_caps=caps)
    duplicate = projection("knowledge", "same")
    result = compile_context([duplicate, duplicate])
    assert result["selection"]["rejected"] == [{"stable_handle": "same", "reason": "duplicate"}]
    assert result["truncated"] is False


def test_universal_context_reports_domain_byte_and_token_truncation() -> None:
    item = projection("knowledge", "bounded")
    domain_limited = compile_context([item], domain_caps={"knowledge": 0})
    assert domain_limited["truncation_reasons"] == ["domain_budget"]
    byte_limited = compile_context([item], max_bytes=1)
    assert byte_limited["truncation_reasons"] == ["byte_budget"]
    token_limited = compile_context([item], max_tokens=1)
    assert token_limited["truncation_reasons"] == ["token_budget"]


def test_universal_context_applies_trust_floor_without_promoting_instructions() -> None:
    untrusted = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="untrusted",
        payload={"repository": "repo", "trust": "untrusted", "value": "text"},
    )
    verified = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="verified",
        payload={"repository": "repo", "trust": "verified", "value": "fact"},
    )
    result = compile_context([untrusted, verified], repository_scope="repo", trust_floor="verified")
    assert [item["stable_handle"] for item in result["projections"]] == ["verified"]
    assert result["selection"]["rejected"] == [{"stable_handle": "untrusted", "reason": "trust_floor"}]
    assert result["projections"][0]["trusted_for_instruction"] is False
    assert result["trust_floor"] == "verified"
    with pytest.raises(UniversalContextError, match="context_trust_invalid"):
        compile_context([], trust_floor="unknown")


def test_universal_context_uses_exact_tokenizer_and_labels_fallback() -> None:
    exact = compile_context(
        [projection("knowledge", "exact")],
        tokenizer_id="test-exact-v1",
        tokenizer=lambda text: len(text.encode("utf-8")),
    )
    assert exact["tokenizer"] == {
        "mode": "exact",
        "id": "test-exact-v1",
        "reason": None,
    }
    assert exact["tokens"] is not None
    unavailable = compile_context(
        [projection("knowledge", "fallback")],
        tokenizer_id="tiktoken:missing-for-test",
    )
    assert unavailable["tokenizer"] == {
        "mode": "estimated",
        "id": "tiktoken:missing-for-test",
        "reason": "provider_tokenizer_unavailable",
    }
    assert unavailable["tokens"] is None


def test_universal_context_rejects_invalid_tokenizer_contract() -> None:
    with pytest.raises(UniversalContextError, match="context_tokenizer_invalid"):
        compile_context([], tokenizer=lambda text: 1)
    with pytest.raises(UniversalContextError, match="context_tokenizer_invalid"):
        compile_context([], tokenizer_id=True)
    with pytest.raises(UniversalContextError, match="context_tokenizer_invalid"):
        compile_context(
            [projection("knowledge", "invalid-tokenizer")],
            tokenizer_id="test",
            tokenizer=lambda text: True,
        )
