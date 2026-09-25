import json
import time
from simplicio_fast.hybrid_index import HybridIndex

docs = {str(i): f"symbol {i % 10} module" for i in range(1000)}
vec = {str(i): [(i % 10) / 10, 1 - (i % 10) / 10] for i in range(1000)}
idx = HybridIndex(docs, vec)
for lane, q in (("lexical", None), ("hybrid_4bit_rerank", [0.7, 0.3])):
    raw = []
    results = None
    for _ in range(10):
        t = time.perf_counter_ns()
        results = idx.search("symbol 7", q)
        raw.append(time.perf_counter_ns() - t)
    print(
        json.dumps(
            {
                "schema": "simplicio.fast-hybrid-index-benchmark/v1",
                "lane": lane,
                "raw_ns": raw,
                "top": results[0]["id"],
                "local_llm": False,
                "tokens": None,
            }
        )
    )
