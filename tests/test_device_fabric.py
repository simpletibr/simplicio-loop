from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from simplicio_loop.device_fabric import (
    Backpressure,
    DeviceFabric,
    DeviceRequest,
    DeviceRequirement,
    DeviceStageAdapter,
    EffectUnknown,
    FakeRuntimeDeviceAuthority,
    StaleCapacity,
    TransientDeviceFailure,
    detect_litert,
    human_status,
    write_evidence,
)


DEVICES = {
    "CPU": {
        "slots": 2, "memory_bytes": 1024,
        "capabilities": ["completion", "embedding"],
        "backend": "litert-cpu",
    },
    "GPU": {
        "slots": 1, "memory_bytes": 2048,
        "capabilities": ["completion", "vision"],
        "backend": "litert-gpu",
    },
    "NPU": {
        "slots": 1, "memory_bytes": 1024,
        "capabilities": ["completion"],
        "backend": "litert-npu",
    },
}


def request(
    number=1, *, session="session-a", devices=("NPU", "GPU", "CPU"),
    fallback=("GPU", "CPU"), capability="completion", memory=64, deadline=2,
):
    return DeviceRequest(
        request_id=f"request-{number}",
        session_id=session,
        owner_id=f"host:{session}",
        idempotency_key=f"run-794:{number}",
        requirement=DeviceRequirement(
            capability, tuple(devices), tuple(fallback),
            memory_bytes=memory, deadline_seconds=deadline,
        ),
    )


async def successful(cancel):
    await asyncio.sleep(0.002)
    if cancel.is_set():
        raise asyncio.CancelledError
    return {"value": "ok"}


def run(coro):
    return asyncio.run(coro)


def test_litert_detection_is_metadata_only_and_never_starts_provider():
    available = detect_litert({"ai-edge-litert": "2.0", "litert-lm": "1.0"})
    assert available["available"] is True
    assert available["engine_distribution"] == "ai-edge-litert"
    assert available["engine_imported"] is False
    assert available["model_provider_started"] is False
    missing = detect_litert({})
    assert missing["available"] is False
    assert missing["reason_code"] == "litert_not_installed"


def test_bounded_queue_applies_backpressure():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority(DEVICES)
        fabric = DeviceFabric(runtime, queue_capacity=2, max_in_flight=1)
        first = fabric.submit(request(1), successful)
        second = fabric.submit(request(2), successful)
        with pytest.raises(Backpressure):
            fabric.submit(request(3), successful)
        await asyncio.gather(first, second)
        await fabric.close()
        assert fabric.metrics["max_queued"] == 2
        assert fabric.metrics["blocked"] == 1
    run(scenario())


def test_fallback_is_explicit_and_policy_gated():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({
            "CPU": DEVICES["CPU"],
            "GPU": DEVICES["GPU"],
        })
        fabric = DeviceFabric(runtime)
        allowed = await fabric.submit(
            request(1, devices=("NPU", "CPU"), fallback=("CPU",)), successful
        )
        denied = await fabric.submit(
            request(2, devices=("NPU", "CPU"), fallback=()), successful
        )
        await fabric.close()
        assert allowed["status"] == "succeeded"
        assert allowed["effective"]["device"] == "CPU"
        assert allowed["fallback"] == {"used": True, "policy_allowed": True}
        assert denied["status"] == "blocked"
        assert denied["reason_code"] == "fallback_denied"
    run(scenario())


def test_cancel_queued_and_running_releases_physical_lease():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": {**DEVICES["CPU"], "slots": 1}})
        fabric = DeviceFabric(runtime, max_in_flight=1)
        entered = asyncio.Event()

        async def long(cancel):
            entered.set()
            await asyncio.sleep(10)

        running = fabric.submit(
            request(1, devices=("CPU",), fallback=()), long
        )
        queued = fabric.submit(
            request(2, devices=("CPU",), fallback=()), successful
        )
        await entered.wait()
        assert await fabric.cancel("request-2", "pause") is True
        assert await fabric.cancel("request-1", "stop") is True
        queued_receipt, running_receipt = await asyncio.gather(queued, running)
        assert queued_receipt["execution_time_reason"] == "never_started"
        assert running_receipt["execution_time_reason"] == "cancelled_before_completion"
        await fabric.close()
        snapshot = await runtime.capacity_snapshot()
        assert snapshot["devices"]["CPU"]["slots_available"] == 1
        assert runtime.cancelled
    run(scenario())


def test_two_hosts_never_share_exclusive_device_slot():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"NPU": DEVICES["NPU"]})
        host_a = DeviceFabric(runtime, max_in_flight=1)
        host_b = DeviceFabric(runtime, max_in_flight=1)
        first = host_a.submit(
            request(1, session="a", devices=("NPU",), fallback=()), successful
        )
        second = host_b.submit(
            request(2, session="b", devices=("NPU",), fallback=()), successful
        )
        receipts = await asyncio.gather(first, second)
        await asyncio.gather(host_a.close(), host_b.close())
        assert all(item["status"] == "succeeded" for item in receipts)
        assert runtime.max_used["NPU"] == 1
        assert receipts[0]["lease"]["fence"] != receipts[1]["lease"]["fence"]
    run(scenario())


