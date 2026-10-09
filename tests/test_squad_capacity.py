"""Automatic squad sizing (`squad_capacity`): demand from the issues, supply from a MEASURED probe, one verdict.

Every test injects a fake probe: nothing here reads the real load, memory or disk of the machine running it.
"""
from __future__ import annotations

import dataclasses
import json
import math
import random

import pytest

from simplicio_loop import economy_profile, local_capacity, squad_capacity, squads
from simplicio_loop.squad_capacity import GIB, Limits, Probe

IDLE = (0.0, 0.0, 0.0)


def probe(cpu=10, load=IDLE, mem_gib=64.0, disk_gib=500.0, **kw) -> Probe:
    return Probe(cpu_count=cpu, load_average=load, memory_available_bytes=int(mem_gib * GIB),
                 disk_free_bytes=int(disk_gib * GIB), **kw)


def independent(n):
    return [{"number": i, "paths": [f"src/m{i}.py"]} for i in range(1, n + 1)]


def chain(n):
    return [{"number": i, "paths": [f"src/m{i}.py"], **({"depends_on": [i - 1]} if i > 1 else {})} for i in range(1, n + 1)]


def rec(issues, p=None, **limits):
    return squad_capacity.recommend(issues, p or probe(), Limits(**limits))


# ---------------------------------------------------------------------------------------------- demand


def test_three_independent_issues_on_an_idle_64_core_host_give_three_workers_in_one_squad():
    plan = rec(independent(3), probe(cpu=64))
    assert (plan.total_workers, plan.squads, plan.workers_per_squad) == (3, 1, 3)
    assert plan.limited_by == "demand" and plan.proof_kind == "MEASURED"


def test_a_six_issue_linear_chain_is_width_one_even_on_a_huge_host():
    plan = rec(chain(6), probe(cpu=256, mem_gib=2048))
    assert plan.demand.width == 1 and plan.demand.levels == (1, 1, 1, 1, 1, 1)
    assert (plan.total_workers, plan.squads) == (1, 1) and plan.limited_by == "demand"


def test_a_diamond_is_as_wide_as_its_widest_level():
    issues = [{"number": 1}, {"number": 2, "depends_on": [1]}, {"number": 3, "depends_on": [1]},
              {"number": 4, "depends_on": [1]}, {"number": 5, "depends_on": [2, 3, 4]}]
    demand = squad_capacity.measure_demand(issues)
    assert demand.levels == (1, 3, 1) and demand.width == 3 and demand.issues == 5


def test_body_dependencies_count_like_depends_on():
    issues = [{"number": 1}, {"number": 2, "body": "depends on #1"}, {"number": 3, "body": "depende de #2"}]
    assert squad_capacity.measure_demand(issues).width == 1


def test_issues_that_share_a_file_cannot_run_together():
    issues = [{"number": n, "paths": ["src/shared.py"]} for n in (1, 2, 3, 4)]
    demand = squad_capacity.measure_demand(issues)
    assert demand.width == 1 and demand.conflicts == 6


def test_a_partial_conflict_still_leaves_two_in_parallel():
    # 1-2 share a file and 2-3 share a file, 1 and 3 do not: 1 and 3 can run together.
    issues = [{"number": 1, "paths": ["a.py"]}, {"number": 2, "paths": ["a.py", "b.py"]}, {"number": 3, "paths": ["b.py"]}]
    assert squad_capacity.measure_demand(issues).width == 2


def test_paths_are_cleaned_like_the_squad_planner_does():
    issues = [{"number": 1, "paths": ["./src/a.py"]}, {"number": 2, "paths": ["src\\a.py"]}]
    assert squad_capacity.measure_demand(issues).width == 1


def test_no_issues_means_no_workers():
    plan = rec([])
    assert plan.total_workers == 0 and plan.squads == 0 and plan.limited_by == "demand"


def test_a_dependency_cycle_is_the_planners_own_error():
    cyclic = [{"number": 1, "body": "depends on #2"}, {"number": 2, "body": "depends on #1"}]
    with pytest.raises(squads.SquadCycleError):
        squad_capacity.measure_demand(cyclic)


def test_demand_can_be_passed_in_precomputed():
    demand = squad_capacity.measure_demand(independent(5))
    assert rec(demand, probe(cpu=64)).total_workers == 5


# ---------------------------------------------------------------------------------------------- supply


