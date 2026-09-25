import asyncio
import json
import time
from simplicio_fast.content_cache import ContentCache, key


async def main():
    for n in (1, 5, 20):
        c = ContentCache()
        k = key("s", 1, "q", "c", "t", "facts")

        async def compute():
            await asyncio.sleep(0)
            return b"x"

        raw = []
        for _ in range(10):
            t = time.perf_counter_ns()
            await asyncio.gather(*(c.get(k, compute, ["x"]) for _ in range(n)))
            raw.append(time.perf_counter_ns() - t)
        print(
            json.dumps(
                {
                    "schema": "simplicio.fast-cache-benchmark/v1",
                    "clients": n,
                    "raw_ns": raw,
                    "receipt": c.receipt(),
                    "local_llm": False,
                }
            )
        )


asyncio.run(main())
