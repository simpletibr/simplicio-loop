from concurrent.futures import ThreadPoolExecutor
import hashlib
import math

import pytest

from simplicio_fast.federation import (
    FederatedEdge,
    Federation,
    FederationError,
    FederationMember,
    _canonical,
    compile_federation,
)


def member(repo: str, generation: str = "g1") -> FederationMember:
    digest = hashlib.sha256(repo.encode("utf-8")).hexdigest()
    return FederationMember(repo, "commit-" + repo, generation, "projection/v1", "sha256:" + digest)


def test_federation_is_pinned_deterministic_and_bounded() -> None:
    edge = FederatedEdge("repo-a:schema/x", "repo-b:consumer/y", "depends", 1.0, ("fixture:1",))
    first = compile_federation([member("repo-b"), member("repo-a")], [edge])
    second = compile_federation([member("repo-a"), member("repo-b")], [edge])
    assert first.encode() == second.encode()
    assert first.manifest()["body"]["generation"] == first.generation
    assert first.consumers("repo-b:consumer/y")[0]["source_handle"] == "repo-a:schema/x"
    assert first.dependencies("repo-a:schema/x")[0]["target_handle"] == "repo-b:consumer/y"


def test_federation_traversal_preserves_provenance_paths() -> None:
    edges = [
        FederatedEdge("a:schema", "b:schema", "depends", 0.9, ("a.json:1",)),
        FederatedEdge("b:schema", "c:schema", "depends", 0.8, ("b.json:2",), derived=True),
    ]
    result = compile_federation([member("a"), member("b"), member("c")], edges).traverse("a:schema")
    assert result["nodes"] == ["a:schema", "b:schema", "c:schema"]
    assert result["paths"]["c:schema"] == ["a:schema", "b:schema", "c:schema"]
    assert result["complete"] is True


def test_federation_rejects_duplicate_scope_tombstone_and_unproven_edge() -> None:
    with pytest.raises(FederationError, match="duplicate_member_repository"):
        compile_federation([member("Repo"), member("repo")])
    with pytest.raises(FederationError, match="member_tombstone_present"):
        compile_federation([FederationMember("repo", "c", "g", "s", "sha256:" + "a" * 64, tombstone=True)])
    with pytest.raises(FederationError, match="derived_edge_evidence_missing"):
        FederatedEdge("a:x", "b:y", "depends", 1.0, derived=True)
    with pytest.raises(FederationError, match="edge_confidence_invalid"):
        FederatedEdge("a:x", "b:y", "depends", True)
    with pytest.raises(FederationError, match="edge_confidence_invalid"):
        FederatedEdge("a:x", "b:y", "depends", math.nan)
    with pytest.raises(FederationError, match="edge_evidence_invalid"):
        FederatedEdge("a:x", "b:y", "depends", 1.0, ("",))
    with pytest.raises(FederationError, match="member_digest_invalid"):
        FederationMember("repo", "commit", "generation", "schema", "digest")
    with pytest.raises(FederationError, match="member_digest_invalid"):
        FederationMember("repo", "commit", "generation", "schema", "sha256:" + "g" * 64)


def test_federation_rejects_invalid_canonical_values_and_member_limits() -> None:
    body = compile_federation([member("repo")]).manifest()["body"]
    body["invalid"] = object()
    with pytest.raises(FederationError, match="federation_not_json"):
        _canonical(body)
    with pytest.raises(FederationError, match="member_count_limit"):
        compile_federation([member(f"repo-{index}") for index in range(257)])


def test_federation_rejects_unbounded_traversal() -> None:
    with pytest.raises(FederationError, match="traversal_budget_invalid"):
        compile_federation([member("repo")]).traverse("repo:root", max_nodes=0)


def test_federation_reports_truncated_depth_and_node_closure() -> None:
    edges = [
        FederatedEdge("a:schema", "b:schema", "depends", 1.0),
        FederatedEdge("b:schema", "c:schema", "depends", 1.0),
    ]
    federation = compile_federation([member("a"), member("b"), member("c")], edges)
    depth_limited = federation.traverse("a:schema", max_depth=0)
    assert depth_limited["complete"] is False
    assert depth_limited["truncation_reasons"] == ["max_depth"]
    node_limited = federation.traverse("a:schema", max_nodes=1)
    assert node_limited["complete"] is False
    assert node_limited["truncation_reasons"] == ["max_nodes"]


def test_federation_rejects_edges_outside_pinned_members_and_duplicates() -> None:
    with pytest.raises(FederationError, match="edge_member_missing"):
        compile_federation(
            [member("repo-a")],
            [FederatedEdge("repo-a:schema", "repo-b:consumer", "depends", 1.0)],
        )
    edge = FederatedEdge("repo-a:schema", "repo-a:consumer", "depends", 1.0)
    with pytest.raises(FederationError, match="duplicate_edge"):
        compile_federation([member("repo-a")], [edge, edge])