def test_cpu_limited():
    plan = rec(independent(10), probe(cpu=4))
    assert plan.total_workers == 3 and plan.limited_by == "cpu"  # floor(0.8 * 4)


def test_load_limited_by_a_busy_host():
    plan = rec(independent(10), probe(cpu=10, load=(12.0, 12.0, 12.0)))
    assert plan.total_workers == 1 and plan.limited_by == "load"
    assert any("load" in r for r in plan.reasons)


def test_load_leaves_headroom_proportionally():
    plan = rec(independent(10), probe(cpu=10, load=(4.0, 5.0, 4.0)))
    assert plan.total_workers == 3 and plan.limited_by == "load"  # floor(8 - 5)


def test_an_idle_host_is_cpu_limited_not_load_limited():
    plan = rec(independent(40), probe(cpu=10))
    assert plan.total_workers == 8 and plan.limited_by == "cpu"


def test_memory_limited():
    plan = rec(independent(10), probe(cpu=64, mem_gib=4.0))
    assert plan.total_workers == 2 and plan.limited_by == "memory"  # (4 - 0.5) / 1.25
    assert any("ESTIMATE" in r for r in plan.reasons), "the per-worker memory is an estimate and says so"


def test_disk_limited_names_the_disk_and_never_fills_it():
    plan = rec(independent(10), probe(cpu=64, disk_gib=3 * 1e9 / GIB))  # 3 GB free
    assert plan.total_workers == 1 and plan.limited_by == "disk"
    assert any("disk" in r and "floor" in r for r in plan.reasons)


def test_disk_gives_one_worker_per_gib_above_the_floor():
    plan = rec(independent(40), probe(cpu=64, disk_gib=2 + 5.5))
    assert plan.total_workers == 5 and plan.limited_by == "disk"


def test_budget_cap_limits_and_can_be_exhausted():
    assert rec(independent(10), probe(cpu=64), budget_left=2).limited_by == "budget"
    assert rec(independent(10), probe(cpu=64), budget_left=2).total_workers == 2
    spent = rec(independent(10), probe(cpu=64), budget_left=0)
    assert spent.total_workers == 0 and spent.squads == 0 and spent.limited_by == "budget"


def test_unknown_probe_is_the_conservative_minimum_and_unverified():
    plan = rec(independent(10), Probe())
    assert plan.total_workers == 1 and plan.proof_kind == "UNVERIFIED"
    assert set(plan.unverified) == {"cpu_count", "load_average", "memory_available_bytes", "disk_free_bytes"}
    assert all(plan.unverified.values()), "each missing value carries a reason"


@pytest.mark.parametrize("missing", ["cpu_count", "load_average", "memory_available_bytes", "disk_free_bytes"])
def test_any_single_missing_value_falls_back_to_one_worker(missing):
    full = probe(cpu=64)
    plan = rec(independent(10), dataclasses.replace(full, **{missing: None}))
    assert plan.total_workers == 1 and plan.proof_kind == "UNVERIFIED" and list(plan.unverified) == [missing]
    limit = {"cpu_count": "cpu", "load_average": "load", "memory_available_bytes": "memory", "disk_free_bytes": "disk"}[missing]
    assert plan.supply[limit] == 1, "the unknown limit itself is the conservative minimum, never unlimited"


def test_the_probes_own_reason_is_kept():
    plan = rec(independent(3), Probe(cpu_count=8, load_average=IDLE, memory_available_bytes=8 * GIB,
                                     disk_free_bytes=None, null_reasons={"disk_free_bytes": "disk_probe_failed"}))
    assert plan.unverified == {"disk_free_bytes": "disk_probe_failed"}


# ---------------------------------------------------------------------------------------------- overrides


def test_explicit_squads_override_wins_over_the_machine():
    busy = probe(cpu=10, load=(12.0, 12.0, 12.0))
    assert rec(independent(8), busy).total_workers == 1
    forced = rec(independent(8), busy, squads=2)
    assert forced.squads == 2 and forced.total_workers == 8 and forced.workers_per_squad == 4
    assert forced.limited_by == "override"
    assert any("override" in r for r in forced.reasons)


def test_explicit_squads_never_makes_an_empty_squad():
    forced = rec(independent(2), probe(cpu=64), squads=5)
    assert forced.squads == 2 and forced.total_workers == 2


def test_explicit_workers_override_wins_over_the_machine():
    busy = probe(cpu=10, load=(12.0, 12.0, 12.0))
    forced = rec(independent(8), busy, workers=5)
    assert forced.total_workers == 5 and forced.limited_by == "override"


