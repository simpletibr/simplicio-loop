from __future__ import annotations

from pathlib import Path

import pytest

from simplicio_loop.checkpoint_lifecycle import CandidateSpec, CheckpointLifecycle, LifecycleError


def lifecycle(tmp_path: Path) -> CheckpointLifecycle:
    base = tmp_path / "base"
    base.mkdir()
    return CheckpointLifecycle(
        tmp_path / ".simplicio-loop" / "loop-runs",
        task_id="task-761",
        attempt_id="attempt-1",
        source_commit="abc",
        fast_generation="generation-1",
        base_path=base,
    )


def test_overlays_are_isolated_and_idempotent(tmp_path):
    run = lifecycle(tmp_path)
    first = run.create_overlay("a")
    second = run.create_overlay("b")
    assert first != second
    assert run.create_overlay("a") == first
    assert (first / "overlay.json").read_bytes() != (second / "overlay.json").read_bytes()


def test_checkpoint_resume_revalidates_generation_and_overlay(tmp_path):
    run = lifecycle(tmp_path)
    value = run.checkpoint("a", "s1", "READY_TO_PROMOTE", receipts=["tests"], work_units=5)
    assert value["thread_id"] == "task-761/attempt-1"
    assert value["durable_execution"]["side_effects"] == "receipt-gated"
    assert run.load("a", "s1")["digest"] == value["digest"]


def test_applied_requires_receipts_langgraph_side_effect_practice(tmp_path):
    run = lifecycle(tmp_path)
    with pytest.raises(LifecycleError, match="receipts"):
        run.checkpoint("a", "s1", "APPLIED", receipts=[])
    ok = run.checkpoint("a", "s1", "APPLIED", receipts=["effect:abc"])
    assert ok["state"] == "APPLIED"
    assert ok["receipts"] == ["effect:abc"]
    stale = CheckpointLifecycle(
        run.root,
        task_id=run.task_id,
        attempt_id=run.attempt_id,
        source_commit=run.source_commit,
        fast_generation="generation-2",
        base_path=run.base_path,
    )
    with pytest.raises(LifecycleError, match="stale"):
        stale.load("a", "s1")


def test_adaptive_fanin_defaults_to_one_and_expands_on_risk(tmp_path):
    run = lifecycle(tmp_path)
    for candidate, work in (("a", 3), ("b", 2), ("c", 1)):
        run.checkpoint(candidate, "s1", "READY_TO_PROMOTE", receipts=["test", "lint"], work_units=work)
    specs = [
        CandidateSpec("a", risk=0.1, uncertainty=0.1),
        CandidateSpec("b", risk=0.1, uncertainty=0.1),
        CandidateSpec("c", risk=0.1, uncertainty=0.1),
    ]
    single = run.fanin(specs, expected_shards=["s1"])
    assert single["selected_candidates"] == ["a"]
    expanded = run.fanin(
        [CandidateSpec("a", risk=0.9, uncertainty=0.1), *specs[1:]],
        expected_shards=["s1"],
    )
    assert expanded["selected_candidates"] == ["a", "b", "c"]
    assert expanded["winner_id"] == "c"


def test_cancellation_propagates_and_partial_failure_is_held(tmp_path):
    run = lifecycle(tmp_path)
    called = []

    def cancel(candidate):
        called.append(candidate)
        if candidate == "b":
            raise RuntimeError("worker unavailable")

    result = run.cancel(["b", "a"], reason="winner selected", cancel_callback=cancel)
    assert result["status"] == "HELD"
    assert result["cancelled"] == ["a"]
    assert called == ["a", "b"]


def test_converge_seals_exactly_one_winner_and_cancels_loser(tmp_path):
    run = lifecycle(tmp_path)
    for candidate, work in (("a", 2), ("b", 1)):
        run.checkpoint(candidate, "s1", "READY_TO_PROMOTE", receipts=["tests"], work_units=work)
    cancelled = []
    result = run.converge(
        [CandidateSpec("a", 0.9, 0.1), CandidateSpec("b", 0.1, 0.1)],
        expected_shards=["s1"],
        cancel_callback=cancelled.append,
    )
    assert result["status"] == "SEALED"
    assert result["fence"]["winner_id"] == "b"
    assert cancelled == ["a"]
    assert run.seal_winner(result["fan_in"]) == result["fence"]


def test_explicit_winner_must_be_verified_and_is_never_reselected(tmp_path):
    run = lifecycle(tmp_path)
    run.checkpoint("good", "candidate", "READY_TO_PROMOTE", receipts=["tests"])
    run.checkpoint("failed", "candidate", "HELD", receipts=["error"])
    with pytest.raises(LifecycleError, match="not verified"):
        run.converge_selected(
            winner_id="failed", candidate_ids=["good", "failed"], shard_id="candidate")
    result = run.converge_selected(
        winner_id="good", candidate_ids=["good", "failed"], shard_id="candidate")
    assert result["fence"]["winner_id"] == "good"
    assert result["cancellation"]["cancelled"] == ["failed"]


def test_gc_never_removes_active_lease_then_reclaims_cancelled_overlay(tmp_path):
    run = lifecycle(tmp_path)
    run.checkpoint("a", "s1", "CANCELLED")
    run.cancel(["a"], reason="lost")
    run.lease("a", expires_ns=200)
    assert run.gc(retention_ns=0, now_ns=100, apply=True)["removed"] == []
    result = run.gc(retention_ns=0, now_ns=300, apply=True)
    assert result["removed"] == ["a"]
    assert not (run.overlays / "a").exists()


def test_missing_corrupt_and_nonterminal_shards_fail_closed(tmp_path):
    run = lifecycle(tmp_path)
    run.checkpoint("a", "s1", "PLANNED")
    with pytest.raises(LifecycleError, match="not promotion-ready"):
        run.fanin([CandidateSpec("a", 0, 0)], expected_shards=["s1"])
    with pytest.raises(LifecycleError, match="missing or corrupt"):
        run.fanin([CandidateSpec("a", 0, 0)], expected_shards=["missing"])


def test_generic_fanin_rejects_held_candidate_even_with_better_score(tmp_path):
    run = lifecycle(tmp_path)
    run.checkpoint(
        "ready", "candidate", "READY_TO_PROMOTE",
        receipts=["test"], work_units=10)
    run.checkpoint(
        "held", "candidate", "HELD",
        receipts=["test", "lint", "coverage"], work_units=1)
    with pytest.raises(LifecycleError, match="not promotion-ready.*HELD"):
        run.fanin(
            [
                CandidateSpec("held", risk=0.0, uncertainty=0.0, stalled=True),
                CandidateSpec("ready", risk=0.9, uncertainty=0.9),
            ],
            expected_shards=["candidate"],
        )
