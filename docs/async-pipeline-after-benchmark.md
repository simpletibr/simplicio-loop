# Async mapping pipeline -- after benchmark (issue #235, ADR-009 plan step 10)

Measured: 2026-07-18T00:02:30.170006+00:00 against the CURRENT `simplicio_mapper.mapper.build_artifacts` -- now a thin `asyncio.run(build_artifacts_async(...))` adapter over the bounded-concurrency `AsyncMappingPipeline` (ADR-009 plan steps 4-8, PR #260). This is the **after** number for issue #235; compare against `docs/async-pipeline-baseline-benchmark.md` (the **before** number, measured on the pre-async, pre-O(n^2)-fix revision).

**Read this before the table**: two changes landed between before and after, not one -- this async pipeline AND PR #255's unrelated fix for the O(n^2) `_candidate_import_targets` fallback scan in `graph.py` (ADR-009's own profiling identified that quadratic scan, not blocking I/O, as the dominant cost at scale: 93s of a 120s profiled run on the 1650-file tree). Both fixes are already merged into the same `build_artifacts()` on this revision, so this report cannot and does not isolate the async pipeline's own marginal contribution from the O(n^2) fix's contribution -- it reports the combined, real, current behavior of the production entry point every `index`/`map`/`scan` command calls.

Python: `3.14.5`. Tool: `scripts/async_pipeline_after_benchmark.py`. Cold = fresh empty disk cache; warm = same output dir re-run immediately after (disk-cache hit path). Same synthetic-tree generator, seed, and sizes as the baseline benchmark, so rows are directly comparable.

| Size | Files | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm files/s | Warm/Cold speedup |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| small | 4 | 0.1288 / 0.1325 | 0.0156 | 33.69 | 31.06 | 0.0764 / 0.0793 | 52.35 | 1.69x |
| medium | 220 | 1.6082 / 2.258 | 0.8281 | 40.79 | 136.8 | 0.3426 / 0.4764 | 642.23 | 4.69x |
| large | 1650 | 13.8028 / 14.4471 | 9.1875 | 53.93 | 119.54 | 5.2692 / 5.4196 | 313.14 | 2.62x |

## Before vs. after (cold wall time)

| Size | Before cold wall p50 (s) | After cold wall p50 (s) | Speedup |
|---|---:|---:|---:|
| small | 0.0682 | 0.1288 | 0.53x |
| medium | 1.0738 | 1.6082 | 0.67x |
| large | 25.7289 | 13.8028 | 1.86x |

Honest caveat (see the framing note above the first table): the before/after delta above bundles the async pipeline together with PR #255's O(n^2) algorithmic fix. For the small tree (4 files, effectively no I/O-wait or quadratic-scan cost to hide), expect the speedup to be modest or even a wash, matching ADR-009's own honest prediction in its "Negativas" section -- a large speedup here would be the surprising result needing explanation, not the expected one. For medium/large trees, most of any large speedup should be attributed to the O(n^2) fix rather than asserted as the async pipeline's own doing, per the framing note above.