def test_override_above_demand_is_limited_by_demand():
    assert rec(independent(3), probe(), workers=9).limited_by == "demand"


def test_the_daily_budget_still_caps_an_override():
    plan = rec(independent(8), probe(), squads=3, budget_left=2)
    assert plan.total_workers == 2 and plan.limited_by == "budget"


def test_override_reports_what_the_machine_would_have_allowed():
    forced = rec(independent(8), probe(cpu=10, load=(12.0, 12.0, 12.0)), workers=6)
    assert any("load" in r and "1" in r for r in forced.reasons)


def test_squads_option_parses_auto_and_positive_integers_only():
    assert squad_capacity.parse_squads("auto") is None and squad_capacity.parse_squads(" AUTO ") is None
    assert squad_capacity.parse_squads("3") == 3 and squad_capacity.parse_squads(2) == 2
    for bad in ("0", "-1", "x", "1.5", 0, True):
        with pytest.raises(ValueError):
            squad_capacity.parse_squads(bad)


ECONOMY = {"SIMPLICIO_PRISM_SLOTS": "9", "SIMPLICIO_LOOP_OPERATOR_WORKERS": "10"}


def test_limits_from_env_reads_the_squads_override():
    assert Limits.from_env({}, economy=ECONOMY) == Limits()
    assert Limits.from_env({"SIMPLICIO_SQUADS": "3"}, economy=ECONOMY).squads == 3
    assert Limits.from_env({"SIMPLICIO_SQUADS": "auto"}, economy=ECONOMY).squads is None
    for bad in ("0", "-2", "many"):
        with pytest.raises(ValueError):
            Limits.from_env({"SIMPLICIO_SQUADS": bad}, economy=ECONOMY)


def test_a_worker_env_above_the_economy_profile_is_a_user_override():
    assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "20"}, economy=ECONOMY).workers == 20
    both = {"SIMPLICIO_PRISM_SLOTS": "20", "SIMPLICIO_LOOP_OPERATOR_WORKERS": "12"}
    assert Limits.from_env(both, economy=ECONOMY).workers == 12, "when both are explicit the smaller one is used"
    assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "10"}, economy=ECONOMY).workers == 10, "one above the static figure"


def test_the_economy_profiles_own_values_are_not_an_override():
    # `simplicio-loop economy apply` exports these two for every session; they must not switch the load check off.
    assert Limits.from_env(dict(ECONOMY), economy=ECONOMY).workers is None
    # ...nor does a value at or below the static figure: the profile tightens its value when free RAM is low.
    assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "2", "SIMPLICIO_LOOP_OPERATOR_WORKERS": "3"}, economy=ECONOMY).workers is None


def test_garbage_worker_envs_are_ignored():
    for bad in ("0", "-1", "lots", ""):
        assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": bad}, economy=ECONOMY).workers is None


def test_extra_worker_envs_are_always_explicit():
    env = {"SIMPLICIO_247_CONCURRENCY": "2"}
    limits = Limits.from_env(env, economy=ECONOMY, extra_worker_envs=("SIMPLICIO_247_CONCURRENCY",), budget_left=7)
    assert limits.workers == 2 and limits.budget_left == 7


def test_limits_from_env_computes_the_economy_profile_when_not_injected(monkeypatch):
    monkeypatch.setattr(economy_profile, "recommend_prism_slots_static", lambda *a, **kw: 7)
    monkeypatch.setattr(economy_profile, "recommend_operator_workers", lambda *a, **kw: 7)
    assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "7"}).workers is None
    assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "8"}).workers == 8
    assert Limits.from_env({"SIMPLICIO_LOOP_OPERATOR_WORKERS": "8"}).workers == 8


def _host_with_free_ram(monkeypatch, avail_gb):
    """A 10-core host with 32 GiB in total and `avail_gb` free: the profile exports 9 on an idle host."""
    monkeypatch.setattr(economy_profile, "_cpu_count", lambda: 10)
    monkeypatch.setattr(economy_profile, "_ram_gb", lambda: (32.0, avail_gb))


