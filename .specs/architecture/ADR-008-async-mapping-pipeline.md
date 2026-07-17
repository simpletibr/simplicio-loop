# ADR-008: Async mapping pipeline with bounded concurrency (`AsyncMappingPipeline`)

> Addresses https://github.com/wesleysimplicio/simplicio-mapper/issues/235
> ("[Performance] Arquitetar pipeline assíncrono e concorrência limitada
> para mapeamento Python"). This ADR covers the **design** (plan steps 3-9
> of the issue); it does not implement the pipeline. See "Plano de adoção"
> below for what is done vs. deferred.

---

## Status

`Proposto`

---

## Data

2026-07-17

---

## Autores

- wesleysimplicio
- Claude (claude-sonnet-5)

---

## Contexto

`simplicio_mapper.mapper.build_artifacts` (`simplicio_mapper/mapper/emit.py`)
is the core of every `index`/`map`/`scan` deep pass (see ADR-003 for the
two-tier fast/deep split — this ADR is entirely about the *deep* lane).
Today it runs fully synchronously, single-threaded, single-process:

1. `_git_status_map` — one blocking `subprocess.run(["git", "status", ...])`
   (`simplicio_mapper/mapper/parse.py:218`).
2. `_build_file_inventory` — a plain `for` loop over `_collect_text_files`
   (`os.walk`, `parse.py:249`) that, per file, does a blocking `open()` read
   (`_read_safe`, `parse.py:148`), CPU-bound regex parsing
   (`_parse_imports`/`_parse_symbols`), and one `diskcache` get+set through
   `FileProcessingCache` (`simplicio_mapper/cache.py`).
3. `_build_symbol_index`, `_build_call_graph`, `_build_architecture_inventory`
   (`simplicio_mapper/mapper/graph.py`) — CPU-bound passes over the file list
   that also re-open file content via the shared `contents` dict cache.
4. `_write_json_stable` (`emit.py:213`) — five sequential atomic
   (write-tmp + `os.replace`) JSON writes, single writer, no concurrency at
   all today.

