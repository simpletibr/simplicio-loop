"""`simplicio-loop squads plan` sizes the squads itself (--squads auto is the default); --squads N / SIMPLICIO_SQUADS win.

The probe is always a fake: these tests never read the real load, memory or disk.
"""
from __future__ import annotations

import json
import random

import pytest

from simplicio_loop import cli_impl, economy_profile, squad_capacity, squads
from simplicio_loop.squad_capacity import GIB, Limits, Probe

ECONOMY = {"SIMPLICIO_PRISM_SLOTS": "9", "SIMPLICIO_LOOP_OPERATOR_WORKERS": "10"}


def fake(cpu=10, load=(0.0, 0.0, 0.0), mem_gib=64.0, disk_gib=500.0):
    return Probe(cpu_count=cpu, load_average=load, memory_available_bytes=int(mem_gib * GIB),
                 disk_free_bytes=int(disk_gib * GIB))


def sample(n):
    return [{"number": i, "title": f"t{i}", "area": "api" if i % 2 else "web", "paths": [f"src/m{i}.py"]} for i in range(1, n + 1)]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("SIMPLICIO_SQUADS", "SIMPLICIO_PRISM_SLOTS", "SIMPLICIO_LOOP_OPERATOR_WORKERS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(economy_profile, "recommend_prism_slots_static", lambda *a, **kw: int(ECONOMY["SIMPLICIO_PRISM_SLOTS"]))
    monkeypatch.setattr(economy_profile, "recommend_operator_workers", lambda *a, **kw: int(ECONOMY["SIMPLICIO_LOOP_OPERATOR_WORKERS"]))


@pytest.fixture
def host(monkeypatch):
    """`host.probe` is what squad_capacity.measure answers; `host.calls` counts the measurements."""
    class Host:
        probe = fake()
        calls = 0

    def measure(root=".", **kw):
        Host.calls += 1
        return Host.probe

    monkeypatch.setattr(squad_capacity, "measure", measure)
    return Host


def run(capsys, *argv):
    code = cli_impl.main(["squads", "plan", *argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------------------------- plan_squads_auto


def test_auto_returns_the_plan_and_the_capacity():
    auto = squads.plan_squads_auto(sample(8), probe=fake(), limits=Limits())
    assert isinstance(auto.plan, squads.SquadPlan) and auto.capacity.total_workers == 8
    assert (auto.capacity.squads, auto.capacity.workers_per_squad) == (2, 4)


def test_sizing_never_changes_the_plan_or_the_merge_order():
    # Sizing decides how many run at once, never the squads, their file ownership, the merge order or the contracts.
    issues = sample(9) + [{"number": 10, "depends_on": [1], "area": "api"}]
    plain = squads.plan_squads(issues)
    rng = random.Random(7)
    for _ in range(60):
        probe = Probe(cpu_count=rng.randint(1, 64), load_average=tuple(rng.random() * 20 for _ in range(3)),
                      memory_available_bytes=int(rng.random() * 64 * GIB), disk_free_bytes=int(rng.random() * 300 * GIB))
        auto = squads.plan_squads_auto(issues, probe=probe, limits=Limits())
        assert auto.plan == plain
        assert auto.plan.merge_order == plain.merge_order and auto.plan.contracts == plain.contracts
    assert squads.plan_squads_auto(issues, probe=Probe(), limits=Limits(squads=1)).plan == plain


def test_auto_probes_once_when_no_probe_is_given(host):
    squads.plan_squads_auto(sample(4), limits=Limits())
    assert host.calls == 1
    squads.plan_squads_auto(sample(4), probe=fake(), limits=Limits())
    assert host.calls == 1, "a probe handed in is the sample: no second measurement"


def test_auto_keeps_the_planners_errors_first():
    cyclic = [{"number": 1, "body": "depends on #2"}, {"number": 2, "body": "depends on #1"}]
    with pytest.raises(squads.SquadCycleError):
        squads.plan_squads_auto(cyclic, probe=fake(), limits=Limits())
    with pytest.raises(squads.model_roles.ModelRoleError):
        squads.plan_squads_auto([], family="nope", probe=fake(), limits=Limits())
    with pytest.raises(squads.SquadPlanError):
        squads.plan_squads_auto(sample(2), probe=fake(), limits=Limits(max_workers_per_squad=0))


def test_the_explicit_max_workers_is_still_the_squad_size_ceiling():
    auto = squads.plan_squads_auto(sample(8), probe=fake(cpu=64), limits=Limits(max_workers_per_squad=2))
    assert auto.plan.max_workers == 2 and len(auto.plan.squads) == 4
    assert auto.capacity.workers_per_squad <= 2


# ---------------------------------------------------------------------------------------------- CLI


def test_default_is_auto_and_the_json_has_a_capacity_block(capsys, host):
    code, out = run(capsys, "--issues", json.dumps(sample(8)))
    assert code == 0 and host.calls == 1
    assert out["schema"] == "simplicio.squad-plan/v1"
    cap = out["capacity"]
    assert cap["schema"] == "simplicio.squad-capacity/v1"
    assert {"squads", "workers_per_squad", "total_workers", "limited_by", "proof_kind", "recheck_after_s", "reasons",
            "demand", "supply", "probe", "limits", "unverified", "estimates"} <= set(cap)
    assert cap["limits"]["squads"] is None and cap["total_workers"] == 8 and cap["limited_by"] == "demand"
    assert cap["proof_kind"] == "MEASURED" and cap["reasons"]


def test_a_busy_host_gets_a_small_answer_with_the_reason(capsys, host):
    host.probe = fake(cpu=10, load=(12.0, 11.0, 9.0), disk_gib=3.0)
    code, out = run(capsys, "--issues", json.dumps(sample(8)))
    cap = out["capacity"]
    assert code == 0 and cap["total_workers"] == 1 and cap["squads"] == 1
    assert any("load" in r for r in cap["reasons"]) and any("disk" in r for r in cap["reasons"])


def test_squads_flag_is_the_override_and_wins(capsys, host):
    host.probe = fake(cpu=10, load=(12.0, 12.0, 12.0))
    code, out = run(capsys, "--issues", json.dumps(sample(8)), "--squads", "2")
    cap = out["capacity"]
    assert code == 0 and cap["squads"] == 2 and cap["limited_by"] == "override"
    assert cap["limits"]["override_source"] == "--squads"


def test_squads_env_is_the_override_and_the_flag_beats_it(capsys, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SQUADS", "3")
    _, out = run(capsys, "--issues", json.dumps(sample(8)))
    assert out["capacity"]["squads"] == 3 and out["capacity"]["limits"]["override_source"] == "SIMPLICIO_SQUADS"
    _, out = run(capsys, "--issues", json.dumps(sample(8)), "--squads", "1")
    assert out["capacity"]["squads"] == 1
    _, out = run(capsys, "--issues", json.dumps(sample(8)), "--squads", "auto")
    assert out["capacity"]["limits"]["squads"] is None, "an explicit --squads auto turns the env override off"


@pytest.mark.parametrize("argv", [["--squads", "0"], ["--squads", "-1"], ["--squads", "many"]])
def test_zero_and_garbage_squads_are_blocked(capsys, host, argv):
    code, out = run(capsys, "--issues", json.dumps(sample(2)), *argv)
    assert code == 2 and out["status"] == "BLOCKED" and out["error"] == "ValueError" and "squads" in out["reason"]


def test_zero_squads_in_the_env_is_blocked_too(capsys, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SQUADS", "0")
    code, out = run(capsys, "--issues", json.dumps(sample(2)))
    assert code == 2 and out["status"] == "BLOCKED" and "SIMPLICIO_SQUADS" in out["reason"]


def test_a_worker_env_the_user_set_is_an_override_but_the_economy_value_is_not(capsys, host, monkeypatch):
    host.probe = fake(cpu=10, load=(12.0, 12.0, 12.0))
    monkeypatch.setenv("SIMPLICIO_PRISM_SLOTS", ECONOMY["SIMPLICIO_PRISM_SLOTS"])  # what `economy apply` exports
    _, out = run(capsys, "--issues", json.dumps(sample(8)))
    assert out["capacity"]["total_workers"] == 1 and out["capacity"]["limited_by"] == "load"
    monkeypatch.setenv("SIMPLICIO_PRISM_SLOTS", "10")  # above the profile's static figure (9)
    _, out = run(capsys, "--issues", json.dumps(sample(12)))
    assert out["capacity"]["total_workers"] == 10 and out["capacity"]["limited_by"] == "override"


def _run_with_stderr(capsys, *argv):
    code = cli_impl.main(["squads", "plan", *argv, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_an_override_above_the_machine_prints_the_warning_on_stderr_and_keeps_stdout_json(capsys, host):
    host.probe = fake(cpu=10, load=(12.0, 12.0, 12.0))
    code, out, err = _run_with_stderr(capsys, "--issues", json.dumps(sample(8)), "--squads", "2")
    cap = out["capacity"]
    assert code == 0 and cap["warnings"] and all(w.startswith("WARN: ") for w in cap["warnings"])
    assert err.splitlines() == cap["warnings"], "every warning of the plan, one per line, nothing else"
    assert "--squads" in err and "machine allows 1" in err
    assert cap["reasons"][0].startswith("WARN: ")


def test_no_warning_and_a_silent_stderr_when_nothing_is_overridden(capsys, host):
    code, out, err = _run_with_stderr(capsys, "--issues", json.dumps(sample(8)))
    assert code == 0 and out["capacity"]["warnings"] == [] and err == ""


def test_an_invalid_squads_value_stays_blocked_with_no_stderr_noise(capsys, host):
    code, out, err = _run_with_stderr(capsys, "--issues", json.dumps(sample(2)), "--squads", "\u00b2")
    assert code == 2 and out["status"] == "BLOCKED" and "squads" in out["reason"]


def test_max_workers_flag_still_works(capsys, host):
    code, out = run(capsys, "--issues", json.dumps(sample(8)), "--max-workers", "2")
    assert code == 0 and out["max_workers"] == 2 and len(out["squads"]) == 4
    assert out["capacity"]["workers_per_squad"] == 2


def test_the_plan_part_of_the_json_is_the_legacy_plan(capsys, host):
    host.probe = fake(cpu=2)
    code, out = run(capsys, "--issues", json.dumps(sample(8)))
    legacy = squads.plan_squads(sample(8)).to_dict()
    out.pop("capacity")
    assert code == 0 and out == legacy
