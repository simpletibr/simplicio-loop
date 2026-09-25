import asyncio
import pytest

from simplicio_fast.resident_daemon import DaemonError, ResidentFastDaemon, make_request


def run(coro):
    return asyncio.run(coro)


def test_one_daemon_multiplexes_twenty_slots_and_single_flights_generation():
    async def scenario():
        opened = 0
        active = 0
        peak = 0

        async def opener(generation):
            nonlocal opened
            opened += 1
            await asyncio.sleep(0.001)
            return generation

        async def handler(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.001)
            active -= 1
            return {"slot": request.slot_id}

        daemon = ResidentFastDaemon(
            handler, max_inflight=5, queue_capacity=20, generation_opener=opener
        )
        await daemon.start()
        receipts = await asyncio.gather(
            *(daemon.submit(make_request(f"r{i}", f"s{i}")) for i in range(20))
        )
        assert len(receipts) == 20 and opened == 1 and peak <= 5
        assert daemon.health()["pinned_generations"] == [1]
        await daemon.shutdown()

    run(scenario())


def test_shutdown_drains_and_releases_pin():
    async def scenario():
        released = []

        async def handler(request):
            await asyncio.sleep(0.001)
            return {"ok": True}

        daemon = ResidentFastDaemon(
            handler, generation_closer=lambda pin: _append(released, pin)
        )
        await daemon.start()
        task = asyncio.create_task(daemon.submit(make_request("r", "s")))
        await asyncio.sleep(0)
        health = await daemon.shutdown(drain=True)
        assert (await task)["status"] == "COMPLETED"
        assert health["state"] == "STOPPED" and released == [1]

    run(scenario())


async def _append(target, value):
    target.append(value)


def test_timeout_and_cancel_do_not_leak_work():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            started.set()
            await release.wait()
            return {}

        daemon = ResidentFastDaemon(handler, max_inflight=1)
        await daemon.start()
        task = asyncio.create_task(
            daemon.submit(make_request("r", "s", timeout_seconds=0.01))
        )
        await started.wait()
        with pytest.raises(DaemonError, match="deadline_expired"):
            await task
        await asyncio.sleep(0)
        assert daemon.health()["inflight"] == 0
        await daemon.shutdown()

    run(scenario())


def test_backpressure_is_bounded():
    async def scenario():
        hold = asyncio.Event()

        async def handler(request):
            await hold.wait()
            return {}

        daemon = ResidentFastDaemon(handler, max_inflight=1, queue_capacity=1)
        await daemon.start()
        first = asyncio.create_task(daemon.submit(make_request("1", "s")))
        await asyncio.sleep(0)
        second = asyncio.create_task(daemon.submit(make_request("2", "s")))
        await asyncio.sleep(0)
        with pytest.raises(DaemonError, match="backpressure"):
            await daemon.submit(make_request("3", "s"))
        hold.set()
        await asyncio.gather(first, second)
        await daemon.shutdown()

    run(scenario())


def test_crash_restart_does_not_confirm_lost_request_and_snapshot_is_reopened():
    async def scenario():
        started = asyncio.Event()
        opened = 0

        async def opener(generation):
            nonlocal opened
            opened += 1
            return generation

        async def handler(request):
            started.set()
            await asyncio.sleep(60)

        daemon = ResidentFastDaemon(handler, generation_opener=opener)
        await daemon.start()
        lost = asyncio.create_task(
            daemon.submit(make_request("lost", "s", timeout_seconds=1))
        )
        await started.wait()
        await daemon.crash()
        with pytest.raises(DaemonError, match="request_cancelled"):
            await lost
        assert "lost" not in daemon._terminal
        daemon._pins.clear()

        async def recovered(request):
            return {"recovered": True}

        daemon._handler = recovered
        await daemon.start()
        result = await daemon.submit(make_request("lost", "s"))
        assert (
            result["status"] == "COMPLETED"
            and result["daemon_epoch"] == 2
            and opened == 2
        )
        await daemon.shutdown()

    run(scenario())


def test_duplicate_terminal_request_replays_without_second_effect():
    async def scenario():
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            return {"ok": True}

        daemon = ResidentFastDaemon(handler)
        await daemon.start()
        request = make_request("same", "s")
        first = await daemon.submit(request)
        second = await daemon.submit(request)
        assert first["receipt_digest"] == second["receipt_digest"]
        assert second["replay"] and calls == 1
        await daemon.shutdown()

    run(scenario())


def test_protocol_rejects_offsets_and_exposes_backend_health():
    async def scenario():
        daemon = ResidentFastDaemon(lambda request: asyncio.sleep(0, result={}))
        await daemon.start()
        with pytest.raises(DaemonError, match="protocol_exposes_offset"):
            await daemon.submit(make_request("r", "s", payload={"offset": 7}))
        health = daemon.health()
        assert health["backend"] == "python"
        assert health["rust_null_reason"] == "RUST_UNAVAILABLE"
        assert health["local_llm"] is False
        await daemon.shutdown()

    run(scenario())
