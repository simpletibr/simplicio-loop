# Canonical-reuse benchmark (issue #269, extended by issue #236 epic closure)

Reproducible N-worktree benchmark comparing the full remap pipeline against
the canonical-reuse opt-in path. Script:
[`scripts/canonical_reuse_benchmark.py`](../scripts/canonical_reuse_benchmark.py).
Raw JSON from the last real run: [`docs/evidence/canonical-reuse-benchmark.json`](evidence/canonical-reuse-benchmark.json)
(schema `simplicio.canonical-reuse-benchmark/v2`).

```bash
python3 scripts/canonical_reuse_benchmark.py --worktrees 5 --files 300 --update-doc
```

## What schema v2 adds over v1

Epic #236's unmet acceptance criterion was: *"Benchmarks demonstram redução
de CPU, RSS, I/O e tempo para N worktrees"* — v1 (merged with #269) measured
wall time and the *main process's own* CPU (`time.process_time()`) and peak
RSS (`resource.getrusage(RUSAGE_SELF)`), but never the CPU/RSS spent in the
real `git` subprocesses the pipeline shells out to
(`simplicio_mapper/mapper/canonical_builder.py::_run_git`), and never
collected any I/O signal at all.

v2 adds, per run, using **only the stdlib `resource` module** (no new
dependency — `psutil` was considered and intentionally not added; this repo
requires asking before adding any dependency):

| Field | Source | What it is |
|---|---|---|
| `cpu_s_children` | `resource.getrusage(RUSAGE_CHILDREN)` delta (`ru_utime + ru_stime`) | CPU time spent in child processes (the `git` subprocess calls) during the call |
| `peak_rss_kb_children` | `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` | Cumulative peak RSS of child processes (KB) |
| `io_in_blocks` / `io_out_blocks` | `resource.getrusage(RUSAGE_SELF)` `ru_inblock`/`ru_oublock` delta | Block I/O operation counts (not bytes) for the main process |
| `io_in_blocks_children` / `io_out_blocks_children` | Same, `RUSAGE_CHILDREN` | Same, for child processes |

The pre-existing v1 fields (`wall_s`, `cpu_s`, `peak_rss_kb`,
`files_mapped`) are kept unchanged — this is an additive bump, not a
breaking one, because every v1 consumer (the script's own test suite, any
future doc/analysis) still finds the same fields at the same meaning; only
the `schema` string and the new fields are new.

**Honest limits of the I/O number**: `ru_inblock`/`ru_oublock` count block
I/O *operations*, not bytes, and on some kernels/filesystems a read fully
served from page cache does not increment it. This is a real, stdlib,
kernel-reported counter — not a fabricated estimate — but it is coarser than
a full strace-level trace. No syscall counts or page-cache hit/miss ratios
are collected.

## Real measurements (this run, this machine, Linux container)

Two scales were run for real (raw JSON of the second is what
`docs/evidence/canonical-reuse-benchmark.json` currently holds after the last
`--update-doc` run):

### 4 worktrees x 40 files/worktree

| | full remap (total) | canonical-reuse (total) |
|---|---|---|
| Wall time | 0.2098s | 0.3356s |
| Speedup ratio (wall) | 1.0 (baseline) | **0.625x — slower** |

At this small scale, canonical-reuse is *slower* in wall time: the first
worktree in the reuse group pays the one-time canonical-build cost (detached
checkout + full pipeline), and with only 40 files that fixed cost is not
amortized away by the other 3 worktrees' cache hits. This is a real,
unedited measurement, not an error — see the "when this helps vs. doesn't"
note below.

### 5 worktrees x 300 files/worktree

| | full remap (total) | canonical-reuse (total) |
|---|---|---|
| Wall time | 1.4701s | 1.0476s |
| Speedup ratio (wall) | 1.0 (baseline) | **1.403x faster** |
| CPU (self, sum across runs) | 1.1056s | 0.5026s (**-54.6%**) |
| CPU (children, sum across runs) | 0.0644s | 0.4290s (higher — canonical build's `git ls-tree`/`worktree add` cost concentrated in worktree 0) |
| Peak RSS (self, max across runs) | 29624 KB | 31984 KB (comparable) |
| Peak RSS (children, max across runs) | 43324 KB | 43324 KB (identical — same `git` subprocess ceiling either way) |
| I/O out-blocks (self, sum across runs) | 75176 | 27752 (**-63.1%**) |

At this larger, more realistic scale, canonical-reuse shows a real
reduction in wall time, main-process CPU, and I/O out-blocks — the 4
worktrees after the first one hit the cached canonical manifest instead of
re-walking and re-parsing 300 files each. Child-process CPU is higher in
absolute terms for canonical-reuse because the one-time canonical build
issues more `git` subprocess calls than a single `full` run does, but that
cost is paid once and amortized across N worktrees, which is exactly the
tradeoff this issue's acceptance criterion is about.

### Reading these two results together

Both runs are genuine, unedited measurements from the same script, same
container, same day. They do not agree on whether canonical-reuse "wins" —
and that is the honest finding: the tradeoff is a function of `(files per
worktree, worktrees)`, not a fixed constant. At small fixture sizes the fixed
canonical-build cost is not amortized; at larger, more realistic ones it is.
This benchmark's fixture sizes are deliberately small enough to run in
seconds (documented in the script's own module docstring) — it demonstrates
the *shape* of the tradeoff on this machine, not a universal number that
holds at every repo size.

## Platform coverage — what this benchmark does NOT demonstrate

This benchmark (v1 and v2 alike) has only ever been run inside a **Linux
container**, in every session that has worked on epic #236 to date. macOS
and Windows were never available in any of those sessions. Epic #236's
platform acceptance criterion ("Linux, macOS e Windows") is **not met** by
this work and cannot be met from here — there is no simulated or faked
substitute for it in this repository. See
[`docs/features/canonical-map-lifecycle.md`](features/canonical-map-lifecycle.md#limitações-por-plataforma)
for the explicit, standing note on this gap. Closing it requires a human or
an agent session with actual access to a macOS and a Windows machine/runner
to run `scripts/canonical_reuse_benchmark.py` (and the rest of the
`canonical status/build/verify/gc` surface) there for real.
