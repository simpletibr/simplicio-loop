import asyncio
import hashlib
import json
import time
from simplicio_fast.semantic_pager import SemanticPager


async def main():
    for n in (1, 5, 20):
        raw = []
        for _ in range(10):
            p = SemanticPager(4096, 4096)
            data = b"x" * 128
            d = hashlib.sha256(data).hexdigest()
            t = time.perf_counter_ns()
            await asyncio.gather(
                *(
                    p.page(str(i), str(i), d, lambda: asyncio.sleep(0, result=data))
                    for i in range(n)
                )
            )
            raw.append(time.perf_counter_ns() - t)
        print(
            json.dumps(
                {
                    "schema": "simplicio.fast-pager-benchmark/v1",
                    "pages": n,
                    "raw_ns": raw,
                    "local_llm": False,
                    "tokens": None,
                }
            )
        )


asyncio.run(main())
