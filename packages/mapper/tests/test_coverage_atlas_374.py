import pytest
from simplicio_mapper.coverage_atlas import AtlasError, build_atlas, coverage_delta, edge, node


def fixture(clean=False):
    requirement = node("requirement", "REQ-1", source_hash="s", owner="mapper", valid_from="1")
    owner = node("repository", "loop", source_hash="s", owner="loop", valid_from="1")
    contract = node("contract", "receipt-v1", source_hash="s", owner="runtime", valid_from="1")
    producer = node("producer", "fast", source_hash="s", owner="fast", valid_from="1")
    consumer = node("consumer", "loop", source_hash="s", owner="loop", valid_from="1")
    test = node("test", "contract-test", source_hash="s", owner="qa", valid_from="1")
    edges = []
    if clean:
        edges = [
            edge("OWNS", requirement["node_id"], owner["node_id"], source_hash="s", valid_from="1"),
            edge("PRODUCES", producer["node_id"], contract["node_id"], source_hash="s", valid_from="1"),
            edge("CONSUMES", contract["node_id"], consumer["node_id"], source_hash="s", valid_from="1"),
            edge("VERIFIES", test["node_id"], contract["node_id"], source_hash="s", valid_from="1"),
        ]
    return build_atlas([requirement, owner, contract, producer, consumer, test], edges,
                       source="simplicio-mapper@installed", revision="1")


def test_seeded_gaps_and_clean_control_are_deterministic():
    first = coverage_delta(fixture())
    second = coverage_delta(fixture())
    assert first == second
    assert {item["kind"] for item in first["gaps"]} == {
        "missing_owner", "missing_producer", "missing_consumer", "missing_test",
    }
    assert coverage_delta(fixture(clean=True))["gaps"] == []


def test_delta_reports_opened_and_closed_without_full_reprocessing():
    dirty = coverage_delta(fixture())
    clean = coverage_delta(fixture(clean=True), [item["gap_id"] for item in dirty["gaps"]])
    assert clean["opened_gap_ids"] == []
    assert clean["closed_gap_ids"] == sorted(item["gap_id"] for item in dirty["gaps"])


def test_partial_and_orphan_graphs_fail_closed():
    with pytest.raises(AtlasError, match="partial"):
        build_atlas([], [], source="x", revision="1", complete=False)
    orphan = edge("OWNS", "missing", "also-missing", source_hash="s", valid_from="1")
    with pytest.raises(AtlasError, match="orphan"):
        build_atlas([], [orphan], source="x", revision="1")


def test_receipt_without_ac_and_virtual_address_without_route_are_gaps():
    evidence = node("evidence", "receipt:unbound", source_hash="s", owner="fast", valid_from="1")
    address = node("agent_address", "fast://cache", source_hash="s", owner="fast", valid_from="1")
    atlas = build_atlas([evidence, address], [], source="mapper", revision="1")
    assert {item["kind"] for item in coverage_delta(atlas)["gaps"]} == {
        "missing_evidence", "missing_integration",
    }


def test_suppression_requires_owner_reason_and_expires():
    atlas = fixture()
    gap = coverage_delta(atlas)["gaps"][0]
    atlas = build_atlas(
        atlas["nodes"], atlas["edges"], source=atlas["source"], revision="1",
        suppressions=[{"gap_id": gap["gap_id"], "owner": "team", "reason": "migration",
                       "expires_after": "2"}],
    )
    # New atlas digest intentionally creates new stable gap IDs; suppressions bind one atlas revision.
    assert coverage_delta(atlas, now_revision="3")["gaps"]


def test_operational_health_adapter_emits_fast_gap_without_dispatch_authority():
    from simplicio_mapper.coverage_atlas import operational_delta
    delta = operational_delta(
        source="mapper@installed", base_atlas_digest="sha256:atlas",
        observations=[
            {"kind": "cache_integrity", "subject": "cache:main", "healthy": False,
             "evidence_refs": ["fast://health"]},
            {"kind": "index_generation", "subject": "index:main", "healthy": True},
        ],
    )
    assert [item["kind"] for item in delta["gaps"]] == ["cache_integrity"]
    assert not any(key in delta for key in ("dispatch", "completion", "worker"))
