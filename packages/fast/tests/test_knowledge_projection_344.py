from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib

import pytest

from simplicio_fast.knowledge_projection import HANDOFF_SCHEMA, KnowledgeFact, KnowledgeProjection, KnowledgeProjectionError, _digest


def fact(handle: str, text: str, *, state: str = "active") -> KnowledgeFact:
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    return KnowledgeFact("adr", "mapper", handle, "v1", ("mapper:fixture:1",), "verified", digest, text, "repo", "tenant", state=state, applicability=("python",))


def test_knowledge_projection_preserves_provenance_and_separates_explain_dimensions() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    projection.apply_delta([fact("h1", "parser contract and compatibility"), fact("h2", "parser revoked", state="revoked")])
    result = projection.query("parser contract")
    assert result["handles"] == ["h1"]
    assert result["results"][0]["provenance"] == ["mapper:fixture:1"]
    assert result["results"][0]["producer"] == "mapper"
    assert result["results"][0]["repository"] == "repo"
    assert result["results"][0]["scope"] == "tenant"
    assert set(result["results"][0]["explain"]) >= {"relevance", "trust", "freshness", "applicability"}
    assert result["results"][0]["explain"]["ranking"] == "lexical-fallback"


def test_knowledge_projection_delta_temporal_scope_and_caps_fail_closed() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    projection.apply_delta([fact("h", "contract",)], tombstones=())
    with pytest.raises(KnowledgeProjectionError, match="fact_scope_mismatch"):
        projection.apply_delta([KnowledgeFact("adr", "mapper", "x", "v1", ("p",), "verified", "sha256:x", "contract", "other", "tenant")])
    assert projection.query("contract", max_bytes=1)["truncated"] is True
    assert projection.query("contract", as_of=100)["handles"] == ["h"]


def test_knowledge_projection_preserves_conflict_and_tombstone_lineage() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    original = fact("same", "contract v1")
    conflicting = KnowledgeFact(
        "adr", "mapper", "same", "v2", ("mapper:fixture:2",), "verified",
        "sha256:" + "f" * 64, "contract v2", "repo", "tenant",
    )
    delta = projection.apply_delta([original, conflicting])
    assert delta["conflicts"] == ["same"]
    assert projection.query("contract")["handles"] == []
    assert projection.snapshot()["conflicts"] == ["same"]
    removed = projection.apply_delta(tombstones=["same"])
    assert removed["tombstones"] == ["same"]
    assert projection.snapshot()["tombstones"] == ["same"]


def test_knowledge_projection_applies_same_version_revocation() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    active = fact("revocable", "parser contract")
    projection.apply_delta([active])
    revoked = KnowledgeFact(
        active.source_type,
        active.producer,
        active.stable_handle,
        active.version,
        active.provenance,
        active.trust,
        active.digest,
        active.text,
        active.repository,
        active.scope,
        state="revoked",
        applicability=active.applicability,
    )
    delta = projection.apply_delta([revoked])
    assert delta["changed_handles"] == ["revocable"]
    assert delta["conflicts"] == []
    assert projection.query("parser contract")["handles"] == []


def test_knowledge_fact_and_projection_contracts_fail_closed() -> None:
    base = {
        "source_type": "adr",
        "producer": "mapper",
        "stable_handle": "h",
        "version": "v1",
        "provenance": ("p",),
        "trust": "verified",
        "digest": "sha256:x",
        "text": "contract",
        "repository": "repo",
        "scope": "tenant",
    }
    with pytest.raises(KnowledgeProjectionError, match="fact_identity_invalid"):
        KnowledgeFact(**{**base, "repository": ""})
    with pytest.raises(KnowledgeProjectionError, match="fact_provenance_invalid"):
        KnowledgeFact(**{**base, "provenance": ("",)})
    with pytest.raises(KnowledgeProjectionError, match="fact_text_invalid"):
        KnowledgeFact(**{**base, "text": 1})
    with pytest.raises(KnowledgeProjectionError, match="fact_state_invalid"):
        KnowledgeFact(**{**base, "state": "unknown"})
    with pytest.raises(KnowledgeProjectionError, match="fact_temporal_bounds_invalid"):
        KnowledgeFact(**{**base, "valid_from": 2, "valid_until": 1})
    assert KnowledgeFact(**base).to_dict()["schema"] == "simplicio.fast.knowledge-fact/v1"
    assert _digest({"fact": "stable"}).startswith("sha256:")
    with pytest.raises(KnowledgeProjectionError, match="projection_scope_invalid"):
        KnowledgeProjection("", "tenant", "g1")


def test_knowledge_fact_normalizes_mutable_provenance_sequences() -> None:
    item = fact("normalized", "contract",)
    normalized = KnowledgeFact(
        item.source_type,
        item.producer,
        item.stable_handle,
        item.version,
        ["mapper:fixture:1"],
        item.trust,
        item.digest,
        item.text,
        item.repository,
        item.scope,
        applicability=["python"],
    )
    assert normalized.provenance == ("mapper:fixture:1",)
    assert normalized.applicability == ("python",)