def test_a_profile_value_exported_on_an_idle_host_is_not_an_override_when_the_ram_is_low_later(monkeypatch):
    # Audit of #1572, defect 1. `economy apply` exported PRISM_SLOTS=9; now only 2.0 GiB are free, so the profile would
    # recompute 2. The old code saw 9 != 2, took it for a user override and switched ALL machine limits off.
    _host_with_free_ram(monkeypatch, 20.0)
    exported = economy_profile.economy_parallel_env()
    assert exported["SIMPLICIO_PRISM_SLOTS"] == "9"
    _host_with_free_ram(monkeypatch, 2.0)
    assert economy_profile.economy_parallel_env()["SIMPLICIO_PRISM_SLOTS"] == "2"
    env = {k: exported[k] for k in ("SIMPLICIO_PRISM_SLOTS", "SIMPLICIO_LOOP_OPERATOR_WORKERS")}
    limits = Limits.from_env(env)
    assert limits.workers is None and limits.override_source == ""
    plan = squad_capacity.recommend(independent(10), probe(cpu=10, mem_gib=2.0), limits)
    assert plan.limited_by == "memory" and plan.total_workers == 1, "the machine decides, not an override"
    assert plan.warnings == () and not any(r.startswith(("override", "WARN")) for r in plan.reasons)


def test_a_deliberate_value_above_the_profile_still_overrides_when_the_ram_is_low(monkeypatch):
    _host_with_free_ram(monkeypatch, 2.0)
    for value in ("10", "20", "64"):
        limits = Limits.from_env({"SIMPLICIO_PRISM_SLOTS": value})
        assert limits.workers == int(value) and limits.override_source == "SIMPLICIO_PRISM_SLOTS"
    assert Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "9"}).workers is None, "the static figure itself is the profile's"
    assert Limits.from_env({"SIMPLICIO_LOOP_OPERATOR_WORKERS": "10"}).workers is None
    assert Limits.from_env({"SIMPLICIO_LOOP_OPERATOR_WORKERS": "11"}).workers == 11
    plan = squad_capacity.recommend(independent(12), probe(cpu=10, mem_gib=2.0), Limits.from_env({"SIMPLICIO_PRISM_SLOTS": "10"}))
    assert plan.total_workers == 10 and plan.limited_by == "override"


# ---------------------------------------------------------------------------------------------- invalid SIMPLICIO_247_CONCURRENCY

CONCURRENCY = "SIMPLICIO_247_CONCURRENCY"


def _concurrency(value):
    return Limits.from_env({CONCURRENCY: value}, economy=ECONOMY, extra_worker_envs=(CONCURRENCY,))


@pytest.mark.parametrize("bad", ["0", "-1", "2.0", "lots", "\u00b2", "\u0663", "9" * 5000, "1234567", "+3", "1e2"],
                         ids=["zero", "negative", "float", "text", "superscript", "arabic-indic", "5000-digits", "7-digits", "plus", "exp"])
def test_an_invalid_concurrency_never_raises_and_falls_back_to_the_automatic_sizing_with_a_warning(bad):
    limits = _concurrency(bad)  # must not raise, whatever the text
    assert limits.workers is None and limits.override_source == ""
    assert len(limits.warnings) == 1 and limits.warnings[0].startswith("WARN: ")
    assert CONCURRENCY in limits.warnings[0] and "automatic" in limits.warnings[0]
    assert len(limits.warnings[0]) < 300, "a huge value is clipped in the message"
    if len(bad) < 40:
        assert repr(bad) in limits.warnings[0], "the message names the invalid value"
    plan = squad_capacity.recommend(independent(4), probe(cpu=10), limits)
    assert plan.total_workers == 4 and plan.warnings == limits.warnings
    assert limits.warnings[0] in plan.reasons and json.loads(json.dumps(plan.to_dict()))["warnings"] == list(limits.warnings)


@pytest.mark.parametrize("good,expected", [("3", 3), (" 3", 3), ("08", 8), ("3 ", 3), ("999999", 999999), ("1", 1)])
def test_a_valid_concurrency_is_the_override(good, expected):
    limits = _concurrency(good)
    assert limits.workers == expected and limits.override_source == CONCURRENCY and limits.warnings == ()


@pytest.mark.parametrize("unset", ["", "   "])
def test_an_unset_concurrency_is_automatic_without_a_warning(unset):
    limits = _concurrency(unset)
    assert limits.workers is None and limits.warnings == ()
    assert Limits.from_env({}, economy=ECONOMY, extra_worker_envs=(CONCURRENCY,)).warnings == ()


