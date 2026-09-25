from concurrent.futures import ThreadPoolExecutor

import pytest

from simplicio_fast.operations_projection import OperationReceipt, OperationsProjection, OperationsProjectionError


def receipt(handle: str, sequence: int, status: str = "running") -> OperationReceipt:
    return OperationReceipt(handle, "attempt", status, "g1", sequence, "runtime.receipt/v1", {"slot": handle})


def test_operations_projection_is_read_only_bounded_and_incremental() -> None:
    projection = OperationsProjection("repo", "g1")
    delta = projection.ingest([receipt("a", 1), receipt("b", 2, "done")])
    assert delta["changed_handles"] == ["a", "b"]
    assert projection.query(status="done")[0]["handle"] == "b"
    assert projection.snapshot()["schema"] == "simplicio.fast.operations-projection/v1"


def test_operations_projection_rejects_stale_receipts_and_unbounded_queries() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([receipt("a", 2)])
    with pytest.raises(OperationsProjectionError, match="receipt_sequence_regression"):
        projection.ingest([receipt("a", 1)])
    with pytest.raises(OperationsProjectionError, match="receipt_generation_mismatch"):
        projection.ingest([OperationReceipt("b", "attempt", "queued", "g2", 1, "x/v1", {})])
    with pytest.raises(OperationsProjectionError, match="query_budget_invalid"):
        projection.query(max_results=0)


def test_operations_projection_reports_slots_leases_and_read_only_stats() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([
        OperationReceipt("slot:1", "slot", "active", "g1", 1, "loop/v1", {}),
        OperationReceipt("lease:1", "lease", "held", "g1", 2, "loop/v1", {"owner": "worker-a", "fence": "f1", "expires_at": 100}),
    ])
    assert projection.query_slots()[0]["handle"] == "lease:1"
    lease = projection.query_leases(50)[0]["lease"]
    assert lease["active"] is True
    assert lease["authority"] == "producer"
    assert projection.stats()["authority"] == "derived_read_only"
    assert projection.query_leases(100)[0]["lease"]["active"] is False


def test_operations_projection_blocks_complete_status_on_causal_gap() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([
        OperationReceipt(
            "attempt:child",
            "attempt",
            "complete",
            "g1",
            2,
            "loop/v1",
            {"causal_parent": "attempt:missing"},
        )
    ])
    assert projection.query(status="complete") == []
    assert projection.query()[0]["consistency"] == "causal_gap"
    assert projection.snapshot()["consistency"] == {
        "causal_gaps": ["attempt:child"],
        "forks": [],
    }


def test_operations_projection_rejects_same_sequence_fork_but_allows_duplicate() -> None:
    projection = OperationsProjection("repo", "g1")
    item = receipt("a", 1)
    projection.ingest([item, item])
    with pytest.raises(OperationsProjectionError, match="receipt_fork_detected"):
        projection.ingest([OperationReceipt("a", "attempt", "failed", "g1", 1, "loop/v1", {})])
    assert projection.query()[0]["consistency"] == "fork"


def test_operations_projection_supports_twenty_concurrent_readers() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([receipt(f"attempt:{index}", index) for index in range(1, 21)])

    def read(index: int) -> tuple[int, int, int, str]:
        return (
            len(projection.query(max_results=1000)),
            len(projection.query_slots(max_results=1000)),
            projection.stats()["receipts"],
            projection.snapshot()["schema"],
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(read, range(20)))
    assert results == [(20, 20, 20, "simplicio.fast.operations-projection/v1")] * 20


def test_operations_projection_receipt_and_scope_contracts_fail_closed() -> None:
    base = {
        "handle": "h",
        "kind": "attempt",
        "status": "running",
        "generation": "g1",
        "sequence": 1,
        "source_schema": "runtime/v1",
        "payload": {},
    }
    for field, value, reason in (
        ("handle", "", "receipt_identity_invalid"),
        ("sequence", True, "receipt_sequence_invalid"),
        ("payload", [], "receipt_payload_invalid"),
    ):
        with pytest.raises(OperationsProjectionError, match=reason):
            OperationReceipt(**{**base, field: value})
    with pytest.raises(OperationsProjectionError, match="projection_scope_invalid"):
        OperationsProjection("", "g1")


def test_operation_receipt_detaches_nested_payload() -> None:
    payload = {"lease": {"owner": "worker-a"}}
    item = OperationReceipt("attempt", "attempt", "running", "g1", 1, "runtime/v1", payload)
    payload["lease"]["owner"] = "mutated"
    assert item.payload["lease"]["owner"] == "worker-a"


def test_operations_projection_rejects_untyped_ingest_filters_and_lease_limits() -> None:
    projection = OperationsProjection("repo", "g1")
    with pytest.raises(OperationsProjectionError, match="receipt_type_invalid"):
        projection.ingest([object()])
    with pytest.raises(OperationsProjectionError, match="query_filter_invalid"):
        projection.query(status=1)
    with pytest.raises(OperationsProjectionError, match="lease_query_invalid"):
        projection.query_leases(0, max_results=True)
    with pytest.raises(OperationsProjectionError, match="lease_query_invalid"):
        projection.query_leases(0, max_results=1.5)
    for status in (1, True, ""):
        with pytest.raises(OperationsProjectionError, match="query_filter_invalid"):
            projection.query_slots(status=status)


