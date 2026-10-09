"""Squads drain benchmark (#1549, part of): the load generator, the metrics and a tiny in-process drain.

The drain here runs with time_scale ~0 and a fixed idle machine probe, so it is fast and does not depend on the host.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bench" / "benchmark_squads_drain.py"
_spec = importlib.util.spec_from_file_location("benchmark_squads_drain", SCRIPT)
bench = importlib.util.module_from_spec(_spec)
sys.modules["benchmark_squads_drain"] = bench
_spec.loader.exec_module(bench)

from simplicio_loop import squad_metrics  # noqa: E402


def _levels(load) -> dict[int, int]:
    """Longest-chain level of each task, computed here from the edges only (not from the generator's own field)."""
    deps = {t.number: t.deps for t in load.tasks}
    level: dict[int, int] = {}

    def of(number: int, seen: tuple = ()) -> int:
        assert number not in seen, "dependency cycle"
        if number not in level:
            level[number] = 1 + max((of(d, seen + (number,)) for d in deps[number]), default=-1)
        return level[number]

    for number in deps:
        of(number)
    return level


def test_same_seed_same_load_and_other_seed_other_load():
    assert bench.generate_load(seed=1) == bench.generate_load(seed=1)
    assert bench.generate_load(seed=1) != bench.generate_load(seed=2)


def test_load_shape_is_acyclic_40_tasks_width_12_depth_5():
    load = bench.generate_load(seed=1)
    assert len(load.tasks) == 40
    numbers = {t.number for t in load.tasks}
    assert len(numbers) == 40
    assert all(set(t.deps) <= numbers and t.number not in t.deps for t in load.tasks)
    levels = _levels(load)  # raises on a cycle
    widths = [sum(1 for v in levels.values() if v == k) for k in range(max(levels.values()) + 1)]
    assert len(widths) == 5
    assert max(widths) == 12 and all(1 <= w <= 12 for w in widths)
    assert sum(widths) == 40


def test_load_durations_and_failures_follow_the_declared_distribution():
    load = bench.generate_load(seed=1)
    assert all(0.2 <= t.duration_s <= 1.5 and 0.2 <= t.retry_duration_s <= 1.5 for t in load.tasks)
    assert sum(t.fails_first for t in load.tasks) == 6  # exactly round(0.15 * 40)


def test_issue_rows_carry_the_real_dependency_syntax():
    from simplicio_loop import squads

    load = bench.generate_load(seed=1)
    deps = squads.dependencies(bench.issue_rows(load))
    assert deps == {t.number: tuple(sorted(t.deps)) for t in load.tasks}


def test_spread_is_median_min_max_of_the_measured_values():
    assert bench.spread([3.0, 1.0, 2.0, 10.0, 4.0]) == {"n": 5, "median": 3.0, "min": 1.0, "max": 10.0}
    assert bench.spread([]) == {"n": 0, "median": None, "min": None, "max": None}


def test_run_metrics_from_hand_made_records():
    escalated = [{"role": "execution", "outcome": "failed", "reason": "verify_failed"}, {"role": "coordination", "outcome": "ok"}]
    plain = [{"role": "execution", "outcome": "ok"}]
    merged_at = {1: 10.0, 2: 12.0}
    records = [
        {**squad_metrics.task_record(plain, [], 8.0, merged_at, "ok"), "issue": "r#1"},
        {**squad_metrics.task_record(escalated, [1], 9.0, merged_at, "ok"), "issue": "r#2"},  # waits 10 - 9 = 1.0
        {**squad_metrics.task_record(plain, [1, 2], 10.0, merged_at, "ok"), "issue": "r#3"},  # waits 12 - 10 = 2.0
    ]
    m = bench.run_metrics(records, wall_s=6.0, merged=3)
    assert m["prs_per_min"] == 30.0
    assert m["dependency_wait_mean_s"] == 1.5 and m["dependency_wait_n"] == 2
    assert m["escalation_rate"] == pytest.approx(1 / 3, abs=1e-4) and m["escalated"] == 1


def test_run_metrics_without_dependency_samples_is_none_not_zero():
    plain = [{"role": "execution", "outcome": "ok"}]
    records = [{**squad_metrics.task_record(plain, [], 1.0, {}, "ok"), "issue": "r#1"}]
    assert bench.run_metrics(records, wall_s=2.0, merged=1)["dependency_wait_mean_s"] is None


@pytest.mark.parametrize("mode", ["baseline", "squads-v2-off", "squads"])
def test_tiny_drain_merges_everything_in_dependency_order(mode):
    run = asyncio.run(bench.run_once(mode=mode, probe_kind="idle", seed=1, time_scale=0.0005))
    assert run["merged"] == 40 and run["invariants_ok"] is True
    assert run["escalated"] == 6 and run["escalation_rate"] == 0.15
    assert 1 <= run["max_concurrent_workers"] <= run["workers"]
    assert run["workers"] == 1 if mode == "baseline" else run["workers"] > 1
    assert run["simulated"] is True and run["time_scale"] == 0.0005


def test_baseline_tests_every_pr_and_squads_use_the_merge_train():
    base = asyncio.run(bench.run_once(mode="baseline", probe_kind="idle", seed=1, time_scale=0.0005))
    v2 = asyncio.run(bench.run_once(mode="squads", probe_kind="idle", seed=1, time_scale=0.0005))
    assert base["train_tests"] == 40 and base["train_batch_max"] == 1
    assert v2["train_batch_max"] <= 4 and v2["train_tests"] <= 40


def test_idle_probe_sizes_squads_from_demand_and_cores():
    run = asyncio.run(bench.run_once(mode="squads", probe_kind="idle", seed=1, time_scale=0.0005))
    assert run["workers"] == 8 and run["limited_by"] == "cpu"  # 10 cores x 4/5 = 8; the demand is 12
    assert run["squads"] == 2 and run["workers_per_squad"] == 4