def test_parse_squads_never_raises_anything_but_value_error():
    for bad in ("\u00b2", "9" * 5000, "\u0663", "1" * 7):
        with pytest.raises(ValueError, match="squads must be"):
            squad_capacity.parse_squads(bad)
    assert squad_capacity.parse_squads("999999") == 999999


# ---------------------------------------------------------------------------------------------- override above the machine

LOADED = (9.6, 9.7, 9.9)  # a busy 10-core host: the machine allows 1 worker (limited by load)


def test_an_override_above_the_machine_warns_in_the_plan():
    plan = rec(independent(10), probe(cpu=10, load=LOADED), workers=64, override_source="SIMPLICIO_PRISM_SLOTS")
    assert plan.total_workers == 10, "the override still wins: it is the user's decision"
    assert len(plan.warnings) == 1 and plan.warnings[0].startswith("WARN: ")
    for part in ("SIMPLICIO_PRISM_SLOTS", "10 worker(s)", "allows 1", "load"):
        assert part in plan.warnings[0], part
    assert plan.reasons[0].startswith("WARN: ") and "limited by demand" not in plan.reasons[0], "the headline says it"
    override_line = next(r for r in plan.reasons if "wins over the machine limits" in r)
    assert override_line.startswith("WARN: override: 64 worker(s) set by SIMPLICIO_PRISM_SLOTS")
    assert json.loads(json.dumps(plan.to_dict()))["warnings"] == list(plan.warnings)


def test_a_squads_override_above_the_machine_warns_too():
    plan = rec(independent(8), probe(cpu=10, load=LOADED), squads=3, override_source="--squads")
    assert plan.total_workers == 8 and plan.warnings and "--squads" in plan.warnings[0]
    assert plan.reasons[0].startswith("WARN: ")


def test_a_budget_cap_does_not_hide_the_warning():
    plan = rec(independent(10), probe(cpu=10, load=LOADED), workers=64, budget_left=3, override_source="X")
    assert plan.total_workers == 3 and plan.limited_by == "budget" and plan.warnings


def test_the_warning_does_not_change_proof_kind():
    assert rec(independent(10), probe(cpu=10, load=LOADED), workers=64).proof_kind == "MEASURED"
    partial = Probe(cpu_count=10, load_average=LOADED, memory_available_bytes=None, disk_free_bytes=500 * GIB)
    plan = rec(independent(10), partial, workers=64)
    assert plan.warnings and plan.proof_kind == "UNVERIFIED", "a missing value stays UNVERIFIED next to the warning"


@pytest.mark.parametrize("limits", [dict(), dict(workers=2), dict(squads=1), dict(workers=64), dict(workers=8)])
def test_no_warning_when_nothing_runs_above_what_the_machine_allows(limits):
    # idle 10 cores allow 8; an override that stays within it, or demand that keeps the run within it, is silent
    issues = independent(1) if limits.get("workers") == 64 else independent(10)
    plan = rec(issues, probe(cpu=10), **limits)
    assert plan.total_workers <= 8 and plan.warnings == ()
    assert not plan.reasons[0].startswith("WARN") and not any(r.startswith("WARN") for r in plan.reasons)


def test_one_worker_above_the_machine_is_already_a_warning():
    plan = rec(independent(10), probe(cpu=10), workers=9)  # an idle 10-core host allows 8
    assert plan.total_workers == 9 and len(plan.warnings) == 1 and "allows 8" in plan.warnings[0]


def test_an_override_that_demand_keeps_within_the_machine_is_not_a_warning():
    plan = rec(independent(1), probe(cpu=10, load=LOADED), workers=64)
    assert plan.total_workers == 1 and plan.warnings == ()


def test_resize_keeps_the_warning_of_an_override():
    plan = rec(independent(10), probe(cpu=10, load=LOADED), workers=64)
    again = squad_capacity.resize(plan, probe(cpu=10, load=LOADED))
    assert again.warnings == plan.warnings


# ---------------------------------------------------------------------------------------------- properties


def test_a_plan_never_exceeds_the_squad_size_and_is_json_serializable():
    for width in (1, 2, 3, 4, 5, 9, 17):
        plan = rec(independent(width), probe(cpu=128))
        assert plan.workers_per_squad <= squads.DEFAULT_MAX_WORKERS == squad_capacity.MAX_WORKERS_PER_SQUAD
        assert plan.squads == math.ceil(plan.total_workers / plan.workers_per_squad)
        assert plan.squads * plan.workers_per_squad >= plan.total_workers
        assert json.loads(json.dumps(plan.to_dict()))["total_workers"] == plan.total_workers