Just wrapping this in `asyncio`/`uvloop` without separating I/O from CPU
work would not help — issue #235's own framing is correct: parsing is
CPU-bound (`re.compile`/`re.finditer` over each file's text), the git call
and file reads are I/O-bound, and the five final writes are the one place
that must stay a single serialized writer to avoid interleaved/corrupt
`.simplicio/*.json`.

### Baseline measurement (issue #235 plan step 1)

`scripts/async_pipeline_baseline_benchmark.py` (added in this same
Phase-0 PR) measures the current synchronous pipeline end-to-end via
`build_artifacts()`, cold (empty disk cache) and warm (same cache dir
re-run), against the real committed
`contracts/mapper-artifacts/v1/fixtures/python-minimal/source` fixture (4
files, "small") and two synthetic deterministic Python trees ("medium" =
220 files, "large" = 1650 files). Numbers measured on this machine
(Python 3.14.5, Windows, `--runs 3`), see
`docs/async-pipeline-baseline-benchmark.md` /
`docs/evidence/async-pipeline-baseline-benchmark.json` for the full,
regenerable report:

| Size | Files | Cold wall p50 (s) | Cold files/s | Warm wall p50 (s) | Warm files/s | Warm/Cold speedup |
|---|---:|---:|---:|---:|---:|---:|
| small | 4 | 0.068 | 58.6 | 0.060 | 66.2 | 1.13x |
| medium | 220 | 1.07 | 204.9 | 0.83 | 266.0 | 1.30x |
| large | 1650 | 25.7 | 64.1 | 23.0 | 71.7 | 1.12x |

The large-tree run is disproportionately slow relative to file count
(1650 files is 7.5x the medium tree's 220, but cold wall time is ~24x
higher, and files/s *drops* instead of holding steady) -- a clear signal
of superlinear behavior, not just "more files takes proportionally
longer." This matters for scoping the async rewrite honestly: a naive
"wrap the existing loop in `asyncio.gather` with a semaphore" would not
fix a step that is already algorithmically quadratic.

### I/O-bound vs CPU-bound vs write-critical inventory (issue #235 plan step 2)

To find out *what* dominates at scale (not guess), this PR profiled the
large-tree run with `cProfile` (`build_artifacts` against the same
1650-file synthetic tree used above, one-off local run, not committed as
a script since it is a diagnostic aid, not a regression gate):

```
102872131 function calls in 119.956s (unbounded/no-limit debug build, single run)
  93.413s  cumulative  _build_call_graph                  (graph.py:341)
  79.709s  cumulative  _candidate_import_targets           (graph.py:280)  -- 7,650 calls
  58.821s  cumulative  _strip_known_ext                    (graph.py:276)  -- 12,630,150 calls
  50.052s  cumulative  posixpath.splitext                              -- called from _strip_known_ext
  25.403s  cumulative  _build_file_inventory                (parse.py:560)
  22.618s  cumulative  _content_for / _read_safe / io.open  (parse.py)     -- real blocking I/O
  12.863s  cumulative  _nearest_symbol                     (graph.py:335)  -- 15,000 calls
```

Root cause identified: `_candidate_import_targets` (`graph.py:280`), when an
import does not resolve via a direct candidate-path lookup, falls back to
a **linear scan over the full `known_paths` set** (`graph.py:307-313`) for
every unresolved import, in every file. That is `O(files * imports_per_file
* total_files)` -- quadratic in project size. On the 1650-file tree this
single function (via `_build_call_graph`) is 93s of a 120s run; the
blocking file-read I/O the issue is worried about is only ~22s.

This changes the priority order for the async work:

| Operation | Classification | Evidence | Priority for this ADR |
|---|---|---|---|
| `_git_status_map` (one `subprocess.run`) | I/O-bound, single call, cheap | `parse.py:218` | Low -- one call per run, not a bottleneck |
| `_collect_text_files` (`os.walk`) | I/O-bound (directory syscalls), currently sequential | `parse.py:249` | Medium -- fine to move off the event loop thread but not a hot spot alone |
| `_read_safe`/`_content_for` (per-file `open()` + read) | I/O-bound, blocking, one call per file | `parse.py:148-162`; 22.6s of the 120s profiled run | **High** -- the textbook `asyncio.to_thread` candidate |
| `_parse_imports`/`_parse_symbols` (regex per file) | CPU-bound, pure-Python regex | `parse.py:267-361` | Medium -- real CPU cost but linear in file size, not the top hotspot measured |
| `FileProcessingCache.get/set_processed_file` (diskcache/SQLite) | I/O-bound + shared mutable state | `cache.py:45-57`; 1.2s of the 120s profiled run at this scale | **High for correctness** -- must stay single-writer even though it is cheap today, because concurrent SQLite writers is exactly the corruption risk issue #235 calls out |
| `_candidate_import_targets` fallback scan | **CPU-bound, algorithmically quadratic** | `graph.py:280-313`; 79.7s of the 120s profiled run | **Highest priority, but not an async problem** -- no amount of `asyncio.gather`/thread-pooling fixes an `O(n^2)` algorithm; this needs an index (e.g. a `dict[str, list[path]]` keyed by stripped-suffix, built once in `O(n)`) before or independent of the async rewrite. Filed as a separate follow-up (see below), out of scope for this ADR's concurrency design. |
| `_write_json_stable` x5 (atomic tmp-write + `os.replace`) | Write-critical, must stay single-writer | `emit.py:213-243` | N/A for concurrency -- already atomic per-file; needs to stay serialized as a set (batch commit), not per-file racing |
| `_build_brown_hilbert_map` (called twice: once in `_build_file_inventory`, once again for `agent_tree` in `build_artifacts`) | CPU-bound, duplicated work | `parse.py:597`, `emit.py:196` | Low priority correctness/perf nit, noted here as a byproduct of this inventory pass, **not fixed in this PR** (out of scope, no production code changes) |

**Practical implication for this ADR's scope**: the parallelism work below
(bounded concurrency, `asyncio.to_thread` for file reads, single writer)
targets the `_build_file_inventory` walk-and-parse loop, where I/O-wait is
real and the current baseline confirms a plain sequential loop leaves
throughput on the table (medium tree: 204.9 cold files/s single-threaded;
warm/cache-hit path is only 1.1x-1.5x faster, meaning the cache is not
compensating for I/O wait either). The quadratic `_candidate_import_targets`
issue is real, `git blame`-traceable, and measured, but it is an
**algorithmic bug**, not a concurrency-architecture question -- fixing it
is filed as a separate, narrowly-scoped follow-up issue rather than folded
into this design, since mixing "make it concurrent" and "make it not
quadratic" in one change would make either fix harder to review and
harder to attribute if something regresses.

---

## Decisão

Adopt an `AsyncMappingPipeline` design for the file-inventory walk-and-parse
stage (`_build_file_inventory` and its direct blocking dependencies), with
the existing synchronous `build_artifacts`/CLI surface preserved unchanged
as the default entry point. **This ADR proposes the design; it does not
implement the pipeline in this PR** (see "Plano de adoção").

### Shape of `AsyncMappingPipeline`

- New module `simplicio_mapper/mapper/async_pipeline.py` (name reserved by
  this ADR, not created yet) exposing:
  - `async def build_file_inventory_async(cwd, pkg, status_map, cache, ...) -> list[ProjectFile]`
    — the async replacement for `_build_file_inventory`'s walk-and-parse
    loop, structurally equivalent output (same `ProjectFile` list, same
    sort order) so `build_artifacts` can call either the sync or async path
    with the rest of the pipeline (symbol index, call graph, writes)
    untouched initially.
  - `async def build_artifacts_async(cwd, meta=None, incremental=False, output_dir=".simplicio") -> dict`
    — full async pipeline, native `async def`, never nests its own
    `asyncio.run()` (issue #235 AC: "adicionar API async nativa sem
    `asyncio.run()` aninhado"). Callers already inside an event loop
    (e.g. a future async CLI, or embedding hosts) `await` it directly;
    `build_artifacts` (sync) becomes a thin adapter that does
    `asyncio.run(build_artifacts_async(...))` when no loop is already
    running, preserving today's signature and return value exactly.

- **Bounded concurrency, never unbounded.** A single `asyncio.Semaphore`
  (default cap, tunable via env var e.g. `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`,
  default suggested at `min(32, os.cpu_count() * 4)` matching common
  thread-pool sizing heuristics for I/O-bound work) gates how many files are
  in flight for read+parse at once. No `asyncio.gather` over an unbounded
  file list, no "one task per file" fire-and-forget -- every file's
  read+parse task is acquired from the semaphore before starting and
  released in a `finally`, matching issue #235 AC "Nenhuma concorrência
  ilimitada ou task órfã."

- **Blocking I/O via `asyncio.to_thread`.** `_read_safe`'s `open()` +
  `.read()` moves to `asyncio.to_thread(_read_safe, path)`; this reuses the
  default `ThreadPoolExecutor` (sized by Python's default, itself bounded)
  rather than spinning up a second concurrency primitive. CPU-bound regex
  parsing (`_parse_imports`/`_parse_symbols`) stays on the calling
  coroutine's thread (no process pool) unless a future, separately-measured
  follow-up shows real benefit -- issue #235 itself says "avaliar pool de
  processos somente para parsing comprovadamente CPU-bound," and this ADR's
  own profiling shows the current top CPU cost is the *quadratic*
  `_candidate_import_targets`, not per-file regex parsing, so a process pool
  is not justified by today's evidence.

- **`_git_status_map`'s `subprocess.run`** moves to
  `asyncio.to_thread(_git_status_map, cwd)` too (or `asyncio.create_subprocess_exec`
  if a future iteration wants non-blocking process I/O specifically) --
  it is one call per run, so this is about not blocking the event loop for
  its duration, not about throughput.

- **Single writer for cache and index, preserved.** `FileProcessingCache`
  (diskcache/SQLite) keeps a single writer: `to_thread`-wrapped
  `cache.get_processed_file`/`set_processed_file` calls are serialized
  through the semaphore-bounded worker pool but never given a second,
  independent writer path. The final `_write_json_stable` x5 sequence stays
  exactly as-is (single-threaded, after all async work has been awaited and
  results assembled) -- this is already atomic-per-file (tmp + `os.replace`)
  and issue #235 AC requires "Escritas permanecem atômicas e índices não
  corrompem sob cancelamento," which a single, un-parallelized writer
  trivially satisfies without new locking.

- **`uvloop` opt-in, Linux/macOS only, automatic when available.** A new
  optional extra `simplicio-mapper[uvloop]` (or a lazy
  `try: import uvloop / except ImportError: uvloop = None` inside the
  adapter, not a hard dependency) installs `uvloop`'s event loop policy only
  when `sys.platform != "win32"` and the import succeeds; Windows always
  uses the stdlib `asyncio` event loop (issue #235 AC: "uvloop é opcional e
  possui fallback transparente"; `ProactorEventLoop`/`SelectorEventLoop`
  differences on Windows are exactly why uvloop does not ship Windows
  wheels upstream either, so this is not a workaround, it matches upstream
  reality).

- **Timeouts, cancellation, backpressure.** Each file's bounded task wraps
  its `to_thread` call in `asyncio.wait_for(..., timeout=<per-file timeout>)`
  (default matching the existing large-file skip threshold behavior in
  spirit: fail soft, record in `degraded`, do not abort the whole run for
  one slow file). The pipeline as a whole supports cancellation
  (`asyncio.CancelledError` propagates cleanly, in-flight semaphore slots
  release via `finally`, no orphaned threads left running past the
  pipeline's own return -- `asyncio.to_thread` tasks are awaited, so
  cancellation of the parent task does not leave a dangling thread pool
  reference, though the underlying OS thread may finish its current
  syscall before the executor reclaims it, which is a known
  `to_thread`/`ThreadPoolExecutor` limitation documented here rather than
  silently assumed away).

### Sync API preservation

- `build_artifacts` (sync), `write_mapping_artifacts`, and every CLI command
  in `simplicio_mapper/cli/` keep their exact current signatures and
  synchronous call semantics. The async path is purely additive
  (`build_artifacts_async` as a new, parallel entry point); nothing existing
  is deprecated or rewired to require an event loop by default.
- The adapter direction is sync-wraps-async (`build_artifacts` calls
  `asyncio.run(build_artifacts_async(...))`), not async-wraps-sync, so the
  async pipeline is the one source of truth and the sync path never drifts
  from it silently.

---

## Consequências

### Positivas (+)

- Gives future work (this ADR's own "Plano de adoção" steps 3-9) a concrete
  target shape agreed on *before* a large diff lands, instead of reviewing
  a mega-PR that mixes design debate with implementation.
- The profiling in this ADR already redirects likely future effort away
  from a naive "async will fix it" assumption and toward the actual
  measured bottleneck (`_candidate_import_targets`), which is valuable on
  its own regardless of whether/when the async rewrite ships.
- Bounded semaphore + `to_thread` + single writer directly satisfies every
  explicit acceptance criterion in issue #235 as a design, without
  requiring speculative new dependencies (`uvloop` stays optional,
  `asyncio`/`concurrent.futures.ThreadPoolExecutor` are stdlib).

### Negativas (-)

- This ADR alone ships **no runtime behavior change** -- issue #235 is not
  closed by this PR; a reader tracking only closed issues will not see
  progress unless they read the ADR/PR/issue comment.
- The design's benefit is unverified until implemented and re-benchmarked;
  the honest, measured baseline in this PR could show the async version
  is *not* meaningfully faster for I/O-bound reads at this project's
  typical file sizes (mostly small source files, not large blobs), since
  the profiled bottleneck today is CPU-bound (`_candidate_import_targets`)
  and OS-level disk cache usually makes repeated small-file reads cheap
  already on a warm filesystem cache -- the "before" number in this PR is
  necessary but not sufficient; an "after" number is still required before
  claiming a win (tracked as a follow-up step, not asserted here).

### Neutras / observações

- The quadratic `_candidate_import_targets` finding is arguably the more
  impactful discovery of this Phase-0 pass, but is explicitly out of scope
  for this ADR (a concurrency-architecture decision) and is instead filed
  as its own follow-up so it can be reviewed, tested, and merged
  independently and quickly.

---

## Alternativas consideradas

### Alternativa A — Full rewrite in one PR (original issue framing)

- Implement all 10 plan steps (`AsyncMappingPipeline`, uvloop, timeouts,
  cancellation, docs, benchmarks) as a single change.
- Descartada: this is exactly the "unreviewable, high-risk mega-diff" this
  Phase-0 increment is designed to avoid. A change this size, touching the
  hot path of every `index`/`map`/`scan` command, with no incremental
  review checkpoint, has an outsized chance of a regression slipping
  through (the DoD's own "coverage >= 88%" and "system-level" test
  requirements are much harder to satisfy honestly for a 10-step change
  landed atomically).

### Alternativa B — Process-pool CPU parallelism instead of asyncio

- Use `multiprocessing`/`concurrent.futures.ProcessPoolExecutor` to
  parallelize file parsing across CPU cores instead of `asyncio` + threads.
- Descartada (for now): issue #235 itself asks to "avaliar pool de
  processos somente para parsing comprovadamente CPU-bound," and this
  ADR's own profiling shows the current top real cost at scale is the
  quadratic `_candidate_import_targets` (single-threaded-bound regardless
  of process count) rather than per-file regex parsing. Revisit once that
  algorithmic fix lands and a fresh profile shows regex parsing as the next
  bottleneck.

### Alternativa C — "Não fazer nada" (status quo)

- Keep the fully synchronous pipeline.
- Descartada as a permanent answer, but is the correct choice for *this*
  PR specifically: no production code changes here, by design, to keep the
  Phase-0 increment's regression risk at zero while still making real,
  reviewable progress (benchmark + inventory + design).

---

## Critério de revisão

- Revisit once `build_file_inventory_async` is implemented and a fresh run
  of `scripts/async_pipeline_baseline_benchmark.py` (or its successor)
  shows the after numbers -- if warm/cold files/s does not improve
  meaningfully for the medium/large synthetic trees, the design's core
  assumption (I/O-wait dominates at this project's typical file sizes)
  needs to be revisited before investing further.
- Revisit if the `_candidate_import_targets` quadratic-scan follow-up
  fix changes the profiled bottleneck distribution enough that a process
  pool for regex parsing becomes newly justified (Alternativa B).
- Revisit if `uvloop` upstream ships Windows support, or drops
  Linux/macOS-only status, changing the opt-in gating logic.

---

## Plano de adoção

1. ✅ Baseline benchmark committed (`scripts/async_pipeline_baseline_benchmark.py`,
   `docs/async-pipeline-baseline-benchmark.md`,
   `docs/evidence/async-pipeline-baseline-benchmark.json`) -- issue #235
   plan step 1.
2. ✅ I/O vs CPU vs write-critical inventory, with `cProfile` evidence --
   issue #235 plan step 2 (this ADR's "Contexto" section).
3. ✅ This ADR: `AsyncMappingPipeline` design, bounded concurrency,
   `to_thread` usage, single writer, `uvloop` opt-in, sync-API-preservation
   strategy -- issue #235 plan step 3 (design only).
4. ⬜ Follow-up issue: fix `_candidate_import_targets`'s `O(n^2)` fallback
   scan (`graph.py:307-313`) with an index built once in `O(n)` (e.g. a
   `dict[str, list[str]]` keyed by stripped-suffix over `known_paths`).
   Independent of the async work; should land first since it changes what
   the "after" benchmark needs to demonstrate.
5. ⬜ Implement `build_file_inventory_async` + bounded semaphore +
   `asyncio.to_thread` for reads and git status -- issue #235 plan steps
   4-5.
6. ⬜ Implement `build_artifacts_async` composing the async inventory step
   with the (still synchronous, CPU-bound) symbol-index/call-graph/write
   stages, keeping the single writer -- issue #235 plan step 6.
7. ⬜ `uvloop` optional extra + Linux/macOS auto-detection + Windows
   fallback -- issue #235 plan step 7.
8. ⬜ `build_artifacts` sync adapter wrapping `asyncio.run(build_artifacts_async(...))`,
   CLI unchanged -- issue #235 plan step 8.
9. ⬜ Timeouts/cancellation/backpressure implementation + the full test
   matrix from issue #235 ("Testes obrigatórios": limits, cancellation,
   timeout, loop selection, Git/diskcache integration, large-repo system
   test, low-memory system test, deterministic regression, Windows/Linux/
   macOS) -- issue #235 plan step 9.
10. ⬜ After/before benchmark comparison + tuning docs + rollback docs --
    issue #235 plan step 10.

Each unchecked item above should be filed as its own follow-up issue
(scoped, reviewable) rather than resumed as one large PR against this ADR.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/235
- Baseline benchmark: `docs/async-pipeline-baseline-benchmark.md`,
  `docs/evidence/async-pipeline-baseline-benchmark.json`,
  `scripts/async_pipeline_baseline_benchmark.py`
- Related ADR: `ADR-003-two-tier-async-mapper.md` (fast/deep split at the
  `scan`/`status` command layer -- orthogonal to this ADR, which is about
  parallelism *inside* the deep pass itself)
- Files referenced: `simplicio_mapper/mapper/parse.py`,
  `simplicio_mapper/mapper/graph.py`, `simplicio_mapper/mapper/emit.py`,
  `simplicio_mapper/cache.py`