def test_federation_delta_reuses_members_and_removes_tombstoned_edges() -> None:
    original = compile_federation(
        [member("repo-a"), member("repo-b")],
        [FederatedEdge("repo-a:x", "repo-b:y", "depends", 1.0, ("fixture:1",))],
    )
    replacement = FederationMember("repo-b", "commit-b2", "g2", "projection/v1", "sha256:" + "b" * 64)
    updated, receipt = original.apply_delta([replacement], added_edges=())
    assert updated.members[1].commit == "commit-b2"
    assert receipt["changed_repositories"] == ["repo-b"]
    assert receipt["reused_members"] == 1
    assert updated.edges == original.edges
    removed, removed_receipt = original.apply_delta(removed_repositories=("repo-b",))
    assert removed.edges == ()
    assert removed_receipt["tombstones"] == ["repo-b"]


def test_federation_delta_rejects_split_brain_member_updates() -> None:
    original = compile_federation([member("repo-a"), member("repo-b")])
    with pytest.raises(FederationError, match="delta_split_brain"):
        original.apply_delta([member("repo-b"), member("Repo-b", "g2")])
    with pytest.raises(FederationError, match="delta_split_brain"):
        original.apply_delta([member("repo-b")], removed_repositories=("repo-b",))


def test_federation_queries_reject_invalid_or_oversized_budgets() -> None:
    edge = FederatedEdge("repo-a:x", "repo-b:y", "depends", 1.0, ("fixture:1",))
    federation = compile_federation([member("repo-a"), member("repo-b")], [edge])
    with pytest.raises(FederationError, match="edge_budget_invalid"):
        federation.consumers("repo-b:y", max_edges=True)
    with pytest.raises(FederationError, match="byte_budget_invalid"):
        federation.dependencies("repo-a:x", max_bytes=True)
    with pytest.raises(FederationError, match="result_size_limit"):
        federation.consumers("repo-b:y", max_bytes=1)
    with pytest.raises(FederationError, match="edge_budget_exceeded"):
        federation.traverse("repo-a:x", max_edges=0)
    with pytest.raises(FederationError, match="result_size_limit"):
        federation.traverse("repo-a:x", max_bytes=1)


def test_federation_supports_twenty_concurrent_readers() -> None:
    edge = FederatedEdge("repo-a:schema/x", "repo-b:consumer/y", "depends", 1.0, ("fixture:1",))
    federation = compile_federation([member("repo-a"), member("repo-b")], [edge])
    expected_generation = federation.generation

    def read(_: int) -> tuple[str, int, int, str]:
        return (
            federation.generation,
            len(federation.consumers("repo-b:consumer/y")),
            len(federation.traverse("repo-a:schema/x")["nodes"]),
            federation.manifest()["schema"],
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(read, range(20)))
    assert results == [(expected_generation, 1, 2, "simplicio.fast.federated-generation/v1")] * 20


def test_federation_boundaries_fail_closed_for_handles_and_delta_types() -> None:
    with pytest.raises(FederationError, match="edge_handle_invalid"):
        FederatedEdge("repo", "repo:target", "depends", 1.0)
    with pytest.raises(FederationError, match="edge_handle_invalid"):
        FederatedEdge("repo:source", "target", "depends", 1.0)
    with pytest.raises(FederationError, match="edge_handle_invalid"):
        FederatedEdge("repo:", "repo:target", "depends", 1.0)
    with pytest.raises(FederationError, match="edge_evidence_invalid"):
        FederatedEdge("repo:source", "repo:target", "depends", 1.0, evidence="bad")
    edge = FederatedEdge("repo:source", "repo:target", "depends", 1.0, evidence=["fixture:1"])
    assert edge.evidence == ("fixture:1",)
    with pytest.raises(FederationError, match="edge_derived_invalid"):
        FederatedEdge("repo:source", "repo:target", "depends", 1.0, derived=1)
    with pytest.raises(FederationError, match="member_tombstone_invalid"):
        FederationMember("repo", "commit", "g", "schema", "sha256:" + "a" * 64, tombstone=1)
    federation = compile_federation([member("repo")])
    with pytest.raises(FederationError, match="delta_member_type_invalid"):
        federation.apply_delta([object()])
    with pytest.raises(FederationError, match="delta_edge_type_invalid"):
        federation.apply_delta(added_edges=[object()])
    with pytest.raises(FederationError, match="delta_repository_invalid"):
        federation.apply_delta(removed_repositories=[""])


def test_federation_constructor_rejects_non_sequence_inputs() -> None:
    with pytest.raises(FederationError, match="member_type_invalid"):
        Federation(object())  # type: ignore[arg-type]
    with pytest.raises(FederationError, match="edge_type_invalid"):
        Federation([member("repo")], object())  # type: ignore[arg-type]
