"""#1474: the turbo service path is asyncio-native. No sleeps: events and fake transports only."""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.turbo import run_turbo


@pytest.mark.parametrize("stuck, winner", [("s", "duplicate"), ("s-hedge", "primary")])
def test_the_hedge_loser_is_cancelled(monkeypatch, stuck, winner):
    cancelled: list[str] = []
    duplicate_out = asyncio.Event()

    async def post(body, key, session_id, timeout):
        if session_id.endswith("-hedge"):
            duplicate_out.set()
        if session_id == stuck:  # this request never answers: only a cancel ends it
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(session_id)
                raise
        if session_id == "s":
            await duplicate_out.wait()  # the healthy primary answers only once the hedge went out
        return {"ok": True, "content": session_id, "latency_s": 0.0}

    async def scenario():
        reply = await turbo_provider.complete("x", [], session_id="s", api_key="k", hedge=0.01)
        return reply, [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    monkeypatch.setattr(turbo_provider, "_post", post)

    reply, leftover = asyncio.run(scenario())
    assert reply["hedged"] is True and reply["hedge_winner"] == winner
    assert cancelled == [stuck]  # the loser was cancelled, not awaited to the end
    assert leftover == []  # and no request task outlives the call


def test_a_hedged_call_starts_no_thread(monkeypatch):
    seen_threads: list[int] = []

    async def post(body, key, session_id, timeout):
        seen_threads.append(threading.active_count())
        if session_id == "s":
            await asyncio.Event().wait()
        return {"ok": True, "content": "ok", "latency_s": 0.0}

    monkeypatch.setattr(turbo_provider, "_post", post)
    before = threading.active_count()
    reply = asyncio.run(turbo_provider.complete("x", [], session_id="s", api_key="k", hedge=0.01))
    assert reply["hedged"] is True
    assert seen_threads == [before, before] and threading.active_count() == before
    assert not hasattr(turbo_provider, "_pool")  # the thread pool is gone, not just idle


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """A repo with a Mapper map, a fake dev-cli subprocess, and gauges for what runs at the same time."""
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    state = tmp_path / ".simplicio-loop"
    state.mkdir()
    (state / "project-map.json").write_text('{"mark":"MAP"}', encoding="utf-8")
    gauge = SimpleNamespace(applying=0, max_applying=0, calling=0, max_calling=0, commands=0)

    receipt = b'{"schema":"simplicio.dev-cli.edit-receipt/v1","applied":true,"receipt_digest":"fake"}'

    class FakeProcess:
        returncode = 0

        def __init__(self, cmd):
            self._stdout = receipt if "--apply" in cmd else b"{}"

        async def communicate(self):
            for _ in range(5):  # yield to every other task: an unguarded second apply would start here
                await asyncio.sleep(0)
            gauge.applying -= 1
            return self._stdout, b""

    async def fake_exec(*cmd, **kwargs):
        gauge.commands += 1
        gauge.applying += 1
        gauge.max_applying = max(gauge.max_applying, gauge.applying)
        return FakeProcess(cmd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    async def complete(arm, messages, **kwargs):
        gauge.calling += 1
        gauge.max_calling = max(gauge.max_calling, gauge.calling)
        for _ in range(5):
            await asyncio.sleep(0)
        gauge.calling -= 1
        if kwargs.get("max_tokens") == 1:
            return {"ok": True, "content": "OK"}
        index = messages[-1]["content"].split("Tasks:", 1)[1].strip().split(".", 1)[0]
        ops = [{"path": f"f{index}.txt", "find": "", "replace": index}]
        return {"ok": True, "content": json.dumps({"operations": ops})}

    return SimpleNamespace(root=tmp_path, gauge=gauge, complete=complete)


@pytest.mark.parametrize("count", [1, 2, 5, 12])
def test_one_task_and_many_tasks_share_the_same_bounded_path(engine, monkeypatch, count):
    monkeypatch.setenv("SIMPLICIO_TURBO_CONCURRENCY", "3")
    tasks = [{"index": i, "text": f"Create f{i}.txt", "depends_on": []} for i in range(1, count + 1)]
    result = asyncio.run(run_turbo(engine.root, tasks, engine.complete, dev_cli="fake-dev-cli"))
    assert result["applied_all"] is True and len(result["outcomes"]) == (1 if count <= 3 else count)
    assert engine.gauge.commands == len(result["commands"]) > 0
    assert engine.gauge.max_calling <= 3  # model calls are bounded by the semaphore
    assert engine.gauge.max_applying == 1  # dev-cli applies never overlap


def test_a_wave_really_fans_out_up_to_the_limit(engine, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TURBO_CONCURRENCY", "4")
    tasks = [{"index": i, "text": f"Create f{i}.txt", "depends_on": []} for i in range(1, 9)]
    result = asyncio.run(run_turbo(engine.root, tasks, engine.complete, dev_cli="fake-dev-cli"))
    assert result["applied_all"] is True and result["wave"] is True
    assert engine.gauge.max_calling == 4 and engine.gauge.max_applying == 1
    assert [call["turn"] for call in result["llm_calls"]] == [0, 2, 3, 4, 5, 6, 7, 8, 9]  # the warm-up, then one per task


def test_the_concurrency_limit_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TURBO_CONCURRENCY", raising=False)
    assert turbo_provider.concurrency() == 8
    for raw, expected in ((("2"), 2), ("0", 1), ("junk", 8)):
        monkeypatch.setenv("SIMPLICIO_TURBO_CONCURRENCY", raw)
        assert turbo_provider.concurrency() == expected