def test_operations_projection_causal_and_lease_boundaries() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([
        OperationReceipt("bad-parent", "attempt", "running", "g1", 1, "runtime/v1", {"causal_parent": " "}),
        OperationReceipt("external", "other", "done", "g1", 2, "runtime/v1", {}),
        OperationReceipt("embedded-lease", "attempt", "held", "g1", 3, "runtime/v1", {"lease": {"owner": "w", "fence": "f", "expires_at": 4}}),
    ])
    assert projection.query(status="done", kind="other")[0]["handle"] == "external"
    assert projection.query_slots()[0]["handle"] == "embedded-lease"
    assert projection.query_slots(status="missing") == []
    assert projection.query(max_results=1)[0]["handle"] == "embedded-lease"
    assert projection.query_leases(3)[0]["lease"]["active"] is True
    assert projection.query_leases(4)[0]["lease"]["active"] is False
    assert len(projection.query_leases(3, max_results=1)) == 1
    for observed_at, max_results in ((True, 1), (-1, 1), (0, 0)):
        with pytest.raises(OperationsProjectionError, match="lease_query_invalid"):
            projection.query_leases(observed_at, max_results=max_results)
    invalid_expiry = OperationsProjection("repo", "g1")
    invalid_expiry.ingest([OperationReceipt("lease", "lease", "held", "g1", 1, "runtime/v1", {"expires_at": True})])
    with pytest.raises(OperationsProjectionError, match="lease_expiry_invalid"):
        invalid_expiry.query_leases(0)
    negative_expiry = OperationsProjection("repo", "g1")
    negative_expiry.ingest([OperationReceipt("lease", "lease", "held", "g1", 1, "runtime/v1", {"expires_at": -1})])
    with pytest.raises(OperationsProjectionError, match="lease_expiry_invalid"):
        negative_expiry.query_leases(0)
    with pytest.raises(OperationsProjectionError, match="query_budget_invalid"):
        projection.query_slots(max_results=0)
    ordered = OperationsProjection("repo", "g1")
    ordered.ingest([
        OperationReceipt("parent", "attempt", "running", "g1", 2, "runtime/v1", {}),
        OperationReceipt("child", "attempt", "running", "g1", 1, "runtime/v1", {"causal_parent": "parent"}),
    ])
    by_handle = {item["handle"]: item for item in ordered.query()}
    assert by_handle["child"]["consistency"] == "causal_gap"
    ordered_ok = OperationsProjection("repo", "g1")
    ordered_ok.ingest([
        OperationReceipt("parent", "attempt", "running", "g1", 1, "runtime/v1", {}),
        OperationReceipt("child", "attempt", "running", "g1", 2, "runtime/v1", {"causal_parent": "parent"}),
    ])
    assert ordered_ok.query()[0]["consistency"] == "consistent"


def test_operations_projection_preserves_tombstone_lineage_and_allows_correction() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([OperationReceipt("attempt", "attempt", "running", "g1", 1, "loop/v1", {"producer": "loop"})])
    delta = projection.ingest([OperationReceipt("attempt", "attempt", "deleted", "g1", 2, "loop/v1", {"producer": "loop", "tombstone": True})])
    assert delta["tombstones"] == ["attempt"]
    assert projection.query() == []
    assert projection.snapshot()["tombstones"] == ["attempt"]
    assert projection.stats()["tombstones"] == 1
    projection.ingest([OperationReceipt("attempt", "attempt", "running", "g1", 3, "loop/v1", {"producer": "loop", "correction_of": "attempt"})])
    assert projection.query()[0]["handle"] == "attempt"
    assert projection.snapshot()["tombstones"] == []


def test_operations_projection_supports_as_of_and_producer_freshness() -> None:
    projection = OperationsProjection("repo", "g1")
    projection.ingest([
        OperationReceipt("a1", "attempt", "running", "g1", 1, "loop/v1", {"producer": "loop"}),
        OperationReceipt("b2", "attempt", "running", "g1", 2, "runtime/v1", {"producer": "runtime"}),
        OperationReceipt("a3", "attempt", "done", "g1", 3, "loop/v1", {"producer": "loop"}),
    ])
    assert [item["handle"] for item in projection.query(as_of_sequence=2)] == ["b2", "a1"]
    snapshot = projection.snapshot(observed_sequence=4, as_of_sequence=2)
    assert [item["handle"] for item in snapshot["receipts"]] == ["b2", "a1"]
    assert snapshot["freshness"] == {
        "loop": {"latest_sequence": 3, "lag": 1},
        "runtime": {"latest_sequence": 2, "lag": 2},
    }
    with pytest.raises(OperationsProjectionError, match="query_as_of_invalid"):
        projection.query(as_of_sequence=True)
    with pytest.raises(OperationsProjectionError, match="snapshot_sequence_invalid"):
        projection.snapshot(observed_sequence=True)
