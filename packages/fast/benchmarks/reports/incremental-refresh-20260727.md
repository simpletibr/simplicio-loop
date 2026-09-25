# Incremental refresh benchmark — issue #188

- Schema: `simplicio.fast.incremental-refresh-benchmark/v1`
- Status: `pass`
- Workload: 2400 Rust files, exactly one changed file, 5 repetitions
- Full byte/hash validation median: 418.040 ms
- Metadata validation median: 141.326 ms
- Measured speedup: 2.958x

Median candidate phase timings:

| Phase | Median ms |
|---|---:|
| Previous snapshot load | 15.260 |
| Discovery | 40.322 |
| Unchanged validation | 18.799 |
| Parsing | 0.215 |
| Publication | 37.896 |

The raw five-run samples and environment identity are retained in
[`incremental-refresh-20260727.json`](incremental-refresh-20260727.json).
This is a local synthetic Rust corpus measurement; it does not report LLM/provider token usage.
Missing, corrupt, stale or snapshot-mismatched validation caches fall back to byte hashing.