def _worse(rng, p: Probe) -> Probe:
    """A probe that is no better than `p` in any signal (more load, less memory, less disk, fewer cores, or unknown)."""
    load = p.load_average
    if load is not None and rng.random() < 0.8:
        load = tuple(x + rng.random() * 6 for x in load)
    elif rng.random() < 0.1:
        load = None
    return Probe(
        cpu_count=None if rng.random() < 0.05 else max(1, p.cpu_count - rng.randint(0, 3)),
        load_average=load,
        memory_available_bytes=None if rng.random() < 0.05 else int(p.memory_available_bytes * rng.random()),
        disk_free_bytes=None if rng.random() < 0.05 else int(p.disk_free_bytes * rng.random()),
    )


def test_monotonic_more_pressure_never_adds_workers():
    rng = random.Random(1565)
    demand = squad_capacity.measure_demand(independent(64))
    for _ in range(400):
        base = Probe(cpu_count=rng.randint(1, 64), load_average=tuple(rng.random() * 20 for _ in range(3)),
                     memory_available_bytes=int(rng.random() * 64 * GIB), disk_free_bytes=int(rng.random() * 400 * GIB))
        worse = _worse(rng, base)
        a = squad_capacity.recommend(demand, base, Limits()).total_workers
        b = squad_capacity.recommend(demand, worse, Limits()).total_workers
        assert 1 <= b <= a, (base, worse, a, b)


def test_every_single_signal_is_monotonic_on_its_own():
    demand = squad_capacity.measure_demand(independent(64))
    cpu = [squad_capacity.recommend(demand, probe(cpu=c), Limits()).total_workers for c in range(1, 65)]
    load = [squad_capacity.recommend(demand, probe(load=(x, x, x)), Limits()).total_workers for x in range(0, 25)]
    mem = [squad_capacity.recommend(demand, probe(cpu=64, mem_gib=m / 4), Limits()).total_workers for m in range(1, 200)]
    disk = [squad_capacity.recommend(demand, probe(cpu=64, disk_gib=d / 2), Limits()).total_workers for d in range(1, 100)]
    assert cpu == sorted(cpu) and mem == sorted(mem) and disk == sorted(disk)
    assert load == sorted(load, reverse=True)


def test_the_same_inputs_always_give_the_same_plan():
    one = rec(independent(9), probe(cpu=6, load=(3.0, 2.0, 1.0)))
    assert one == rec(independent(9), probe(cpu=6, load=(3.0, 2.0, 1.0)))


def test_the_constants_are_labelled_estimates_in_the_plan():
    plan = rec(independent(3))
    assert plan.estimates["worker_memory_bytes"] == int(1.25 * GIB) and plan.estimates["label"] == "ESTIMATE"
    assert plan.estimates["worker_disk_bytes"] == GIB


def test_floors_are_the_local_capacity_floors():
    assert squad_capacity.DISK_FLOOR_BYTES == local_capacity.DEFAULT_DISK_FLOOR_BYTES
    assert squad_capacity.MEMORY_FLOOR_BYTES == local_capacity.DEFAULT_MEMORY_FLOOR_BYTES


# ---------------------------------------------------------------------------------------------- resize


def test_resize_shrinks_at_once_when_the_load_rises():
    plan = rec(independent(10), probe(cpu=10))
    assert plan.total_workers == 8
    smaller = squad_capacity.resize(plan, probe(cpu=10, load=(9.0, 9.0, 9.0)))
    assert smaller.total_workers == 1 and smaller.limited_by == "load"
    assert any("shrink" in r for r in smaller.reasons)


def test_resize_grows_only_after_the_load_stays_low_for_a_full_wave():
    busy = probe(cpu=10, load=(6.0, 6.0, 6.0))
    plan = rec(independent(10), busy)
    assert plan.total_workers == 2
    calm = probe(cpu=10)
    held = squad_capacity.resize(plan, calm)  # first calm sample: still 2
    assert held.total_workers == 2 and any("growth waits" in r for r in held.reasons)
    grown = squad_capacity.resize(held, calm)  # a second calm sample in a row: the wave stayed calm
    assert grown.total_workers == 8 and any("grow" in r for r in grown.reasons)


