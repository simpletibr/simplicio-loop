# Async mapping pipeline -- baseline benchmark (issue #235)

Measured: 2026-07-17T20:02:21.877293+00:00 against the current *synchronous* `simplicio_mapper.mapper.build_artifacts` pipeline -- this is the **before** number for the `AsyncMappingPipeline` epic (issue #235, plan steps 1-2). No production code changed for this measurement.

Python: `3.14.5`. Tool: `scripts/async_pipeline_baseline_benchmark.py`. Cold = fresh empty disk cache; warm = same output dir re-run immediately after (disk-cache hit path).

| Size | Files | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm files/s | Warm/Cold speedup |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| small | 4 | 0.0682 / 0.1014 | 0.0156 | 29.01 | 58.64 | 0.0604 / 0.065 | 66.19 | 1.13x |
| medium | 220 | 1.0738 / 5.1639 | 0.9062 | 31.98 | 204.87 | 0.8272 / 0.9943 | 265.97 | 1.3x |
| large | 1650 | 25.7289 / 49.4265 | 23.7344 | 45.79 | 64.13 | 23.0224 / 23.7872 | 71.67 | 1.12x |

## Reading these numbers

- **Cold** exercises the full sequential pipeline: `os.walk` discovery, per-file blocking `open()` + regex parse (`_cached_parse_file`), one `diskcache` miss+set per file, then a single-threaded write of 5 JSON artifacts.
- **Warm** re-runs against the same `.simplicio/cache` dir, so every file should hit `FileProcessingCache.get_processed_file` instead of re-parsing -- the warm/cold ratio is the current cache's real speedup, which any async rewrite must not regress.
- **files/s** is `file_count / wall_median`; this is the number a future `AsyncMappingPipeline` (bounded concurrency + `asyncio.to_thread` for the blocking reads) is expected to raise for medium/large trees, where I/O-wait dominates.
- The **small** row uses the real committed `contracts/mapper-artifacts/v1/fixtures/python-minimal/source` fixture (4 files) so the numbers stay anchored to a real, reviewable input, not only synthetic data. Medium/large rows use deterministically generated synthetic Python packages (seed `20260717`) so file counts are exact and reproducible without committing large trees to the repo.

## Follow-up (not done here)

This script only *measures* the current pipeline (issue #235 plan steps 1-2). See `.specs/architecture/ADR-008-async-mapping-pipeline.md` for the proposed `AsyncMappingPipeline` design and the remaining plan steps (3-10), tracked as follow-up work against issue #235.
