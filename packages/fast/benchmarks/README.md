# Benchmarks

This directory is intentionally separate from the `simplicio_fast` runtime package.

- `run.py` creates temporary synthetic projects with 1k, 10k and 100k symbols.
- It does not alter the measured repository.
- It is not imported by the CLI or library.
- Generated results are ignored by Git.
- Recorded numbers describe one environment and are not product guarantees.

Run (the default is ten repetitions per workload):

```bash
python benchmarks/run.py
```

For a shorter local smoke run, retain the required ten repetitions and select one workload:

```bash
python benchmarks/run.py --sizes 1000 --repetitions 10
```

For comparisons, use the same machine, Python version, repository, query and cache policy. Run at
least ten repetitions and retain raw results for wall time, CPU time, peak RSS, page faults and
incremental reuse. Shared-base overlay receipts always cover the deterministic 1/20/100 slot matrix.
Page-fault fields are `null` when the host does not expose them.
Each wall-time receipt includes p50 (`median`), p95 and p99 values alongside the raw samples;
percentiles are computed deterministically from the recorded repetition set.

Every comparison receipt also carries `simplicio.fast.environment/v1` raw identity fields (Python implementation/version, platform, machine, processor, executable and CPU count). The gate rejects missing or schema-drifted environment fields before comparing metrics; unavailable hardware fields remain explicit `null`.
The latest Fast-vs-baseline receipt is recorded in
[`reports/fast-vs-baseline.md`](reports/fast-vs-baseline.md), with raw JSON in
[`reports/fast-vs-baseline-20260727.json`](reports/fast-vs-baseline-20260727.json). It is a
bounded local fixture; Full/Loop cells remain explicitly blocked when cross-repository runtime
integration is unavailable.

Run the reproducible regression gate after generating a candidate receipt:

```bash
python scripts/perf_gate.py \
  --baseline benchmarks/reports/fast-vs-baseline-20260727.json \
  --candidate path/to/candidate.json \
  --json-out perf-gate.json
```

The gate requires ten repetitions, rejects workload and environment drift (baseline and candidate
must carry the same non-empty environment metadata), treats unavailable metrics as `inconclusive`,
and returns non-zero for `regressed` or `inconclusive`. It never converts a blocked Full/Loop cell
or missing provider telemetry into a passing zero.

`environment.peak_rss_kib` is normalized to KiB. POSIX uses the standard-library
`resource.getrusage`; Windows uses `GetProcessMemoryInfo` through `ctypes`, so no runtime
dependency is added. If the operating system cannot expose peak RSS, the benchmark still emits a
partial JSON receipt with schema `simplicio.fast.benchmark/v1`, `status: "partial"`,
`peak_rss_kib: null`, a deterministic `peak_rss_reason` code and `metrics_status: "partial"`.


## Allocation telemetry

Each generated size receipt also includes `baseline_ast_query_allocation` and
`snapshot_mmap_query_allocation` with schema `simplicio.fast.allocation-metric/v1`.
When `tracemalloc` is available, each metric records ten or more raw peak-byte samples plus
p50 (`median`), p95 and p99. Hosts without `tracemalloc` emit `status: "partial"` and an
explicit `tracemalloc_unavailable` reason; missing allocation telemetry is never treated as zero.
## User CRUD benchmark

The CRUD benchmark validates create, read, update and delete through the service and real HTTP API,
then measures Fast semantic context retrieval and incremental snapshot reuse.

| Artifact | Purpose |
|---|---|
| [Markdown report](reports/crud-benchmark.md) | Methodology, results and interpretation |
| [PDF report](reports/crud-benchmark.pdf) | Rendered two-page A4 report |
| [JSON receipt](results/crud-latest.json) | Machine-readable `simplicio.fast.crud-benchmark/v1` data |

Observed medians from 100 complete cycles:

- direct CRUD cycle: 0.536 ms;
- HTTP CRUD cycle: 3.990 ms;
- Fast `UserService` semantic context: 0.330 ms;
- one-file incremental refresh: 3.852 ms, reusing three of four files.

These operations have different boundaries. Do not present semantic-context latency as an HTTP
speedup ratio. This benchmark does not estimate LLM tokens, provider cost or complete
software-delivery savings.


## Incremental refresh benchmark

Issue #188's benchmark compares full byte/hash validation with the metadata-bound validation cache
on identical Rust corpora. The default workload has 2,400 files, changes exactly one file per
repetition, retains raw samples and reports discovery/validation/parsing/publication phase timings.

```bash
python benchmarks/incremental_refresh.py --files 2400 --repetitions 5 \
  --json-out benchmarks/reports/incremental-refresh-20260727.json
```

Recorded evidence: [Markdown report](reports/incremental-refresh-20260727.md) and [raw JSON](reports/incremental-refresh-20260727.json).

The metadata route is fail-closed: missing, corrupt, stale or snapshot-mismatched sidecars fall
back to reading and hashing normal source files. Results are local CPU/cache measurements and do
not claim LLM token savings.
