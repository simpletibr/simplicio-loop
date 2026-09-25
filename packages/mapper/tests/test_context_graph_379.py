import pytest
from simplicio_mapper.context_graph_v1 import (
    ContextGraphError, Provenance, build_graph, fact, limited_export, relation,
    tombstone, validate_graph,
)


def prov(kind="measured"):
    return Provenance("src/a.py", 1, 2, "a" * 64, "parser", "1", kind)


def graph(order=False):
    items = [
        fact("repo", "g1", "symbol", "a", {"signature": "a()"}, prov()),
        fact("repo", "g1", "test", "test_a", {"path": "tests/test_a.py"}, prov()),
    ]
    edge = relation("repo", "g1", "VERIFIES", items[1]["fact_id"], items[0]["fact_id"], prov())
    return build_graph(repo_id="repo", generation="g1", config_hash="c",
                       facts=reversed(items) if order else items, relations=[edge])


def test_same_repo_config_is_deterministic_and_every_fact_has_provenance():
    assert graph() == graph(True)
    assert all(item["provenance"]["source_sha256"] for item in graph()["facts"])


def test_ids_do_not_collide_across_repo_or_generation():
    left = fact("a", "g1", "symbol", "x", 1, prov())
    assert left["fact_id"] != fact("b", "g1", "symbol", "x", 1, prov())["fact_id"]
    assert left["fact_id"] != fact("a", "g2", "symbol", "x", 1, prov())["fact_id"]


def test_corrupt_and_stale_fail_with_reason_codes():
    value = graph()
    value["facts"][0]["value"] = "tampered"
    with pytest.raises(ContextGraphError) as corrupt:
        validate_graph(value)
    assert corrupt.value.reason_code == "graph_corrupt"
    with pytest.raises(ContextGraphError) as stale:
        validate_graph(graph(), expected_generation="g2")
    assert stale.value.reason_code == "generation_stale"


def test_inferred_fact_is_never_marked_measured_and_tombstone_preserves_lineage():
    item = fact("repo", "g1", "rule", "r", {}, prov("inferred"), confidence=.6)
    assert item["provenance"]["evidence_kind"] == "inferred"
    deleted = tombstone(item, "g2")
    assert deleted["status"] == "TOMBSTONE" and deleted["supersedes"] == item["fact_id"]


def test_limited_export_respects_budget_and_never_exposes_fast_offsets():
    exported = limited_export(graph(), max_facts=1)
    assert len(exported["facts"]) == 1 and exported["truncated"]
    assert exported["public_offsets"] is None and exported["public_offsets_null_reason"]
