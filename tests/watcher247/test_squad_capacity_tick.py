"""The watcher sizes its squads by default (squad_capacity): one MEASURED probe per tick, shared with resource_governor.

The probe is faked at the lowest level (`local_capacity.probe_local_capacity` and the load average): nothing here reads
the real load of the host. SIMPLICIO_247_CONCURRENCY=N is the explicit override and wins.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from simplicio_loop import local_capacity, squad_capacity
from simplicio_loop.squad_capacity import GIB, Probe
from simplicio_loop.watcher247 import config, tick

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REAL_MEASURE = squad_capacity.measure  # the conftest replaces it with a fixed probe; these tests want the real one
REPOS = ["simplicio-a", "simplicio-b", "simplicio-c", "simplicio-d"]


@pytest.fixture
def host(env, monkeypatch):
    """`host.set(cpu=..., load=...)` is the machine; `host.calls` counts every probe of the disk, memory and cores."""
    monkeypatch.setattr(squad_capacity, "measure", REAL_MEASURE)

    class Host:
        calls = 0
        cpu, load, memory, disk = 10, (0.0, 0.0, 0.0), 64 * GIB, 500 * GIB
        age_ns = 0  # how old the sample already is when the probe answers

        def set(self, **kw):
            for name, value in kw.items():
                setattr(self, name, value)

    machine = Host()

    def sample(root=".", **kwargs):
        machine.calls += 1
        return local_capacity.CapacitySample(
            requested_workers=1, safe_workers=1, cpu_count=machine.cpu, memory_available_bytes=machine.memory,
            disk_free_bytes=machine.disk, measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
            unavailable=(), null_reasons={}, observed_at_ns=time.time_ns() - machine.age_ns)

    monkeypatch.setattr(local_capacity, "probe_local_capacity", sample)
    monkeypatch.setattr(squad_capacity, "_loadavg", lambda: machine.load)
    return machine


def one_issue_per_repo(env, n=4, **kwargs):
    fake = env(FakeRun({name: [issue(i)] for i, name in enumerate(REPOS[:n], 1)}, diff=False, **kwargs))
    baseline()
    return fake


def test_one_probe_per_tick_is_shared_with_resource_governor(env, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    one_issue_per_repo(env, 2)
    run_tick()
    assert sorted(read_json(config.STATUS)["processed"]) == ["simplicio-a#1", "simplicio-b#2"]
    assert host.calls == 1, "the sizing probe is the governor's sample: two workers, ONE measurement"


def test_a_stale_sample_is_not_reused_by_the_governor(env, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "1")
    host.set(age_ns=squad_capacity.SHARE_MAX_AGE_NS + 10**9)
    one_issue_per_repo(env, 1)
    run_tick()
    assert read_json(config.STATUS)["processed"] == ["simplicio-a#1"]
    assert host.calls == 2, "an old sample is not a safety check: the governor measures for itself"


def test_default_runs_as_many_as_the_idle_machine_carries(env, host):
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 4, "idle 10 cores: all four repos in one tick, not one"


def test_a_busy_machine_shrinks_the_batch_to_one(env, host):
    host.set(load=(12.0, 12.0, 12.0))
    one_issue_per_repo(env, 4)
    run_tick()
    assert read_json(config.STATUS)["processed"] == ["simplicio-a#1"]


def test_a_small_machine_limits_the_batch_by_cpu(env, host):
    host.set(cpu=4)  # floor(0.8 * 4) = 3
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 3


def test_explicit_concurrency_wins_over_the_load(env, host, monkeypatch):
    host.set(load=(12.0, 12.0, 12.0))
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "3")
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 3


def test_a_garbage_concurrency_is_ignored_and_the_machine_decides(env, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "lots")
    host.set(load=(12.0, 12.0, 12.0))
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 1


@pytest.mark.parametrize("bad", ["0", "-1", "2.0", "lots", "\u00b2", "9" * 5000, " "],
                         ids=["zero", "negative", "float", "text", "superscript", "5000-digits", "blank"])
def test_an_invalid_concurrency_never_fails_the_tick_it_logs_one_warning_and_the_machine_decides(env, host, monkeypatch, capsys, bad):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", bad)
    host.set(load=(12.0, 12.0, 12.0))
    one_issue_per_repo(env, 4)
    run_tick()  # a 5,000-digit or "\u00b2" value used to raise ValueError in int() and fail every tick
    assert read_json(config.STATUS)["processed"] == ["simplicio-a#1"], "automatic sizing: the busy host runs one"
    warned = [line for line in capsys.readouterr().out.splitlines() if "WARN: SIMPLICIO_247_CONCURRENCY=" in line]
    assert len(warned) == (0 if not bad.strip() else 1), warned
    assert all(len(line) < 400 for line in warned), "a huge value is clipped in the log line"


def test_an_override_above_the_machine_is_logged_once_per_tick(env, host, monkeypatch, capsys):
    host.set(load=(12.0, 12.0, 12.0))  # the machine allows 1 worker
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "3")
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 3
    warned = [line for line in capsys.readouterr().out.splitlines()
              if "WARN: SIMPLICIO_247_CONCURRENCY forces 3 worker(s) at once; the machine allows 1 (limited by load)" in line]
    assert len(warned) == 1, warned


def test_no_override_means_no_warning_in_the_log(env, host, capsys):
    host.set(load=(12.0, 12.0, 12.0))
    one_issue_per_repo(env, 4)
    run_tick()
    assert "WARN:" not in capsys.readouterr().out


def test_an_override_within_the_machine_is_not_a_warning(env, host, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")  # the idle 10-core host allows 8
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 2 and "WARN:" not in capsys.readouterr().out


def test_the_daily_pr_cap_still_limits_the_batch(env, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_PRS_PER_DAY", "2")
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 2


def test_status_carries_the_capacity_and_why(env, host):
    fake = env(FakeRun({"simplicio-a": [issue(1, body="Ajustar `src/a.py` para o fluxo do watcher seguir o contrato."),
                                       issue(2, body="Ajustar `src/b.py` para o fluxo do watcher seguir o contrato."),
                                       issue(3, body="Ajustar `src/c.py` para o fluxo do watcher seguir o contrato.")]},
                        diff=False))
    baseline()
    run_tick()
    capacity = read_json(config.STATUS)["squads"]["simplicio-a"]["capacity"]
    assert (capacity["total_workers"], capacity["squads"], capacity["limited_by"]) == (3, 1, "demand")
    assert capacity["proof_kind"] == "MEASURED" and capacity["reasons"] and capacity["probe"]["cpu_count"] == 10
    assert fake.turbo_argv, "the issues were worked"


def test_an_unmeasurable_machine_runs_one_worker_and_says_unverified(env, host, monkeypatch):
    monkeypatch.setattr(squad_capacity, "measure", lambda root=".", **kw: Probe())
    one_issue_per_repo(env, 3)
    run_tick()
    status = read_json(config.STATUS)
    assert status["processed"] == ["simplicio-a#1"]
    assert status["squads"]["simplicio-a"]["capacity"]["proof_kind"] == "UNVERIFIED"


def test_zero_squads_in_the_env_is_a_tick_error_not_a_silent_default(env, host, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SQUADS", "0")
    one_issue_per_repo(env, 1)
    with pytest.raises(ValueError, match="SIMPLICIO_SQUADS"):
        asyncio.run(tick.tick())


def test_the_squads_env_pins_the_batch(env, host, monkeypatch):
    host.set(load=(12.0, 12.0, 12.0))
    monkeypatch.setenv("SIMPLICIO_SQUADS", "1")  # one squad of up to 4 workers
    one_issue_per_repo(env, 4)
    run_tick()
    assert len(read_json(config.STATUS)["processed"]) == 4
