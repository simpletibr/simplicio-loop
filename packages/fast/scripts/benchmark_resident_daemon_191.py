#!/usr/bin/env python3
import asyncio
import json
import resource
import statistics
import time

from simplicio_fast.resident_daemon import ResidentFastDaemon, make_request


async def measure(slots: int, repeats: int = 10):
    samples = []
    opened = 0

    async def opener(generation):
        nonlocal opened
        opened += 1
        await asyncio.sleep(0.001)
        return generation

    async def handler(request):
        await asyncio.sleep(0)
        return {"slot": request.slot_id}

    daemon = ResidentFastDaemon(
        handler, max_inflight=5, queue_capacity=max(20, slots), generation_opener=opener
    )
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for repeat in range(repeats):
        started = time.perf_counter_ns()
        await daemon.start()
        await asyncio.gather(
            *(
                daemon.submit(make_request(f"{repeat}-{i}", f"s{i}"))
                for i in range(slots)
            )
        )
        samples.append(time.perf_counter_ns() - started)
    await daemon.shutdown()
    ordered = sorted(samples)
    return {
        "slots": slots,
        "repetitions": repeats,
        "raw_ns": samples,
        "p50_ns": statistics.median(samples),
        "p95_ns": ordered[int(0.95 * (len(ordered) - 1))],
        "generation_opens": opened,
        "rss_kib_delta": max(
            0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before_rss
        ),
    }


async def main():
    result = {
        "schema": "simplicio.fast-daemon-benchmark/v1",
        "classification": "MEASURED_LOCAL",
        "lanes": [await measure(n) for n in (1, 5, 20)],
        "tokens": None,
        "tokens_null_reason": "NO_LLM_OR_PROVIDER_USED",
        "local_llm": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
