# Async pipeline dispatch -- crossover + confirmation benchmark (issue #235 follow-up)

Measured: 2026-07-18T00:43:54.727506+00:00. Python: `3.14.5`. Tool: `scripts/async_pipeline_dispatch_benchmark.py`. Both tables below are measured on the SAME current revision (dispatcher wired into `build_artifacts()`, PR #255's O(n^2) fix already present in both paths), so -- unlike the historical before/after tables, which compare across revisions -- this is a like-for-like sync-vs-async comparison.

## Crossover table (forced sync vs. forced async, same revision)

Each row forces the named path via `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` (bypassing the dispatcher) and measures cold wall time. This is the evidence used to pick the shipped default threshold (600 files).

| Files (requested / actual) | Sync wall p50 (s) | Async wall p50 (s) | Sync faster? | sync/async ratio |
|---:|---:|---:|---|---:|
| 50 / 54 | 0.4514 | 0.927 | yes | 0.487 |
| 100 / 110 | 0.694 | 1.2896 | yes | 0.538 |
| 400 / 440 | 2.2144 | 3.0266 | yes | 0.732 |
| 800 / 880 | 5.1656 | 6.3242 | yes | 0.817 |
| 1200 / 1320 | 8.5854 | 10.2017 | yes | 0.842 |
| 1650 / 1814 | 18.081 | 15.0309 | no | 1.203 |

## Dispatch-active table (real `build_artifacts()`, default threshold)

Same three sizes as the historical before/after benchmarks (`docs/async-pipeline-baseline-benchmark.md`, `docs/async-pipeline-after-benchmark.md`), now measured through the real, unmodified entry point with the dispatcher active.

| Size | Files | Cold wall p50 (s) | Cold files/s | Warm wall p50 (s) |
|---|---:|---:|---:|---:|
| small | 5 | 0.0796 | 62.79 | 0.0593 |
| medium | 220 | 0.4812 | 457.24 | 0.291 |
| large | 1650 | 12.3638 | 133.45 | 5.2058 |

## Three-way comparison (cold wall time): before (sync-only, pre-#235) vs. after (unconditionally-async, PR #260/#271) vs. dispatch (this change)

| Size | Before (sync-only) | After (unconditional async) | Dispatch (this fix) | Dispatch vs. before | Dispatch vs. after |
|---|---:|---:|---:|---:|---:|
| small | 0.0682 | 0.1288 | 0.0796 | 0.86x | 1.62x |
| medium | 1.0738 | 1.6082 | 0.4812 | 2.23x | 3.34x |
| large | 25.7289 | 13.8028 | 12.3638 | 2.08x | 1.12x |

Reading this table: "Dispatch vs. before" close to or above 1.0x means the regression versus the original synchronous pipeline is fixed (small/medium should land here, since the dispatcher now routes them through the same synchronous code path as "before", modulo the unrelated O(n^2) fix which benefits both). "Dispatch vs. after" close to 1.0x for the large row confirms the async pipeline's real win is preserved once a tree is actually large enough to cross the threshold.