def test_a_spike_between_two_calm_samples_resets_the_wait():
    plan = rec(independent(10), probe(cpu=10, load=(6.0, 6.0, 6.0)))
    held = squad_capacity.resize(plan, probe(cpu=10))
    spiked = squad_capacity.resize(held, probe(cpu=10, load=(9.0, 9.0, 9.0)))
    assert spiked.total_workers == 1
    again = squad_capacity.resize(spiked, probe(cpu=10))
    assert again.total_workers == 1, "after a shrink the calm count starts over"
    assert squad_capacity.resize(again, probe(cpu=10)).total_workers == 8


def test_resize_keeps_the_same_size_when_nothing_changed():
    plan = rec(independent(10), probe(cpu=10))
    assert squad_capacity.resize(plan, probe(cpu=10)).total_workers == plan.total_workers


def test_resize_never_exceeds_an_unknown_probe():
    plan = rec(independent(10), probe(cpu=10))
    assert squad_capacity.resize(plan, Probe()).total_workers == 1


# ---------------------------------------------------------------------------------------------- probe


def test_measure_builds_the_probe_from_the_local_capacity_sample():
    sample = local_capacity.CapacitySample(
        requested_workers=1, safe_workers=1, cpu_count=6, memory_available_bytes=3 * GIB, disk_free_bytes=9 * GIB,
        measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"), unavailable=(), null_reasons={},
        observed_at_ns=123)
    calls = []

    def fake(root, **kw):
        calls.append((root, kw))
        return sample

    got = squad_capacity.measure("/some/root", probe_fn=fake, loadavg_fn=lambda: (1.0, 2.0, 3.0))
    assert got.cpu_count == 6 and got.load_average == (1.0, 2.0, 3.0)
    assert got.memory_available_bytes == 3 * GIB and got.disk_free_bytes == 9 * GIB and got.observed_at_ns == 123
    assert got.sample is sample and calls == [("/some/root", {"requested_workers": 1, "reserve_workers": 0})]


def test_measure_marks_a_missing_load_average_unverified():
    sample = local_capacity.CapacitySample(
        requested_workers=1, safe_workers=0, cpu_count=None, memory_available_bytes=None, disk_free_bytes=None,
        measured=(), unavailable=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
        null_reasons={"cpu_count": "os_cpu_count_unavailable"}, observed_at_ns=1)

    def no_load():
        raise OSError("no getloadavg")

    got = squad_capacity.measure(".", probe_fn=lambda root, **kw: sample, loadavg_fn=no_load)
    assert got.load_average is None and got.null_reasons["load_average"] == "getloadavg_unavailable"
    assert got.null_reasons["cpu_count"] == "os_cpu_count_unavailable"


def test_a_shared_sample_is_reused_only_while_fresh():
    sample = local_capacity.CapacitySample(
        requested_workers=1, safe_workers=1, cpu_count=2, memory_available_bytes=GIB, disk_free_bytes=GIB,
        measured=(), unavailable=(), null_reasons={}, observed_at_ns=1_000)
    shared = probe(sample=sample, observed_at_ns=1_000)
    assert squad_capacity.shared_sample(shared, now_ns=1_000 + 5 * 10**9) is sample
    assert squad_capacity.shared_sample(shared, now_ns=1_000 + 31 * 10**9) is None
    assert squad_capacity.shared_sample(None) is None
    assert squad_capacity.shared_sample(probe(), now_ns=1) is None, "a probe without a raw sample cannot be shared"


def test_to_dict_carries_the_measured_values_the_reasons_and_the_proof():
    out = rec(independent(3), probe(cpu=8, load=(1.0, 2.0, 3.0))).to_dict()
    assert out["schema"] == "simplicio.squad-capacity/v1"
    assert {"squads", "workers_per_squad", "total_workers", "limited_by", "proof_kind", "recheck_after_s", "reasons",
            "demand", "supply", "probe", "limits", "unverified", "estimates"} <= set(out)
    assert out["probe"]["load_average"] == [1.0, 2.0, 3.0] and out["demand"]["width"] == 3
    assert out["supply"]["cpu"] == 6 and isinstance(out["reasons"], list) and out["reasons"]
    assert "sample" not in out["probe"]


def test_recheck_hint_is_short_when_the_limit_can_move_fast():
    assert rec(independent(10), probe(cpu=10, load=(9.0, 9.0, 9.0))).recheck_after_s < rec(independent(2), probe()).recheck_after_s
