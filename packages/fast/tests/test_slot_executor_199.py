from concurrent.futures import ThreadPoolExecutor
import pytest

from simplicio_fast.slot_executor import FastExecutorError, SlotExecutor, make_envelope


def test_two_slots_share_read_snapshot_but_isolate_writes(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {"code.py": b"x=1\n"})
    first, second = make_envelope(1), make_envelope(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(
            pool.map(
                lambda item: executor.execute(
                    item, snapshot, writes={"result.txt": item["slot_id"].encode()}
                ),
                (first, second),
            )
        )
    assert receipts[0]["snapshot_id"] == receipts[1]["snapshot_id"]
    overlays = list((tmp_path / "overlays" / "run").glob("*/result.txt"))
    assert sorted(path.read_text() for path in overlays) == ["slot-1", "slot-2"]


def test_twenty_two_slots_have_distinct_generation_fence_overlays(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {"x": b"x"})
    receipts = [
        executor.execute(
            make_envelope(i, generation=i, fence=f"f{i}"), snapshot, writes={"x": b"y"}
        )
        for i in range(22)
    ]
    assert len({item["overlay_id"] for item in receipts}) == 22
    assert executor.workers_started == 22


def test_duplicate_is_idempotent_and_does_not_start_worker(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {})
    envelope = make_envelope(1)
    first = executor.execute(envelope, snapshot)
    second = executor.execute(envelope, snapshot)
    assert first["receipt_digest"] == second["receipt_digest"]
    assert second["cache_hit"] and second["duplicate_dispatch"]
    assert executor.workers_started == 1


def test_corrupt_snapshot_and_receipt_fail_closed(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {"x": b"x"})
    object_path = snapshot.root / "objects" / snapshot.manifest["x"]
    object_path.write_bytes(b"corrupt")
    with pytest.raises(FastExecutorError, match="snapshot_corrupt"):
        executor.open_snapshot("run", "source", {"x": b"x"})
    clean = executor.open_snapshot("run2", "source", {})
    envelope = make_envelope(1, run_id="run2")
    receipt = executor.execute(envelope, clean)
    receipt["status"] = "DELIVERED"
    assert executor.verify_receipt(receipt, envelope)[0] is False


def test_cache_binding_and_stale_source_rejected(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {})
    changed = make_envelope(1)
    changed["config_hash"] = "changed"
    with pytest.raises(FastExecutorError, match="idempotency_mismatch"):
        executor.execute(changed, snapshot)
    stale = make_envelope(2)
    stale["source_hash"] = "different"
    from simplicio_fast.slot_executor import REQUIRED_HASHES, digest

    stale["idempotency_key"] = digest(
        {
            key: stale[key]
            for key in (
                "run_id",
                "slot_id",
                "issue_id",
                "commit",
                "generation",
                "fence",
                *REQUIRED_HASHES,
            )
        }
    )
    with pytest.raises(FastExecutorError, match="snapshot_stale"):
        executor.execute(stale, snapshot)


def test_mapper_reads_bounded_mmap_pages_not_full_dump(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {"big": b"a" * 10000})
    page = snapshot.page("big", offset=100, limit=100)
    assert len(page["bytes"]) == 100 and not page["eof"]
    with pytest.raises(FastExecutorError, match="invalid_page"):
        snapshot.page("big", limit=1000000)


def test_python_fallback_metrics_and_offline_verification(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {})
    envelope = make_envelope(1)
    receipt = executor.execute(
        envelope, snapshot, runtime_available=False, rust_available=False
    )
    assert receipt["runtime_mode"] == "python_fallback"
    assert receipt["runtime_null_reason"] == "RUNTIME_UNAVAILABLE"
    assert receipt["engine_null_reason"] == "RUST_UNAVAILABLE"
    assert receipt["tokens"] is None and receipt["tokens_null_reason"] == "NO_LLM_USED"
    assert executor.verify_receipt(receipt, envelope) == (True, "ok")
    assert receipt["completion_authority"] == "LOOP_ONLY"


def test_overlay_escape_and_budget_are_blocked(tmp_path):
    executor = SlotExecutor(tmp_path)
    snapshot = executor.open_snapshot("run", "source", {})
    with pytest.raises(FastExecutorError, match="overlay_escape"):
        executor.execute(make_envelope(1), snapshot, writes={"../escape": b"x"})
    envelope = make_envelope(2)
    envelope["budget"] = {"max_operations": 1}
    with pytest.raises(FastExecutorError, match="budget_exhausted"):
        executor.execute(envelope, snapshot, writes={"a": b"a", "b": b"b"})


def test_quantization_lanes_metrics_and_rust_absence_are_explicit():
    from simplicio_fast.slot_executor import parity_receipt, quantize, ranking_metrics

    vector = (-1.0, -0.2, 0.1, 1.0)
    assert quantize(vector, "Q0") == vector
    assert all(-127 <= item <= 127 for item in quantize(vector, "Q1"))
    assert all(-7 <= item <= 7 for item in quantize(vector, "Q2a"))
    metrics = ranking_metrics(["a", "b"], ["a", "x", "b"])
    assert metrics["recall_at_10"] == 1.0
    assert 0 < metrics["ndcg_at_10"] <= 1
    assert metrics["mrr"] == 1.0
    assert parity_receipt({"fixture": 1})["parity"] is None
    assert parity_receipt({"fixture": 1})["parity_null_reason"] == "RUST_UNAVAILABLE"
