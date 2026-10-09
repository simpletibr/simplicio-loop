"""Tests for resource_governor extension point (intake stage).

The point decides from local_capacity.probe_local_capacity's own verdict (safe_workers, null_reasons) and is
registered blocking, so a deferred stops the stage. The probe is faked to be host-independent.
"""
import asyncio

import pytest

from simplicio_loop import local_capacity
from simplicio_loop.watcher247 import config, points
from simplicio_loop.watcher247.points import resource_governor

from ..fakes import FakeRun, baseline, issue, read_json, run_tick, tasks

GB = 1 << 30


def sample(safe_workers=1, reason=None, disk=20 * GB, memory=4 * GB):
    return local_capacity.CapacitySample(
        requested_workers=1, safe_workers=safe_workers, cpu_count=4, memory_available_bytes=memory,
        disk_free_bytes=disk, measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
        unavailable=(), null_reasons={"workers": reason} if reason else {}, observed_at_ns=0)


@pytest.fixture
def probe(monkeypatch):
    """Fake the probe: `probe.sample` is what it answers, `probe.roots` the directories it was asked to measure."""
    class Probe:
        sample = sample()
        roots: list = []

    def fake(root=".", **kwargs):
        Probe.roots.append(root)
        return Probe.sample

    Probe.roots = []
    monkeypatch.setattr(local_capacity, "probe_local_capacity", fake)
    return Probe


def test_registered_blocking_at_intake():
    (info,) = [i for i in points.registered() if i.name == "resource_governor"]
    assert info.stage == "intake" and info.blocking


def test_ok_when_the_probe_finds_a_safe_worker(probe, make_ctx, tmp_path):
    result = asyncio.run(resource_governor.govern(make_ctx(state_dir=tmp_path)))
    assert result.status == "ok" and result.reason_code is None
    assert result.evidence["safe_workers"] == 1


@pytest.mark.parametrize("reason", ["disk_pressure", "memory_pressure", "required_capacity_signal_unavailable"])
def test_defers_with_the_probes_own_reason(probe, make_ctx, tmp_path, reason):
    probe.sample = sample(safe_workers=0, reason=reason)
    result = asyncio.run(resource_governor.govern(make_ctx(state_dir=tmp_path)))
    assert result.status == "deferred" and result.reason_code == reason


def test_without_a_state_dir_it_is_skipped_and_never_probes_the_cwd(probe, point_contract, make_ctx):
    result = point_contract("resource_governor", make_ctx(), expect="skipped")
    assert result.reason_code == "not_applicable" and probe.roots == []


def test_the_probe_measures_the_state_dir_not_the_cwd(probe, make_ctx, tmp_path):
    asyncio.run(resource_governor.govern(make_ctx(state_dir=tmp_path)))
    assert probe.roots == [tmp_path]


def test_a_deferred_result_stops_the_stage(probe, make_ctx, tmp_path):
    probe.sample = sample(safe_workers=0, reason="disk_pressure")
    with pytest.raises(points.PointDeferred) as stopped:
        asyncio.run(points.run("intake", make_ctx(state_dir=tmp_path)))
    assert stopped.value.name == "resource_governor" and stopped.value.reason_code == "disk_pressure"


def test_real_tick_low_disk_gives_the_attempt_back_and_the_issue_is_due_again(env, probe):
    """The effect, through the real registry and tick: no turbo, attempt returned, lease released, due next tick."""
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    probe.sample = sample(safe_workers=0, reason="disk_pressure", disk=1 * GB)
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "retry" and claim["attempts"] == 0  # the attempt is given back
    assert claim["owner_token"] is None and claim["lease_expires_at"] is None  # lease released
    assert claim.get("next_try_at") is None and claim["reason_code"] == "disk_pressure"
    assert tasks(fake) == []  # the turbo never ran
    assert config.ROOT in probe.roots

    probe.sample = sample()  # the disk was freed: the same issue is picked up on the next tick
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "done" and claim["attempts"] == 1
    assert len(tasks(fake)) == 1
