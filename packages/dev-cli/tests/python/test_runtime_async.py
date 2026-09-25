"""Tests for simplicio.runtime_async (issue #212).

No pytest-asyncio dependency is added — each async code path is driven with
a plain `asyncio.run()` call inside an ordinary (sync) test function, which
needs nothing beyond the stdlib already exercised by the rest of the suite.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from simplicio import runtime_async
from simplicio.utils import http_client

# ---------------------------------------------------------------------------
# _resolve_concurrency
# ---------------------------------------------------------------------------


def test_resolve_concurrency_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ASYNC_CONCURRENCY", "9")
    assert runtime_async._resolve_concurrency(3) == 3


def test_resolve_concurrency_reads_env_when_unset(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ASYNC_CONCURRENCY", "7")
    assert runtime_async._resolve_concurrency(None) == 7


def test_resolve_concurrency_defaults_when_env_missing(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_ASYNC_CONCURRENCY", raising=False)
    assert runtime_async._resolve_concurrency(None) == runtime_async.DEFAULT_CONCURRENCY


def test_resolve_concurrency_falls_back_on_bad_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ASYNC_CONCURRENCY", "not-a-number")
    assert runtime_async._resolve_concurrency(None) == runtime_async.DEFAULT_CONCURRENCY


def test_resolve_concurrency_clamps_to_at_least_one(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_ASYNC_CONCURRENCY", raising=False)
    assert runtime_async._resolve_concurrency(0) == 1
    assert runtime_async._resolve_concurrency(-5) == 1


# ---------------------------------------------------------------------------
# RuntimeContext
# ---------------------------------------------------------------------------


def test_runtime_context_semaphore_is_memoized():
    ctx = runtime_async.RuntimeContext(concurrency=2)
    sem1 = ctx.semaphore()
    sem2 = ctx.semaphore()
    assert sem1 is sem2


def test_runtime_context_run_bounded_executes_coro():
    async def scenario():
        ctx = runtime_async.RuntimeContext(concurrency=1)

        async def work():
            return 42

        return await ctx.run_bounded(work)

    assert asyncio.run(scenario()) == 42


def test_runtime_context_bounds_actual_concurrency():
    """The semaphore must cap in-flight coroutines, not just accept the number."""

    async def scenario():
        ctx = runtime_async.RuntimeContext(concurrency=2)
        active = 0
        peak = 0

        async def work():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return "done"

        results = await asyncio.gather(*(ctx.run_bounded(work) for _ in range(6)))
        return peak, results

    peak, results = asyncio.run(scenario())
    assert peak <= 2
    assert results == ["done"] * 6


def test_runtime_context_aclose_closes_shared_async_client():
    async def scenario():
        ctx = runtime_async.RuntimeContext()
        # Force-create the shared async client so aclose() has something to close.
        client = http_client.aclient()
        assert http_client._aclient is client
        await ctx.aclose()

    asyncio.run(scenario())
    assert http_client._aclient is None


# ---------------------------------------------------------------------------
# install_uvloop — never a hard dependency
# ---------------------------------------------------------------------------


def test_install_uvloop_noop_on_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert runtime_async.install_uvloop() is False


def test_install_uvloop_noop_when_uvloop_missing(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    real_import = __import__

    def _blocked_import(name, *args, **kwargs):
        if name == "uvloop":
            raise ImportError("no uvloop in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocked_import)
    assert runtime_async.install_uvloop() is False


# ---------------------------------------------------------------------------
# gather_bounded — independent-thunk fan-out, failure isolation
# ---------------------------------------------------------------------------


def test_gather_bounded_runs_all_thunks_in_order():
    async def scenario():
        async def make(i):
            await asyncio.sleep(0)
            return i * 10

        thunks = [(lambda i=i: make(i)) for i in range(5)]
        return await runtime_async.gather_bounded(thunks, concurrency=2)

    assert asyncio.run(scenario()) == [0, 10, 20, 30, 40]


def test_gather_bounded_isolates_failures():
    async def scenario():
        async def ok():
            return "ok"

        async def boom():
            raise ValueError("kaboom")

        return await runtime_async.gather_bounded([ok, boom, ok], concurrency=3)

    results = asyncio.run(scenario())
    assert results[0] == "ok"
    assert isinstance(results[1], ValueError)
    assert results[2] == "ok"


def test_gather_bounded_closes_shared_client_even_on_failure():
    async def scenario():
        http_client.aclient()  # force-create

        async def boom():
            raise RuntimeError("fail")

        await runtime_async.gather_bounded([boom])

    asyncio.run(scenario())
    assert http_client._aclient is None


# ---------------------------------------------------------------------------
# run_sync_in_thread — blocking bridge
# ---------------------------------------------------------------------------


def test_run_sync_in_thread_returns_value():
    def blocking(a, b, *, c=0):
        return a + b + c

    async def scenario():
        return await runtime_async.run_sync_in_thread(blocking, 1, 2, c=3)

    assert asyncio.run(scenario()) == 6


def test_run_sync_in_thread_propagates_exceptions():
    def blocking():
        raise KeyError("missing")

    async def scenario():
        await runtime_async.run_sync_in_thread(blocking)

    with pytest.raises(KeyError):
        asyncio.run(scenario())


def test_run_sync_in_thread_does_not_block_event_loop():
    """Two blocking calls dispatched concurrently must overlap in wall time."""
    import time

    def slow():
        time.sleep(0.05)
        return "slow-done"

    async def scenario():
        start = time.monotonic()
        results = await asyncio.gather(
            runtime_async.run_sync_in_thread(slow),
            runtime_async.run_sync_in_thread(slow),
        )
        elapsed = time.monotonic() - start
        return results, elapsed

    results, elapsed = asyncio.run(scenario())
    assert results == ["slow-done", "slow-done"]
    # Sequential execution would take >= 0.1s; concurrent execution should
    # finish well under that even with scheduling overhead.
    assert elapsed < 0.09


# ---------------------------------------------------------------------------
# http_client async additions
# ---------------------------------------------------------------------------


def test_aclient_returns_singleton():
    async def scenario():
        http_client._aclient = None
        c1 = http_client.aclient()
        c2 = http_client.aclient()
        assert c1 is c2
        await http_client.aclose()

    asyncio.run(scenario())
    assert http_client._aclient is None


def test_aclose_is_idempotent():
    async def scenario():
        await http_client.aclose()
        await http_client.aclose()

    asyncio.run(scenario())
    assert http_client._aclient is None


def test_apost_json_uses_shared_async_client(monkeypatch):
    calls = []

    class FakeResponse:
        content = b'{"ok": true}'

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        async def post(self, url, *, content, headers, timeout):
            calls.append((url, content, headers, timeout))
            return FakeResponse()

    monkeypatch.setattr(http_client, "aclient", lambda: FakeAsyncClient())

    async def scenario():
        return await http_client.apost_json("https://example.invalid/v1", {"a": 1})

    result = asyncio.run(scenario())
    assert result == {"ok": True}
    assert len(calls) == 1
    url, _content, headers, _timeout = calls[0]
    assert url == "https://example.invalid/v1"
    assert headers["Content-Type"] == "application/json"


def test_config_shared_between_sync_and_async_clients():
    """Both clients must derive from the same env-driven `_config()`."""
    cfg = http_client._config()
    assert isinstance(cfg["timeout"], httpx.Timeout)
    assert isinstance(cfg["limits"], httpx.Limits)
    assert cfg["follow_redirects"] is True
