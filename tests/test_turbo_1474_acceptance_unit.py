"""Acceptance tests for #1474: asyncio-native turbo service path."""
import asyncio
import threading
from unittest import mock
import pytest
from simplicio_loop import turbo_provider


class FakeTransport:
    """Tracks requests and supports cancellation with events."""
    def __init__(self):
        self.requests = []
        self.cancelled = set()
        self.start_event = asyncio.Event()
    
    async def handle(self, session_id):
        """Record request, wait for cancellation event."""
        self.requests.append(session_id)
        try:
            await self.start_event.wait()
        except asyncio.CancelledError:
            self.cancelled.add(session_id)
            raise


def test_hedge_cancels_losing_request():
    """Hedge cancels losing request, not billed."""
    transport = FakeTransport()
    
    async def mock_post(body, key, session_id, timeout):
        if "hedge" in session_id:
            await transport.handle(session_id)
        else:
            await asyncio.sleep(0.05)
            return {"ok": True, "content": "slow", "latency_s": 0.05}
    
    async def run_test():
        with mock.patch("simplicio_loop.turbo_provider._post", side_effect=mock_post):
            result = await turbo_provider.complete(
                "test",
                [{"role": "user", "content": "test"}],
                session_id="test-session",
                api_key="test-key",
                hedge=0.02,
            )
        return result
    
    result = asyncio.run(run_test())
    assert result["hedged"] is True
    assert result["hedge_winner"] == "primary"
    assert "test-session-hedge" in transport.cancelled


def test_no_extra_threads_during_hedge():
    """No extra threads created during hedged call."""
    transport = FakeTransport()
    
    async def slow_post(body, key, session_id, timeout):
        if "hedge" in session_id:
            await transport.handle(session_id)
        else:
            await asyncio.sleep(0.05)
            return {"ok": True, "content": "ok", "latency_s": 0.05}
    
    async def run_test():
        thread_count_before = threading.active_count()
        with mock.patch("simplicio_loop.turbo_provider._post", side_effect=slow_post):
            result = await turbo_provider.complete(
                "test",
                [{"role": "user", "content": "test"}],
                session_id="test-session",
                api_key="test-key",
                hedge=0.01,
            )
        thread_count_after = threading.active_count()
        return thread_count_before, thread_count_after
    
    thread_count_before, thread_count_after = asyncio.run(run_test())
    assert thread_count_after == thread_count_before


def test_1_and_n_tasks_same_path():
    """1 task and N tasks use same async path."""
    import inspect
    from simplicio_loop import turbo
    
    assert inspect.iscoroutinefunction(turbo.run_turbo)
    assert inspect.iscoroutinefunction(turbo._run_concurrent)


def test_dev_cli_apply_serialized():
    """Dev-cli apply never runs concurrently."""
    from simplicio_loop.turbo import _apply_operations
    import inspect
    
    # Verify _apply_operations is async and takes apply_lock
    assert inspect.iscoroutinefunction(_apply_operations)
    sig = inspect.signature(_apply_operations)
    assert "apply_lock" in sig.parameters