def test_effect_unknown_is_not_retried_without_terminal_reconciliation():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": DEVICES["CPU"]})
        fabric = DeviceFabric(runtime, max_transient_retries=3)

        async def unknown(cancel):
            raise EffectUnknown("transport disconnected after dispatch")

        receipt = await fabric.submit(
            request(1, devices=("CPU",), fallback=()), unknown
        )
        await fabric.close()
        assert receipt["status"] == "blocked"
        assert receipt["reason_code"] == "effect_unknown"
        assert runtime.execution_calls["run-794:1"] == 1
    run(scenario())


def test_duplicate_causal_identity_never_executes_twice():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": {**DEVICES["CPU"], "slots": 2}})
        fabric = DeviceFabric(runtime, max_in_flight=2)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def held(cancel):
            entered.set()
            await release.wait()
            return {"ok": True}

        first_request = request(1, devices=("CPU",), fallback=())
        duplicate = DeviceRequest(
            "request-duplicate", "session-b", "host:b",
            first_request.idempotency_key, first_request.requirement,
        )
        first = fabric.submit(first_request, held)
        await entered.wait()
        second = fabric.submit(duplicate, successful)
        duplicate_receipt = await second
        release.set()
        first_receipt = await first
        await fabric.close()
        assert first_receipt["status"] == "succeeded"
        assert duplicate_receipt["reason_code"] == "effect_unknown"
        assert runtime.execution_calls[first_request.idempotency_key] == 1
    run(scenario())


def test_only_classified_transient_failure_retries_same_causal_identity():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": DEVICES["CPU"]})
        fabric = DeviceFabric(runtime, max_transient_retries=1)
        calls = 0

        async def flaky(cancel):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TransientDeviceFailure("temporary")
            return {"ok": True}

        receipt = await fabric.submit(
            request(1, devices=("CPU",), fallback=()), flaky
        )
        await fabric.close()
        assert receipt["status"] == "succeeded"
        assert receipt["attempts"] == 2
        assert receipt["idempotency_key"] == "run-794:1"
        assert runtime.execution_calls["run-794:1"] == 2
    run(scenario())


def test_timeout_and_released_stale_lease_fail_closed():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": DEVICES["CPU"]})
        fabric = DeviceFabric(runtime)

        async def too_slow(cancel):
            await asyncio.sleep(1)

        timed = await fabric.submit(
            request(1, devices=("CPU",), fallback=(), deadline=0.01), too_slow
        )
        assert timed["status"] == "blocked"
        assert timed["reason_code"] == "TimeoutError"
        await fabric.close()

        direct = request(2, devices=("CPU",), fallback=())
        snapshot = await runtime.capacity_snapshot()
        lease = await runtime.acquire(direct, "CPU", snapshot["revision"])
        await runtime.release(lease, "test")
        with pytest.raises(StaleCapacity):
            await runtime.execute(lease, successful, asyncio.Event())
    run(scenario())


def test_pressure_reduces_admission_wave_before_memory_oom():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({
            "CPU": {
                "slots": 4, "memory_bytes": 100,
                "capabilities": ["completion"], "backend": "litert-cpu",
            }
        })
        fabric = DeviceFabric(runtime, max_in_flight=4)
        futures = [
            fabric.submit(
                request(
                    number, devices=("CPU",), fallback=(), memory=45,
                ),
                successful,
            )
            for number in range(1, 5)
        ]
        receipts = await asyncio.gather(*futures)
        await fabric.close()
        assert all(row["status"] == "succeeded" for row in receipts)
        assert runtime.max_used["CPU"] <= 2
        assert fabric.metrics["pressure_events"] >= 1
    run(scenario())


def test_stale_capacity_and_litert_absence_fail_closed_but_other_work_continues():
    class StaleRuntime(FakeRuntimeDeviceAuthority):
        async def capacity_snapshot(self):
            row = dict(await super().capacity_snapshot())
            row["observed_at"] = -100.0
            return row

    async def scenario():
        stale_runtime = StaleRuntime({"CPU": DEVICES["CPU"]}, clock=lambda: 10.0)
        stale = DeviceFabric(
            stale_runtime, clock=lambda: 10.0, capacity_ttl_seconds=1
        )
        receipt = await stale.submit(
            request(1, devices=("CPU",), fallback=()), successful
        )
        await stale.close()
        independent_lane = {"status": "passed", "requires_litert": False}
        assert receipt["reason_code"] == "stale_capacity_snapshot"
        assert independent_lane["status"] == "passed"
        assert stale.status()["model_provider_started"] is False
    run(scenario())


