"""The watcher's lease heartbeat joins the run's events.jsonl as `lease_heartbeat` (#1551).

`tick._heartbeat` renews the lease every HEARTBEAT_S while turbo runs; each renewal (and the loss of the lease) is
one event in the kanban run the watcher opened at intake, under the lease key (`repo#number`). The owner token is
the secret of the lease and never reaches an event.
"""
import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from simplicio_loop import dashboard_events
from simplicio_loop.claim_lease import ClaimStore
from simplicio_loop.watcher247 import config, events, state, tick
from simplicio_loop.watcher247.worktrees import state_home
from tests.test_turbo_1433_unit import repo  # noqa: F401 (repo is a fixture)

from .fakes import baseline, issue, run_tick
from .test_host_mode import REPO, HostRun, checkout, cli_dir  # noqa: F401 (cli_dir is a fixture)

SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "dashboard-event" / "v1" / "schema.json"
KEY = "demo#7"


def _beats(root: Path, run_id: str) -> list[dict]:
    run_dir = root / ".simplicio-loop" / "orchestrator" / "runs" / run_id
    return [e for e in dashboard_events.read_events(run_dir) if e["kind"] == "lease_heartbeat"]


def test_a_beat_is_one_collection_event_of_the_open_run_with_the_lease_key(repo):
    run_id = events.open_run(repo, "demo", 7)
    events.lease_beat(KEY, "renewed", beats=3, ttl_s=180)
    (beat,) = _beats(repo, run_id)
    assert (beat["scope"], beat["task_id"], beat["source"], beat["severity"]) == ("collection", None, "runner", "info")
    assert beat["phase"] is None
    assert beat["payload"] == {"lease_key": KEY, "status": "renewed", "beats": 3, "ttl_s": 180}
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(beat)


def test_a_lost_lease_is_a_warning_with_the_lost_status(repo):
    run_id = events.open_run(repo, "demo", 7)
    events.lease_beat(KEY, "lost", beats=2, ttl_s=180)
    (beat,) = _beats(repo, run_id)
    assert (beat["severity"], beat["payload"]["status"]) == ("warning", "lost")


def test_a_beat_goes_to_the_run_of_its_own_lease_only(repo):
    first = events.open_run(repo, "demo", 7)
    second = events.open_run(repo, "demo", 8)
    events.lease_beat(KEY, "renewed", beats=1, ttl_s=180)
    assert len(_beats(repo, first)) == 1 and _beats(repo, second) == []


def test_no_open_run_means_no_event_and_no_error(repo):
    events.lease_beat("never#1", "renewed", beats=1, ttl_s=180)  # nothing opened for this lease
    run_id = events.open_run(repo, "demo", 7)
    events.close_run(repo, run_id, "ok")
    events.lease_beat(KEY, "renewed", beats=1, ttl_s=180)  # the run is closed: a beat must not follow run_finished
    rows = dashboard_events.read_events(repo / ".simplicio-loop" / "orchestrator" / "runs" / run_id)
    assert rows[-1]["kind"] == "run_finished" and _beats(repo, run_id) == []


def test_a_failing_writer_never_raises_into_the_tick(repo, monkeypatch):
    events.open_run(repo, "demo", 7)

    def broken():
        raise OSError("disk gone")

    monkeypatch.setattr(events.dashboard_events, "load", broken)
    events.lease_beat(KEY, "renewed", beats=1, ttl_s=180)


def test_heartbeat_emits_one_renewed_event_per_renewal_with_a_rising_count(env, repo, monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT_S", 0.01)
    store = ClaimStore(config.CLAIMS)
    run_id = events.open_run(repo, "demo", 7)

    async def drive():
        token = await store.acquire(KEY, config.OWNER, config.LEASE_TTL_S, now=state.now().timestamp())
        task = asyncio.ensure_future(tick._heartbeat(store, KEY, token))
        for _ in range(500):
            if len(_beats(repo, run_id)) >= 3:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        return token

    token = asyncio.run(drive())
    got = _beats(repo, run_id)
    assert [b["payload"]["beats"] for b in got[:3]] == [1, 2, 3]
    assert {b["payload"]["status"] for b in got} == {"renewed"}
    assert {b["payload"]["ttl_s"] for b in got} == {config.LEASE_TTL_S}
    assert token not in json.dumps(got), "the owner token never reaches an event"


def test_heartbeat_reports_the_loss_once_and_stops(env, repo, monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT_S", 0.01)
    store = ClaimStore(config.CLAIMS)
    run_id = events.open_run(repo, "demo", 7)

    async def drive():
        token = await store.acquire(KEY, config.OWNER, config.LEASE_TTL_S, now=state.now().timestamp())
        await store.release(KEY, token, "done", now=state.now().timestamp())  # the lease is gone before the first beat
        await asyncio.wait_for(tick._heartbeat(store, KEY, token), 5)  # returns by itself when the lease is lost

    asyncio.run(drive())
    (beat,) = _beats(repo, run_id)
    assert (beat["payload"]["status"], beat["severity"]) == ("lost", "warning")


def test_a_real_tick_writes_the_beats_into_the_run_it_opened_at_intake(env, cli_dir, monkeypatch):  # noqa: F811
    env(HostRun({REPO: [issue(7)]}, delay=0.3))
    baseline()
    checkout()
    monkeypatch.setattr(config, "HEARTBEAT_S", 0.02)
    run_tick()
    runs = state_home(REPO, 7) / ".simplicio-loop" / "orchestrator" / "runs"
    (run_dir,) = [p for p in runs.iterdir() if p.is_dir()]
    rows = dashboard_events.read_events(run_dir)
    beats = [e for e in rows if e["kind"] == "lease_heartbeat"]
    assert len(beats) >= 3
    assert {b["payload"]["lease_key"] for b in beats} == {f"{REPO}#7"}
    first = beats[0]["payload"]["beats"]  # the lease was renewed before the run opened: the count starts there
    assert [b["payload"]["beats"] for b in beats] == list(range(first, first + len(beats)))
    assert rows[-1]["kind"] == "run_finished" and rows.index(beats[-1]) < len(rows) - 1, "no beat after the run closes"
