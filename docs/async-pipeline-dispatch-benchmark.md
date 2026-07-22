# Default-async pipeline -- local profile comparison (issue #325)

Measured: 2026-07-22T18:28:04.294814+00:00. Python: `3.12.13`. Tool: `scripts/async_pipeline_dispatch_benchmark.py`. Both tables below are measured on the SAME current revision (dispatcher wired into `build_artifacts()`, PR #255's O(n^2) fix already present in both paths), so -- unlike the historical before/after tables, which compare across revisions -- this is a like-for-like sync-vs-async comparison.

Command: `python scripts/async_pipeline_dispatch_benchmark.py --write --runs 1`. Samples per profile/size: 1. Results are local wall-clock measurements; compare profiles on the same host and revision rather than treating them as portable performance guarantees.

## Crossover table (forced sync vs. forced async, same revision)

Each row forces the named path via `SIMPLICIO_MAPPER_EXECUTION_PROFILE` and measures cold wall time. The threshold is retained as receipt/calibration metadata (600 files), but `auto` selects async at every size.

| Files (requested / actual) | Sync wall p50 (s) | Async wall p50 (s) | Sync faster? | sync/async ratio |
|---:|---:|---:|---|---:|
| 50 / 54 | 0.1598 | 0.2042 | yes | 0.783 |
| 100 / 110 | 0.1781 | 1.066 | yes | 0.167 |
| 400 / 440 | 0.8729 | 1.6614 | yes | 0.525 |
| 800 / 880 | 2.5612 | 4.2823 | yes | 0.598 |
| 1200 / 1320 | 4.2995 | 6.2788 | yes | 0.685 |
| 1650 / 1814 | 7.4978 | 10.6245 | yes | 0.706 |

## Auto-active table (real `build_artifacts()`, default profile)

Same three sizes as the historical before/after benchmarks (`docs/async-pipeline-baseline-benchmark.md`, `docs/async-pipeline-after-benchmark.md`), now measured through the real entry point with no explicit execution profile.

| Size | Files | Selected profile | Cold wall p50 (s) | Cold files/s | Warm wall p50 (s) |
|---|---:|---|---:|---:|---:|
| small | 4 | async | 0.0687 | 58.24 | 0.0422 |
| medium | 220 | async | 0.7646 | 287.73 | 0.719 |
| large | 1650 | async | 9.0983 | 181.35 | 8.6816 |

## Three-way comparison (cold wall time): before (sync-only, pre-#235) vs. after (unconditionally-async, PR #260/#271) vs. auto/default-async (this change)

| Size | Before (sync-only) | After (unconditional async) | Auto/default async | Auto vs. before | Auto vs. after |
|---|---:|---:|---:|---:|---:|
| small | 0.0682 | 0.1288 | 0.0687 | 0.99x | 1.87x |
| medium | 1.0738 | 1.6082 | 0.7646 | 1.40x | 2.10x |
| large | 25.7289 | 13.8028 | 9.0983 | 2.83x | 1.52x |

Historical rows were recorded on earlier revisions and are context only. The crossover table above is the valid same-revision profile comparison; the auto table proves the production entry point selects async at every size.