def test_knowledge_projection_idempotence_and_query_boundaries() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    bounded = fact("bounded", "contract parser",)
    projection.apply_delta([bounded])
    unchanged = projection.apply_delta([bounded])
    assert unchanged["changed_handles"] == []
    for kwargs in ({"max_results": 0}, {"max_bytes": 0}, {"max_tokens": 0}):
        with pytest.raises(KnowledgeProjectionError, match="query_budget_invalid"):
            projection.query("contract", **kwargs)
    assert projection.query("unmatched")["handles"] == []
    assert projection.query("contract", source_types=("other",))["handles"] == []
    temporal = KnowledgeFact(
        bounded.source_type,
        bounded.producer,
        "temporal",
        bounded.version,
        bounded.provenance,
        bounded.trust,
        bounded.digest,
        "contract",
        bounded.repository,
        bounded.scope,
        valid_from=10,
        valid_until=20,
    )
    projection.apply_delta([temporal])
    assert "temporal" not in projection.query("contract", as_of=5)["handles"]
    assert "temporal" not in projection.query("contract", as_of=25)["handles"]
    assert projection.query("contract", max_tokens=1)["truncation_reasons"] == ["token_budget"]


def test_knowledge_projection_rejects_boolean_budgets_and_enforces_fact_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    monkeypatch.setattr("simplicio_fast.knowledge_projection.MAX_FACTS", 1)
    projection.apply_delta([fact("one", "contract")])
    with pytest.raises(KnowledgeProjectionError, match="fact_count_limit"):
        projection.apply_delta([fact("two", "contract")])
    for kwargs in ({"max_results": True}, {"max_bytes": True}, {"max_tokens": True}, {"as_of": True}):
        with pytest.raises(KnowledgeProjectionError, match="query_budget_invalid"):
            projection.query("contract", **kwargs)


def test_knowledge_projection_applies_trust_floor_before_ranking() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    derived = KnowledgeFact(
        "adr", "mapper", "derived", "v1", ("mapper:derived",),
        "derived_fact", "sha256:" + "d" * 64, "parser contract", "repo", "tenant",
    )
    verified = fact("verified", "parser contract")
    projection.apply_delta([derived, verified])

    result = projection.query("parser contract", trust_floor="verified")
    assert result["trust_floor"] == "verified"
    assert result["handles"] == ["verified"]
    with pytest.raises(KnowledgeProjectionError, match="query_trust_invalid"):
        projection.query("parser contract", trust_floor="unknown")


def test_knowledge_projection_rejects_untyped_delta_and_query_inputs() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    with pytest.raises(KnowledgeProjectionError, match="fact_type_invalid"):
        projection.apply_delta([object()])
    with pytest.raises(KnowledgeProjectionError, match="tombstone_invalid"):
        projection.apply_delta(tombstones=["", "h"])
    with pytest.raises(KnowledgeProjectionError, match="query_task_invalid"):
        projection.query(1)
    with pytest.raises(KnowledgeProjectionError, match="query_source_types_invalid"):
        projection.query("contract", source_types="adr")
    with pytest.raises(KnowledgeProjectionError, match="fact_temporal_bounds_invalid"):
        replace(fact("time", "contract"), valid_from=True)


def test_knowledge_projection_serializes_twenty_readers() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    projection.apply_delta([fact("shared", "parser contract")])

    def read(_: int) -> tuple[list[str], list[str], str]:
        result = projection.query("parser contract")
        snapshot = projection.snapshot()
        return result["handles"], snapshot["handles"], snapshot["schema"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(read, range(20)))
    assert results == [(["shared"], ["shared"], "simplicio.fast.knowledge-projection/v1")] * 20


def test_knowledge_projection_applies_authorized_mapper_handoff() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    item = fact("handoff", "mapper contract")
    handoff = {
        "schema": HANDOFF_SCHEMA,
        "producer": "mapper",
        "producer_schema": "mapper.knowledge/v1",
        "repository": "repo",
        "scope": "tenant",
        "generation": "g1",
        "facts": [item.to_dict()],
        "tombstones": [],
    }
    delta = projection.apply_handoff(handoff)
    assert delta["producer"] == "mapper"
    assert projection.query("mapper contract")["handles"] == ["handoff"]


def test_knowledge_projection_handoff_rejects_untrusted_or_mismatched_inputs() -> None:
    projection = KnowledgeProjection("repo", "tenant", "g1")
    base = {
        "schema": HANDOFF_SCHEMA,
        "producer": "mapper",
        "producer_schema": "mapper.knowledge/v1",
        "repository": "repo",
        "scope": "tenant",
        "generation": "g1",
        "facts": [],
        "tombstones": [],
    }
    with pytest.raises(KnowledgeProjectionError, match="handoff_producer_untrusted"):
        projection.apply_handoff({**base, "producer": "arbitrary"})
    with pytest.raises(KnowledgeProjectionError, match="handoff_scope_mismatch"):
        projection.apply_handoff({**base, "generation": "g2"})
    with pytest.raises(KnowledgeProjectionError, match="handoff_producer_mismatch"):
        projection.apply_handoff({**base, "facts": [{**fact("wrong", "contract").to_dict(), "producer": "runtime"}]})
