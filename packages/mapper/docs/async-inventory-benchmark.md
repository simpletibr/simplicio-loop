# Async file-inventory benchmark -- sync vs. async (issue #264)

Measured: 2026-07-18T00:10:43.678329+00:00, Python `3.14.5`, `--runs 3` on this machine. Tool: `scripts/async_inventory_benchmark.py --sizes --write`.

Compares three implementations of the file-inventory walk-and-parse step, all callable directly on this revision (unlike the full `build_artifacts` pipeline, whose pre-async sync form no longer exists as an independently callable path -- see `docs/async-pipeline-baseline-benchmark.md` for the historical, frozen full-pipeline baseline measured before the async adapter landed, and this doc's "Limitations" section below):

- `sync` -- `simplicio_mapper.mapper.parse._build_file_inventory` (the original, single-threaded loop; still present, no longer called by `build_artifacts` in production).
- `async_inventory` -- `simplicio_mapper.mapper.async_inventory.build_file_inventory_async_sync` (PR #262; standalone, proven-correct building block, not wired into any CLI command).
- `async_pipeline` -- `simplicio_mapper.mapper.async_pipeline.build_file_inventory_async` (PR #260; the implementation actually composed into `build_artifacts_async`, i.e. what every `index`/`map`/`scan` run uses today via the sync adapter in `simplicio_mapper/mapper/emit.py`).

Cold = fresh empty disk cache; warm = same cache dir re-run immediately after (disk-cache hit path).

## small (4 files, 3 run(s))

| Path | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm CPU (s) | Warm peak RSS (MB) | Warm files/s | Warm/Cold | vs sync (cold/warm) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sync` | 0.0078 / 0.0117 | 0.0 | 33.05 | 515.97 | 0.0021 / 0.0024 | 0.0 | 33.06 | 1878.9 | 3.71x | n/a (baseline) |
| `async_inventory` | 0.01 / 0.0134 | 0.0156 | 32.82 | 400.44 | 0.005 / 0.006 | 0.0 | 32.88 | 802.78 | 2.0x | 0.78x / 0.42x |
| `async_pipeline` | 0.0565 / 0.058 | 0.0156 | 33.6 | 70.76 | 0.0177 / 0.018 | 0.0156 | 32.83 | 225.9 | 3.19x | 0.14x / 0.12x |

## medium (242 files, 3 run(s))

| Path | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm CPU (s) | Warm peak RSS (MB) | Warm files/s | Warm/Cold | vs sync (cold/warm) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sync` | 0.4463 / 3.3918 | 0.1875 | 35.62 | 542.21 | 0.2065 / 0.3867 | 0.1094 | 35.48 | 1171.63 | 2.16x | n/a (baseline) |
| `async_inventory` | 0.1789 / 0.2087 | 0.1875 | 35.79 | 1352.55 | 0.0849 / 0.0884 | 0.0938 | 35.9 | 2849.96 | 2.11x | 2.49x / 2.43x |
| `async_pipeline` | 1.4421 / 2.1756 | 1.0781 | 38.84 | 167.81 | 0.217 / 0.2342 | 0.7812 | 39.19 | 1115.07 | 6.65x | 0.31x / 0.95x |

## large (1814 files, 3 run(s))

| Path | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm CPU (s) | Warm peak RSS (MB) | Warm files/s | Warm/Cold | vs sync (cold/warm) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sync` | 3.0501 / 28.1309 | 1.5938 | 46.59 | 594.73 | 1.5196 / 1.9026 | 0.7656 | 46.82 | 1193.7 | 2.01x | n/a (baseline) |
| `async_inventory` | 1.3027 / 1.6999 | 1.4375 | 47.7 | 1392.5 | 0.5648 / 0.6837 | 0.7344 | 48.72 | 3212.02 | 2.31x | 2.34x / 2.69x |
| `async_pipeline` | 9.0714 / 9.8186 | 6.4844 | 48.47 | 199.97 | 1.658 / 1.6956 | 5.875 | 49.94 | 1094.06 | 5.47x | 0.34x / 0.92x |

## Reading these numbers

- **Cache hit/miss proxy**: this script does not expose raw `diskcache` hit/miss counters, so the warm/cold wall-time ratio is used as the cache-effectiveness proxy, matching `docs/async-pipeline-baseline-benchmark.md`'s convention.
- **files/s** is `file_count / wall_median`.
- **small** uses the real committed `contracts/mapper-artifacts/v1/fixtures/python-minimal/source` fixture; **medium**/**large** use deterministically generated synthetic Python packages (seed `20260717`).
- Per ADR-009's own "Negativas" section: on a fast local disk with OS-level page caching, small trees can show a *negative* speedup for the async paths (asyncio/thread-pool scheduling overhead outweighs I/O-wait savings when there is barely any I/O-wait to hide) -- this is expected and reported honestly here, not treated as a bug or hidden.

## Limitations

- This report measures the **inventory stage only**, not the full `build_artifacts` pipeline (symbol index, call graph, architecture inventory, JSON writes are unchanged and synchronous either way -- see ADR-009's "Contexto" table).
- A true apples-to-apples **full-pipeline** sync-vs-async comparison is not reproducible on this revision: `build_artifacts` unconditionally delegates to `build_artifacts_async` now (ADR-009 plan step 8), so there is no independently callable full-pipeline sync entry point left to re-measure against. `scripts/async_pipeline_baseline_benchmark.py` refuses to run here for exactly this reason (see its own guard and issue #264's comment thread) and its committed numbers in `docs/async-pipeline-baseline-benchmark.md` remain the last real, historical, pre-async-adapter full-pipeline baseline -- frozen, not regenerated by this report.
- Sample sizes here (`--runs 3` by default) are small; wall-time p95 in particular is noisy at n=3 (see the raw JSON evidence file for exact per-run figures). Treat single-digit-percent differences between implementations as within measurement noise on this machine, not a confirmed regression/improvement.
- Numbers are machine- and OS-specific (this run: Windows, single local disk, no cross-platform parity claimed).