def test_litert_unavailable_is_degraded_and_does_not_start_provider():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority(
            {"CPU": DEVICES["CPU"]}, litert_available=False
        )
        fabric = DeviceFabric(runtime)
        receipt = await fabric.submit(
            request(1, devices=("CPU",), fallback=(), deadline=0.01), successful
        )
        await fabric.close()
        assert receipt["status"] == "blocked"
        assert receipt["reason_code"] == "capacity_unavailable"
        assert receipt["model_provider_started"] is False
        assert runtime.execution_calls == {}
    run(scenario())


@pytest.mark.parametrize("count", [1, 6, 64])
def test_load_is_bounded_and_lossless(count):
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority(DEVICES)
        fabric = DeviceFabric(runtime, queue_capacity=64, max_in_flight=6)
        futures = [
            fabric.submit(
                request(
                    number, session=f"session-{number % 4}",
                    devices=("NPU", "GPU", "CPU"), fallback=("GPU", "CPU"),
                ),
                successful,
            )
            for number in range(count)
        ]
        receipts = await asyncio.gather(*futures)
        status = fabric.status()
        await fabric.close()
        assert len(receipts) == count
        assert all(item["status"] == "succeeded" for item in receipts)
        assert all(item["queue_time_ns"] >= 0 for item in receipts)
        assert all(item["execution_time_ns"] > 0 for item in receipts)
        assert status["metrics"]["max_in_flight"] <= 6
        assert runtime.max_used["CPU"] <= 2
        assert runtime.max_used["GPU"] <= 1
        assert runtime.max_used["NPU"] <= 1
    run(scenario())


def test_round_robin_fairness_prevents_large_session_starvation():
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": {**DEVICES["CPU"], "slots": 1}})
        fabric = DeviceFabric(runtime, max_in_flight=1)
        order = []

        def operation(name):
            async def execute(cancel):
                order.append(name)
                await asyncio.sleep(0.001)
                return name
            return execute

        futures = [
            fabric.submit(
                request(number, session="bulk", devices=("CPU",), fallback=()),
                operation(f"bulk-{number}"),
            )
            for number in range(1, 6)
        ]
        futures.append(fabric.submit(
            request(20, session="interactive", devices=("CPU",), fallback=()),
            operation("interactive"),
        ))
        await asyncio.gather(*futures)
        await fabric.close()
        assert order.index("interactive") <= 1
    run(scenario())


def test_receipt_evidence_and_human_json_status(tmp_path):
    async def scenario():
        runtime = FakeRuntimeDeviceAuthority({"CPU": DEVICES["CPU"]})
        fabric = DeviceFabric(runtime)
        receipt = await fabric.submit(
            request(1, devices=("CPU",), fallback=()), successful
        )
        status = fabric.status()
        path = write_evidence(tmp_path, receipt)
        persisted = json.loads(path.read_text())
        assert persisted["receipt_hash"] == receipt["receipt_hash"]
        assert "queued=" in human_status(status)
        tampered = dict(receipt, status="forged")
        with pytest.raises(ValueError, match="hash mismatch"):
            write_evidence(tmp_path, tampered)
        await fabric.close()
    run(scenario())


def test_checked_in_benchmark_receipt_is_measured_bounded_and_model_free():
    path = Path(__file__).parent / "fixtures" / "device_fabric_benchmark_794.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("receipt_hash")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert declared == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert payload["classification"] == "MEASURED_LOCAL"
    assert payload["local_llm"] is False
    assert [row["tasks"] for row in payload["rows"]] == [1, 6, 64]
    assert all(row["lost"] == 0 for row in payload["rows"])
    assert payload["rows"][-1]["max_physical"] == {"CPU": 2, "GPU": 1, "NPU": 1}
    assert payload["rows"][-1]["fairness_first_window_sessions"] == 4


def test_checked_in_two_host_e2e_is_hash_bound_and_releases_lease():
    path = Path(__file__).parent / "fixtures" / "device_fabric_e2e_794.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("receipt_hash")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert declared == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert payload["classification"] == "MEASURED_LOCAL"
    assert payload["local_llm"] is False
    assert payload["model_provider_started"] is False
    assert len(payload["receipts"]) == 2
    assert all(receipt["status"] == "pass" for receipt in payload["receipts"])
    assert all(
        receipt["device_receipt"]["fallback"]["used"]
        for receipt in payload["receipts"]
    )
    assert {
        receipt["stage_instance_id"] for receipt in payload["receipts"]
    } == {"validating@host-a", "validating@host-b"}
    assert payload["physical_max_used"] == {"CPU": 1}
    assert payload["physical_slots_available_after"] == 1
    assert payload["runtime_execution_calls"] == {"e2e:host-a": 1, "e2e:host-b": 1}
