# ADR-009: Async mapping pipeline with bounded concurrency (`AsyncMappingPipeline`)

> Addresses https://github.com/wesleysimplicio/simplicio-mapper/issues/235
> ("[Performance] Arquitetar pipeline assíncrono e concorrência limitada
> para mapeamento Python"). This ADR originally covered only the **design**
> (plan steps 1-3); the pipeline itself, its full test matrix, and the
> after-benchmark (plan steps 4-10) have since been implemented across
> several follow-up PRs. Step 10's own honest after-benchmark then revealed
> a real small/medium-tree regression versus the pre-#235 synchronous
> baseline; plan step 11 fixes it with a size-based sync/async dispatch in
> `build_artifacts`, so the async pipeline is now engaged only above a
> measured file-count threshold rather than unconditionally. **Update
> (issue #264, 2026-07-18)** adds two further pieces on top of that: an
> inventory-stage-only before/after (sync vs. both async implementations,
> with CPU/RSS/p95) in `docs/async-inventory-benchmark.md` /
> `docs/evidence/async-inventory-benchmark.json`, and an operator-facing
> config/rollback/troubleshooting guide in `docs/async-pipeline-operations.md`
> -- neither existed before issue #264. See "Plano de adoção" below for the
> complete, updated status and the "Decisão de fechamento" note for the
> honest remaining gaps.
>
> **Issue #264 update**: the operator-facing configuration/rollback/
> troubleshooting guide referenced throughout this ADR as a gap now exists
> at `docs/async-pipeline-operations.md`. A second, independent after-
> benchmark run was also executed on Linux (this ADR's benchmarks were
> Windows-only until now) -- see `docs/async-pipeline-after-benchmark-linux-container.md`
> and the "Decisão de fechamento" section below for exactly what that run
> does and does not close.

---

## Status

`Aceito` (implementado -- ver "Plano de adoção" e "Decisão de fechamento"
abaixo; gaps de cobertura e de operação (kill-switch, packaging extra do
uvloop) documentados honestamente, não bloqueadores)

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

### Baseline measurement (issue #235 plan step 1) -- historical, frozen

`scripts/async_pipeline_baseline_benchmark.py` (added in this same
Phase-0 PR) measures the then-current synchronous pipeline end-to-end via
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

> **Frozen as of the async adapter landing (issue #264).** `build_artifacts`
> now unconditionally delegates to `build_artifacts_async` (plan step 8
> below), so there is no independently callable full-pipeline *sync* entry
> point left on this revision to re-measure against -- the script itself
> refuses to run here (`_assert_historical_sync_baseline`, PR #265) rather
> than silently mislabel the current async pipeline as a "before" number.
> These committed numbers remain the last real, historical, pre-async
> full-pipeline baseline; they are not regenerated or extrapolated by this
> update. See "Evidence update (issue #264)" below for the current,
> reproducible inventory-stage comparison and its own explicit limitations.

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

## Evidence update (issue #264, 2026-07-18)

Real, reproducible before/after measurements for the actual async pipeline
that ships today were gathered against this revision (`845bb2e`), Python
3.14.5, Windows, `python3 scripts/async_inventory_benchmark.py --sizes --runs 3 --write`.
Full report: `docs/async-inventory-benchmark.md` /
`docs/evidence/async-inventory-benchmark.json` (schema
`simplicio.async-inventory-benchmark/v1`). Summary (cold wall-time
speedup vs. the sync `_build_file_inventory` loop, same machine, same run):

| Size | Files | `async_inventory` (PR #262, standalone) cold/warm speedup vs sync | `async_pipeline` (PR #260, production-wired) cold/warm speedup vs sync |
|---|---:|---:|---:|
| small | 4 | 0.78x / 0.42x | 0.14x / 0.12x |
| medium | 242 | 2.49x / 2.43x | 0.31x / 0.95x |
| large | 1814 | 2.34x / 2.69x | 0.34x / 0.92x |

**Important, honest finding, not hidden**: on this Windows machine,
`async_pipeline.build_file_inventory_async` -- the implementation actually
composed into `build_artifacts_async` and therefore what every
`index`/`map`/`scan` run uses today -- is measurably **slower** than the
plain sync loop for cold-cache runs at every measured size (0.14x-0.34x,
i.e. 3x-7x slower wall time), and roughly at parity for warm-cache runs
(0.92x-0.95x, within noise for medium/large; still slower for small). The
standalone `async_inventory` module (PR #262, not wired into any command)
shows the positive speedup this ADR's design predicted (2.3x-2.7x cold,
matching the design's I/O-bound-gain thesis) for medium/large trees.

The two implementations differ in shape: `async_inventory` does a batched
2-pass design (sync stat+cache-check pass, then one bounded
`asyncio.gather` over only the files that actually need a disk read, then a
sync CPU-bound parse pass), while `async_pipeline._process_one_file` issues
**two separate `asyncio.to_thread` calls per file** (`os.stat`, then a
combined read+parse+cache-access) inside one semaphore-bounded task per
file, every file, regardless of cache hit/miss. A quick isolated check
(monkeypatching away the per-file `cache.close()` call in a throwaway
script, not committed) did not reproduce the gap on its own, so the more
likely explanation is the doubled `to_thread` scheduling overhead per file
combined with not skipping the read for cache hits -- but this is a
hypothesis, not confirmed by a dedicated profile in this pass. **This is a
genuine, measured performance regression in the currently-shipping async
path relative to the sync path it replaced, on this machine/OS** -- per
this task's own scope ("do not change `async_pipeline.py`'s actual
behavior"), it is reported here and in the PR body as a follow-up, not
fixed inline. Recommended follow-up: profile `async_pipeline._process_one_file`
directly (not just the inventory-level wall time) on Windows, and consider
adopting `async_inventory`'s batched-pass shape (skip the read entirely on
a true cache hit, single `to_thread` per file that actually needs work)
inside `async_pipeline` instead of the current per-file double-`to_thread`
shape.

Two further gaps found while gathering this evidence, not previously
called out in this ADR:

- **No deterministic rollback/kill-switch exists.** `build_artifacts`
  unconditionally calls `asyncio.run(build_artifacts_async(...))` -- there
  is no `SIMPLICIO_MAPPER_*` environment variable (or any other runtime
  toggle) to force the old, fully-sync `_build_file_inventory`-based code
  path back on. `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=1` serializes the
  async pipeline's own concurrency (closest available mitigation) but is
  **not** the same code path as the pre-#260 sync loop and does not undo
  the measured regression above (concurrency isn't the cause of it). The
  only deterministic rollback today is pinning/reverting to a pre-PR-#260
  revision or release. See `docs/async-pipeline-operations.md`
  ("Rollback / disable") for the full write-up; recommended follow-up: file
  an issue to add an explicit kill-switch env var
  (e.g. `SIMPLICIO_MAPPER_DISABLE_ASYNC_PIPELINE`) that routes
  `build_artifacts` back through `_build_file_inventory` directly.
- **No `uvloop` packaging extra.** ADR's original design proposed
  `simplicio-mapper[uvloop]`; `pyproject.toml`'s
  `[project.optional-dependencies]` only declares `dev` today. The lazy
  `try: import uvloop` fallback logic itself is implemented and tested
  (`UvloopSelectionTest`, `tests/python/test_async_pipeline.py`), but a user
  who wants uvloop must `pip install uvloop` manually and undocumented,
  rather than via a declared extra.

---

## Critério de revisão

- Revisit once `build_file_inventory_async` is implemented and a fresh run
  of `scripts/async_pipeline_baseline_benchmark.py` (or its successor)
  shows the after numbers -- if warm/cold files/s does not improve
  meaningfully for the medium/large synthetic trees, the design's core
  assumption (I/O-wait dominates at this project's typical file sizes)
  needs to be revisited before investing further. **Resolved by the issue
  #264 evidence update above**: warm/cold *does* improve for the standalone
  `async_inventory` module, but the production-wired `async_pipeline` path
  currently does not on this machine -- revisit this ADR's core assumption
  specifically for `async_pipeline`'s per-file task shape (see "Evidence
  update" above).
- Revisit if the `_candidate_import_targets` quadratic-scan follow-up
  fix changes the profiled bottleneck distribution enough that a process
  pool for regex parsing becomes newly justified (Alternativa B). **Done**:
  PR #255 fixed it with an `O(n)` suffix index
  (`graph.py::_known_path_suffix_index`); no fresh profile redone as part
  of issue #264 (out of scope -- this update is evidence/docs only, per
  #264's own non-goals).
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
4. ✅ Follow-up issue: fix `_candidate_import_targets`'s `O(n^2)` fallback
   scan (`graph.py:307-313`) with an index built once in `O(n)` (e.g. a
   `dict[str, list[str]]` keyed by stripped-suffix over `known_paths`).
   Independent of the async work; landed first, PR #255 (63f9838),
   156x-584x speedup on the profiled quadratic path.
5. ✅ Implemented `build_file_inventory_async` + bounded semaphore +
   `asyncio.to_thread` for reads and git status -- issue #235 plan steps
   4-5. `simplicio_mapper/mapper/async_pipeline.py`, PR #260 (6340988).
   (Note: an earlier, narrower stepping-stone landed first in PR #262
   (`simplicio_mapper/mapper/async_inventory.py`, fb1b2c0) -- superseded by
   `async_pipeline.py`'s own `build_file_inventory_async`, which is the one
   actually composed into `build_artifacts_async` below.
   `async_inventory.py` is not wired into any entry point and is kept only
   for its own tests/benchmark; it is dead code relative to production,
   noted here rather than silently left unexplained. See "Evidence update"
   above for the issue #264 inventory-stage-only measurement of both
   implementations side by side.)
6. ✅ Implemented `build_artifacts_async` composing the async inventory step
   with the (still synchronous, CPU-bound) symbol-index/call-graph/write
   stages, keeping the single writer -- issue #235 plan step 6.
   `simplicio_mapper/mapper/async_pipeline.py::build_artifacts_async`, PR
   #260 (6340988).
7. ✅ (partial) `uvloop` optional extra + Linux/macOS auto-detection + Windows
   fallback -- issue #235 plan step 7. `_install_uvloop_if_available()` in
   `async_pipeline.py`, PR #260 (6340988); covered by
   `UvloopSelectionTest` in `tests/python/test_async_pipeline.py`
   (Windows-verified on this machine; Linux/macOS import-success path
   covered only via mocked `sys.platform`/`sys.modules`, not a real
   non-Windows run -- see item 9 below for the honest cross-platform
   caveat). **Not done**: the `simplicio-mapper[uvloop]` optional packaging
   extra this ADR originally proposed was never added to `pyproject.toml`
   (`[project.optional-dependencies]` only declares `dev` as of issue
   #264) -- a user who wants uvloop must `pip install uvloop` manually,
   undocumented until issue #264's operator guide.
8. ✅ `build_artifacts` sync adapter wrapping `asyncio.run(build_artifacts_async(...))`,
   CLI unchanged -- issue #235 plan step 8.
   `simplicio_mapper/mapper/emit.py::build_artifacts`, PR #260 (6340988).
   Verified: every CLI command (`index`/`map`/`scan`/...) still calls this
   same function with the same signature; `OutputEquivalenceTest` in
   `tests/python/test_async_pipeline.py` asserts the sync adapter's
   `build_artifacts()` output is byte-identical (modulo timestamps) to a
   direct `asyncio.run(build_artifacts_async(...))` call. **Not done**: no
   runtime kill-switch/rollback env var exists to force this adapter back
   onto the pre-#260 fully-sync `_build_file_inventory` path -- see
   "Evidence update" above and `docs/async-pipeline-operations.md`
   ("Rollback / disable") for the deterministic-rollback gap this
   surfaced.
9. ✅ (partial, see caveats) Timeouts/cancellation/backpressure implementation
   + the test matrix from issue #235 ("Testes obrigatórios"), audited and
   closed out in the issue #235 finalization pass:
   - **Limits/bounded concurrency**: ✅ `BoundedConcurrencyTest` in
     `tests/python/test_async_pipeline.py` (never exceeds the configured
     semaphore cap, default cap formula, env override).
   - **Timeout**: ✅ `TimeoutTest` (one slow file times out without hanging
     the run, env override for the per-file timeout).
   - **Cancellation**: ✅ `CancellationTest` (cancelling the pipeline
     propagates cleanly, semaphore released, no orphaned tasks left after
     the OS threads unwind).
   - **Loop selection (uvloop)**: ✅ `UvloopSelectionTest` (Windows never
     attempts uvloop; non-Windows install/fallback logic, mocked).
   - **Git/diskcache integration**: ✅ `OutputEquivalenceTest`'s
     `test_async_inventory_matches_sync_inventory_with_a_shared_cache` (a
     real `FileProcessingCache`, not mocked) plus the full
     `test_large_project_lifecycle.py` suite (real git repos: rename/move/
     delete/restore, branch switch, interrupted checkout, corrupted-state
     recovery) exercising `build_artifacts()` -- which is the async path
     now -- end-to-end.
   - **Sistema em repositório grande**: ✅ added in the issue #235
     finalization pass -- `LargeRepositorySystemTest` in
     `tests/python/test_async_pipeline.py` runs the REAL CLI entry point
     (`simplicio_mapper.cli.main(["index", ...])`, not just the isolated
     `async_pipeline` module) end-to-end over a git-backed, ~320-file
     synthetic tree, validates the written `project-map.json` against its
     committed JSON Schema, and covers an incremental re-index pass too.
     (Kept smaller than the 1650-file benchmark tree to stay fast in the
     unit-test suite; the 1650-file scale is covered by the after-benchmark
     script instead, see item 10.)
   - **Sistema sob baixa memória**: ⚠️ **honestly not covered as a true
     OS-level low-memory test.** `LowResourceProxyTest` (same test file)
     documents why and provides the closest achievable proxy: this sandbox
     is Windows, where neither `resource.setrlimit(RLIMIT_AS, ...)`
     (POSIX-only) nor cgroup memory limits are available from inside a
     unittest run, so there is no way here to genuinely cap the process's
     memory and observe real OOM-recovery behavior. The proxy test drives
     `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=1` (the pipeline's own minimum-
     footprint configuration) over a 120-file tree and asserts correct
     completion -- this proves graceful behavior at minimum concurrency, not
     survival under an enforced memory ceiling. A genuine low-memory system
     test needs dedicated infra (a Linux cgroup-limited container/CI job)
     that does not exist for this repo today; filed here as a known,
     explicit gap rather than faked.
   - **Regressão determinística**: ✅ `OutputEquivalenceTest` (byte-for-byte
     equality, sync vs. async, with and without a shared cache; full
     `build_artifacts()` JSON-artifact equivalence too).
   - **Windows/Linux/macOS**: ⚠️ **Windows-verified since PR #260;
     Linux-verified since issue #264 (partial); macOS still untested.**
     Every test above (including the two new system-level classes) was run
     and passed on Windows (Python 3.14.5) at the time this ADR's plan
     steps were closed out. Issue #264 additionally ran the full focused
     suite (`tests/python/test_async_pipeline.py` +
     `tests/python/test_mapper_async_inventory.py`) on a real Linux
     container (Python 3.11.15): **26 passed, 1 skipped** -- the 1 skip is
     `UvloopSelectionTest::test_build_artifacts_never_calls_uvloop_installer_on_windows`,
     correctly platform-gated to skip on non-Windows. This closes the
     "Linux untested" gap for (a) the full test matrix and (b) a real,
     non-mocked run of `build_artifacts()` completing successfully across
     small/medium/large trees on Linux (see
     `docs/async-pipeline-after-benchmark-linux-container.md`). It does
     **not** close the uvloop-active sub-gap: `uvloop` itself is not
     installed in that container, so `_install_uvloop_if_available()`
     genuinely (not mocked) exercises the "not available, fall back to
     stdlib asyncio" branch on Linux, but the branch where
     `uvloop.EventLoopPolicy()` is actually installed and driving the
     event loop remains verified only via `unittest.mock` in
     `UvloopSelectionTest`. macOS remains entirely untested in any sandbox
     available to date -- no macOS runner exists here either. This repo
     also has no CI at all as of issue #264 -- GitHub Actions workflows
     were removed entirely, a separate, unrelated change -- so all of the
     above is sandbox-local verification, not CI-enforced.
10. ✅ After/before benchmark comparison -- issue #235 plan step 10, with
    two complementary reports:
    - **Full pipeline** (`scripts/async_pipeline_after_benchmark.py`, added
      in the issue #235 finalization pass): re-runs the same
      sizes/methodology as `scripts/async_pipeline_baseline_benchmark.py`
      against the CURRENT, async-wired `build_artifacts()`; results
      committed to `docs/async-pipeline-after-benchmark.md` /
      `docs/evidence/async-pipeline-after-benchmark.json`. Honest summary
      of what was measured (Python 3.14.5, Windows, this machine, `--runs 3`):

      | Size | Files | Before cold wall p50 (s) | After cold wall p50 (s) | Speedup |
      |---|---:|---:|---:|---:|
      | small | 4 | 0.0682 | 0.1288 | 0.53x (slower) |
      | medium | 220 | 1.0738 | 1.6082 | 0.67x (slower) |
      | large | 1650 | 25.7289 | 13.8028 | 1.86x |

      This is the honest number, not a rosy one: small/medium trees got
      **slower**, not faster -- `asyncio`/thread-pool scheduling overhead
      outweighs the I/O-wait it hides when there is little I/O-wait to begin
      with, exactly as ADR-009's own "Negativas" section predicted as a real
      possibility rather than ruled out. The large tree's 1.86x improvement is
      real but, per the after-benchmark script's own framing note, cannot be
      attributed to the async pipeline alone -- PR #255's independent O(n^2)
      `_candidate_import_targets` fix landed on the same revision and was
      already known (from this ADR's own profiling) to be the dominant cost
      at that scale (93s of a 120s profiled run), so most of the large-tree
      win is very likely that algorithmic fix, not the concurrency rewrite.
    - **Inventory stage only** (`scripts/async_inventory_benchmark.py`,
      extended in issue #264): isolates the walk-and-parse stage alone (no
      O(n^2)-fix confound, since that fix lives in the downstream
      call-graph stage, not the inventory stage) and additionally splits
      out the standalone `async_inventory` module from the production
      `async_pipeline` implementation -- see "Evidence update" above.
      `docs/async-inventory-benchmark.md` /
      `docs/evidence/async-inventory-benchmark.json`.

    Revisiting this ADR's own "Critério de revisão" honestly, with both
    reports in hand: the core assumption that I/O-wait dominates enough for
    concurrency alone to pay off at this project's typical (mostly small)
    file sizes is **not** confirmed by either after-benchmark -- if
    anything it is mildly contradicted for small/medium trees in the
    full-pipeline report, and directly contradicted at every measured size
    for the production `async_pipeline` implementation specifically in the
    inventory-stage report (0.14x-0.34x cold vs. sync). The pipeline is
    still the right long-term shape (bounded, safe, no unbounded
    concurrency, bug-for-bug equivalent output) and is a prerequisite for
    larger repos and any future genuinely I/O-bound workload (e.g. network
    filesystems), but its standalone perf case for this project's actual
    small-file-dominated typical repo is weak on today's evidence --
    reported here as-is rather than reframed to look better. Issue #264
    also adds the operator-facing config/rollback/troubleshooting guide
    this plan step originally asked for and the finalization pass above did
    not produce: `docs/async-pipeline-operations.md`.

Every plan step (1-10) above is now checked off; see the top-level
"Decisão de fechamento" note below for whether that means issue #235 itself
is closable.

11. ✅ **Size-based dispatch follow-up** (issue #235 direct follow-up,
    filed immediately after step 10's honest after-benchmark exposed a
    real small/medium regression). Step 10's own numbers showed the
    unconditionally-async `build_artifacts()` is genuinely SLOWER than the
    pre-#235 synchronous pipeline for small (0.53x) and medium (0.67x)
    trees -- `asyncio`/thread-pool scheduling overhead outweighs the
    I/O-wait it hides when a tree does not have much I/O-wait to begin
    with. Since most real-world projects this tool maps are small/medium
    (not 1650-file synthetic monsters), shipping that regression as the
    unconditional default would not fulfill issue #235's own performance
    premise.

    Fix: `simplicio_mapper/mapper/emit.py::build_artifacts` now does a
    cheap, content-free file-count probe (`_fast_file_count`, reusing the
    existing `_walk`/`SKIP_DIRS`/worktree-exclusion logic and `TEXT_EXTS`
    allowlist, early-exiting once the threshold is reached so probing a
    huge tree never becomes its own expensive pre-pass) before deciding
    which pipeline to run:
    - Below `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` (default **600**,
      see measurement below): routes to `_build_artifacts_sync`, a
      restored copy of the original pre-#235 synchronous
      walk-and-parse-and-write body (verbatim from the pre-6340988
      revision, still benefiting from PR #255's unrelated O(n^2) fix in
      `graph.py`, which is shared code).
    - At or above the threshold: routes to
      `async_pipeline.build_artifacts_async` via `asyncio.run(...)`,
      exactly as before this follow-up.

    **Threshold measurement** (`scripts/async_pipeline_dispatch_benchmark.py`,
    `docs/async-pipeline-dispatch-benchmark.md`,
    `docs/evidence/async-pipeline-dispatch-benchmark.json`; Python 3.14.5,
    Windows, this machine): forcing sync vs. async explicitly via the same
    env var on the SAME current revision (both paths already include PR
    #255's fix, so this is a like-for-like comparison unlike the
    across-revision before/after table above) at several synthetic-tree
    sizes:

    | Files | Sync cold wall p50 (s) | Async cold wall p50 (s) | Faster path |
    |---:|---:|---:|---|
    | 220 (medium) | 1.536 | 1.736 | sync (~13%) |
    | 300 | 2.154 | 2.303 | sync (~7%) |
    | 400 | 3.419 | 3.368 | ~parity (async marginally ahead) |
    | 600 | 4.382 | 4.620 | sync (~5%) |
    | 800 | 6.736 | 6.419 | ~parity (async marginally ahead) |
    | 1200 | 11.169 | 10.344 | async (~7%) |
    | 1650 (large) | 16.085 | 12.997 | async (~19%) |

    Reading this honestly: the crossover is not a sharp line -- it is a
    noisy band roughly between 400 and 1200 files where sync and async are
    within measurement noise of each other (Windows wall-clock timing on
    this machine has ~5-10% run-to-run variance even for identical code,
    confirmed by re-running the same size twice and seeing sync "win" in
    one script invocation and "lose" in another when the two paths shared
    a source directory -- an earlier, discarded measurement attempt that
    turned out to be biased by OS page-cache warm-up: whichever path ran
    second in the same directory benefited from the first path's disk
    reads. The numbers above use independently materialized, per-mode
    source trees to remove that bias). Given that band, **600** is chosen
    as the default: it sits inside the noisy crossover zone rather than
    past it, erring toward the synchronous path (the known-safe,
    zero-regression choice) for anything at or below a size where async's
    benefit is not yet clearly demonstrated, while still being low enough
    that any repo meaningfully larger than the noisy band (i.e. approaching
    1650) gets the real, measured async win. The threshold is env-var
    tunable (`SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`) precisely because
    600 is a reasoned default from noisy data, not a guaranteed-optimal
    constant for every environment/filesystem.

    **Confirmation** (`docs/async-pipeline-dispatch-benchmark.md`'s
    dispatch-active table, same three sizes as the historical before/after
    benchmarks, real unmodified `build_artifacts()` with the dispatcher
    active): small and medium trees are back at (or better than) the
    original pre-#235 synchronous baseline, and the large tree still gets
    the async pipeline's real win -- see that document for the exact
    numbers from this measurement run.

    Tests: `tests/python/test_pipeline_dispatch.py` -- threshold/env-var
    unit tests, `_fast_file_count` unit tests (extension filtering, `SKIP_DIRS`
    honored, worktree exclusion honored, early-exit at the cap, never opens
    a file), dispatch-routing tests (sync path taken below threshold, async
    at/above, exact boundary at threshold-1/threshold/threshold+1), and a
    byte-identical-output regression gate across the dispatch boundary
    (dispatcher's choice vs. both paths forced directly, at
    threshold-1/threshold/threshold+1 files).

    **Honest verdict on whether this closes issue #235's performance
    premise**: yes, with the same platform caveat as step 10 -- this fix
    is verified on Windows/Python 3.14.5 only (no Linux/macOS runner
    available in this sandbox), and the crossover threshold is a
    measured-but-noisy default, not a universal constant (hence the env-var
    escape hatch). Within those honest limits, the regression that made
    step 10's after-benchmark fail to support issue #235's own performance
    premise is now fixed: small/medium trees (the common case) no longer
    regress relative to the pre-#235 baseline, and large trees keep the
    real async win.

### Decisão de fechamento (issue #235 finalization pass, updated after step 11 and issue #264)

All 11 plan steps are implemented and tested, with honestly-documented
partial gaps rather than silent omissions:

- **Low-memory system test**: proxy only (minimum-concurrency, not a real
  memory ceiling), documented as infeasible in this sandbox without
  dedicated Linux cgroup infra. Still open as of issue #264 -- unchanged,
  out of scope for that issue (it is a docs/evidence issue, not a new-infra
  issue).
- **Windows/Linux/macOS**: Windows-verified only; Linux/macOS untested in
  this sandbox (no runner available; this repo has no CI at all).
  **Partially closed by issue #264**: see the updated "Testes
  obrigatórios -- Windows/Linux/macOS" bullet above -- Linux is now
  verified for the full test matrix and a real after-benchmark run; the
  uvloop-active branch and macOS remain unverified.
- **Production `async_pipeline` performance regression** (issue #264
  finding): measurably slower than the sync inventory loop it replaced, at
  every measured size, in the isolated inventory-stage benchmark -- see
  "Evidence update" above. Not present in the full-pipeline after-benchmark
  numbers above in the same stark form because that report's large-tree row
  is dominated by PR #255's unrelated O(n^2) fix, which the inventory-only
  report does not include.
- **No deterministic rollback/kill-switch env var** (issue #264 finding,
  filed against a revision before step 11 landed): **superseded** --
  `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` set to an arbitrarily large
  value now deterministically forces every run through
  `_build_artifacts_sync`, which is exactly the rollback mechanism this
  finding asked for.
- **No `uvloop` packaging extra** (issue #264 finding): the ADR's original
  `simplicio-mapper[uvloop]` proposal was never added to `pyproject.toml`.

Step 10's after-benchmark, taken alone, actually undermined issue #235's
own premise: it showed the unconditionally-async pipeline was SLOWER than
the pre-#235 baseline for the common (small/medium) case, which is not a
performance win for this project's typical repo size. Step 11's size-based
dispatch directly addresses that: small/medium trees are routed back to a
verified-equivalent synchronous path (no regression vs. the pre-#235
baseline), and only trees large enough to cross a measured (if noisy)
threshold engage the async pipeline, where the win is real. This closes
the specific gap the earlier finalization pass could not honestly close.

Given issue #235's own acceptance criteria are about the pipeline's design
and safety properties (bounded concurrency, no orphaned tasks, atomic
writes, optional uvloop, sync API preservation) -- all of which are now
implemented and unit/integration/system-tested on two platforms (Windows
and, since issue #264, Linux) -- and given the after-benchmark (step 10),
the dispatch benchmark (step 11), and the inventory-stage benchmark (issue
#264) all provide genuine, un-cherry-picked numbers (including the honest
small/medium regression that step 11 fixes at the full-pipeline level, and
the still-open isolated-inventory-stage regression issue #264 found) on
both platforms, the recommendation is that issue #235 is **closable** with
these gaps recorded as known follow-ups (a dedicated low-memory CI job, a
macOS CI runner, Linux/macOS CI execution of the same test suite, a
profiling pass + possible redesign of
`async_pipeline._process_one_file`'s per-file task shape, and a `uvloop`
packaging extra) rather than blockers, since none of them is a correctness
or safety defect in the shipped code -- they are verification-coverage,
performance, and operability gaps, all now explicitly tracked rather than
hidden. Note that step 11's `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`
env var, set to an arbitrarily large value, already functions as the
deterministic kill-switch issue #264 asked for (forces every run through
`_build_artifacts_sync`) -- so that specific gap from issue #264's original
finding is superseded by step 11, even though it was filed against an
earlier revision that did not yet have it. The size-based dispatch
threshold itself is also not a closed question forever: it is a measured
default on one machine/filesystem, tunable via the same env var, and should
be revisited if a future, less noisy benchmarking environment (or
real-world usage data) suggests a different crossover point. The
coordinating session should make the final call on closing the GitHub
issue.

### Issue #264 closure note (evidence + operational guide)

Issue #264 asked for four things this ADR did not yet have in one place:
(1) reconciled ADR status/checklist -- done above; (2) reproducible
before/after measurements for small/medium/large trees -- the existing
Windows numbers already covered this; a second, independent Linux
measurement was added for this issue
(`docs/async-pipeline-after-benchmark-linux-container.md` /
`docs/evidence/async-pipeline-after-benchmark-linux-container.json`),
with an explicit caveat that cross-machine (Windows vs. Linux-container)
comparisons are informational only, not a controlled experiment; (3)
configuration/rollback/troubleshooting documentation -- new,
`docs/async-pipeline-operations.md`; (4) tests asserting the docs/receipt
schema stay in sync with the code -- new,
`tests/python/test_async_pipeline_docs.py`. No production code changed for
this issue, per its own non-goals ("Rewriting the async pipeline").

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/235
- Follow-up / evidence issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/264
  (evidence + operational guide)
- Baseline benchmark (historical, frozen, pre-async): `docs/async-pipeline-baseline-benchmark.md`,
  `docs/evidence/async-pipeline-baseline-benchmark.json`,
  `scripts/async_pipeline_baseline_benchmark.py`
- After benchmark (Windows, unconditionally-async, plan step 10):
  `docs/async-pipeline-after-benchmark.md`,
  `docs/evidence/async-pipeline-after-benchmark.json`,
  `scripts/async_pipeline_after_benchmark.py`
- After benchmark (Linux container, issue #264):
  `docs/async-pipeline-after-benchmark-linux-container.md`,
  `docs/evidence/async-pipeline-after-benchmark-linux-container.json`
- Dispatch/crossover benchmark (size-based dispatch, plan step 11):
  `docs/async-pipeline-dispatch-benchmark.md`,
  `docs/evidence/async-pipeline-dispatch-benchmark.json`,
  `scripts/async_pipeline_dispatch_benchmark.py`
- Inventory-stage-only benchmark (issue #264): `docs/async-inventory-benchmark.md`,
  `docs/evidence/async-inventory-benchmark.json`,
  `scripts/async_inventory_benchmark.py`
- Operational guide (issue #264): `docs/async-pipeline-operations.md`
  (configuration, rollback/disable, troubleshooting)
- Doc/schema drift guard (issue #264): `tests/python/test_async_pipeline_docs.py`
- Related ADR: `ADR-003-two-tier-async-mapper.md` (fast/deep split at the
  `scan`/`status` command layer -- orthogonal to this ADR, which is about
  parallelism *inside* the deep pass itself)
- Files referenced: `simplicio_mapper/mapper/parse.py`,
  `simplicio_mapper/mapper/graph.py`,
  `simplicio_mapper/mapper/emit.py` (`build_artifacts` dispatch,
  `_build_artifacts_sync`, `_fast_file_count`), `simplicio_mapper/cache.py`
- Tests: `tests/python/test_pipeline_dispatch.py` (dispatch logic),
  `tests/python/test_async_pipeline.py` (pre-existing sync/async
  equivalence, unaffected by the dispatch)
