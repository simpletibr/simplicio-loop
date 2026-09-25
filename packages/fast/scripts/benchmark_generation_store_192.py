import json
import time
from simplicio_fast.generation_store import GenerationStore

for n in (1, 5, 20):
    samples = []
    for _ in range(10):
        s = GenerationStore(".")
        t = time.perf_counter_ns()
        g = s.create("r", "c", "x", "p", {"x": b"x" * 4096})
        for i in range(n):
            s.pin(g.id, i, f"f{i}")
            s.write(g.id, str(i), f"f{i}", "x", b"y")
            s.read(g.id, str(i), f"f{i}", "x")
        samples.append(time.perf_counter_ns() - t)
    print(
        json.dumps(
            {
                "schema": "simplicio.fast-generation-benchmark/v1",
                "slots": n,
                "raw_ns": samples,
                "local_llm": False,
            }
        )
    )
