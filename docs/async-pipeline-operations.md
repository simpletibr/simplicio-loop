# Async mapping pipeline -- operational guide (issue #264)

Operator-facing guide for the `AsyncMappingPipeline`
(`simplicio_mapper/mapper/async_pipeline.py`, ADR-009,
`.specs/architecture/ADR-009-async-mapping-pipeline.md`), the bounded-
concurrency pipeline that has been the default engine behind every
`simplicio-mapper index|map|scan` command since PR #260. This document
covers configuration, rollback/disable, and troubleshooting -- for the
design rationale and the full plan-step history, read ADR-009 itself; for
raw before/after numbers, read `docs/async-pipeline-baseline-benchmark.md`,
`docs/async-pipeline-after-benchmark.md`, and
`docs/async-pipeline-after-benchmark-linux-container.md`.

## TL;DR

The async pipeline is **always on** -- there is no runtime feature flag
that switches it off. `build_artifacts()` (the same public function every
CLI command has always called) is now a thin
`asyncio.run(build_artifacts_async(...))` adapter; its signature, return
value, and on-disk `.simplicio/*.json` output are unchanged and covered by
`OutputEquivalenceTest` (byte-for-byte equivalence with the old sync path).
Day-to-day, an operator only ever needs the two environment variables in
the next section; the "Rollback / disable" section further down covers
what to do if the pipeline itself needs to be bypassed rather than tuned.

## Configuration

### `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`

Caps how many files can be mid-read/parse at once (a single
`asyncio.Semaphore`, never unbounded `asyncio.gather`).

- Default: `min(32, os.cpu_count() * 4)` (`_max_concurrent_files()` in
  `async_pipeline.py`). On a 4-core machine that is `16`; on a 64-core
  machine it caps at `32` rather than scaling unbounded.
- Override: set to any positive integer, e.g.
  `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=1` for the minimum-footprint
  configuration (also the proxy configuration used by
  `LowResourceProxyTest` in `tests/python/test_async_pipeline.py` to
  approximate low-memory behavior).
- Invalid input (non-numeric, zero, or negative) is **ignored in favor of
  the default**, not treated as "unbounded" -- there is no way to disable
  the concurrency cap via this variable, by design.
- When to tune it: lower it (e.g. `4`-`8`) on a memory-constrained host
  where many in-flight file reads risk exhausting available RAM; raise it
  (up to the `32` ceiling) on a fast-disk/high-core-count host processing a
  very large tree, if `docs/async-pipeline-after-benchmark.md`-style
  measurement on that host shows headroom.

### `SIMPLICIO_MAPPER_FILE_TIMEOUT_S`

Per-file timeout (seconds) wrapping each file's `to_thread` read+parse in
`asyncio.wait_for(...)`.

- Default: `30.0` seconds (`_DEFAULT_FILE_TIMEOUT_S`) -- generous enough
  that an ordinary source file under the existing 250KB large-file skip
  threshold never trips it, while still bounding a genuinely hung read
  (e.g. a stalled network filesystem).
- Override: set to any positive float, e.g.
  `SIMPLICIO_MAPPER_FILE_TIMEOUT_S=5` to fail faster in a test/CI
  environment, or a larger value for a known-slow filesystem (network
  mount, remote drive).
- Invalid input (non-numeric, zero, or negative) is ignored in favor of the
  default, same rule as the concurrency variable above.
- On timeout: the file is recorded in an internal `timed_out` list, dropped
  from the inventory for that run, and surfaced in the final artifact's
  `degraded.timed_out_files` field (sorted). **The run does not abort** --
  this is a fail-soft behavior, matching the existing large-file-skip
  pattern, not a fatal error. See "Troubleshooting -- timeout" below for
  what to do when you see entries there.

### `uvloop` (opt-in, Linux/macOS only)

- `_install_uvloop_if_available()` in `async_pipeline.py` attempts
  `import uvloop` and, on success, installs `uvloop.EventLoopPolicy()` as
  the process's event loop policy before the pipeline runs.
- **Windows**: never attempted (`sys.platform == "win32"` short-circuits to
  `False` immediately) -- this matches upstream `uvloop`, which does not
  ship Windows wheels.
- **Linux/macOS with `uvloop` not installed** (the default state of a
  fresh `pip install simplicio-mapper` -- confirmed as the actual behavior
  observed in a real container run for this issue, see
  `docs/async-pipeline-after-benchmark-linux-container.md`): the `import`
  raises `ModuleNotFoundError`, caught and treated as "not available" --
  the stdlib `asyncio` event loop is used, silently, with no error, no
  warning, and no behavior change other than not getting uvloop's speedup.
- **Linux/macOS with `uvloop` installed**: the policy is installed and
  used automatically -- there is no environment variable to opt out of
  uvloop specifically once it is importable in the environment (the only
  way to avoid it is to not have `uvloop` installed, or to run on
  Windows). This path is verified today only via `unittest.mock` in
  `UvloopSelectionTest` (mocked `sys.platform`/`sys.modules`), **not**
  against a real `uvloop` installation actually driving the event loop --
  an honestly-documented gap inherited from ADR-009 and not closed by this
  issue (installing `uvloop` requires adding a dependency, which this
  repo's `AGENTS.md` requires asking the user about first).
- To install the opt-in: `pip install uvloop` (no dedicated
  `simplicio-mapper[uvloop]` extra is declared in `pyproject.toml` today;
  ADR-009 describes one as a *possible future* shape, not a shipped one --
  do not assume `pip install simplicio-mapper[uvloop]` works without first
  checking `pyproject.toml`'s `[project.optional-dependencies]`).

### Windows fallback

Windows always uses the stdlib `asyncio` event loop
(`ProactorEventLoop`/`SelectorEventLoop`, whichever `asyncio` itself
selects by default on the running Python version) -- there is nothing to
configure here; it is the same code path as "Linux/macOS with uvloop not
installed" above, just unconditional rather than import-dependent. All
benchmark numbers in `docs/async-pipeline-baseline-benchmark.md` and
`docs/async-pipeline-after-benchmark.md` were measured on Windows, so
Windows is in fact this pipeline's most-measured platform to date; Linux is
covered by `docs/async-pipeline-after-benchmark-linux-container.md`
(added for this issue) plus the full focused test suite passing on Linux
(26 passed, 1 skipped -- see that file for the skip's explanation). macOS
remains unverified in any sandbox available to date.

### Cancellation and backpressure

- **Backpressure**: bounded by the semaphore described above -- there is no
  separate queue-depth or backpressure knob beyond
  `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`; lowering that value is the
  correct lever if you need to reduce peak concurrent I/O/memory pressure.
- **Cancellation**: if the coroutine running `build_artifacts_async` (or
  the `asyncio.run()` wrapping it in the sync adapter) is cancelled or
  interrupted, every in-flight per-file task is explicitly cancelled and
  drained (`await asyncio.gather(*tasks, return_exceptions=True)`) before
  the cancellation propagates -- no task is left running past the
  pipeline's own return. One caveat inherited from `asyncio.to_thread`
  itself and documented in ADR-009: cancelling the `await` does not forcibly
  kill the underlying OS thread mid-syscall; a thread already blocked in a
  blocking `open()`/read may finish that one syscall before the executor
  reclaims it. This is a known Python stdlib limitation, not a bug specific
  to this pipeline, and does not leave orphaned tasks at the `asyncio`
  level (only, in the worst case, one thread finishing its current
  syscall a little after cancellation was requested).
- **Ctrl-C from the CLI**: a `KeyboardInterrupt` during a CLI command run
  propagates the same way any other cancellation does -- the semaphore and
  task-draining logic above applies regardless of what triggered the
  cancellation.

## Rollback / disable behavior

There is **no environment variable or CLI flag that switches the pipeline
back to a purely synchronous, non-`asyncio` code path** -- unlike the
native-runtime-delegation kill-switches documented elsewhere in this repo's
`CLAUDE.md`/`AGENTS.md` (e.g. `SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT`), ADR-009
did not design or ship a dedicated "disable async" switch, because the sync
public API (`build_artifacts()`) was preserved exactly and the async
rewrite is additive/internal rather than a new opt-in surface a caller
chooses to enable. If a genuine regression is found in production and a
rollback is needed, the available options, in order of preference, are:

1. **Tune around it first** -- most reported problems (slow runs, high
   memory, timeouts) are addressed by `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`
   and `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` above without touching code. Start
   here.
2. **Pin to a pre-async release.** Since `build_artifacts()`'s signature and
   output are unchanged, downgrading the installed `simplicio-mapper`
   version to the last release before PR #260 landed
   (`pip install "simplicio-mapper<<pin-to-pre-PR-260-version>>"`) is a
   real, working rollback path -- confirm the exact last pre-async version
   against the CHANGELOG/release tags before pinning, since this document
   does not hardcode a version number that will drift out of date.
3. **Revert PR #260 on a local branch** if you are running from source and
   need a code-level rollback rather than a package pin -- `git revert` (or
   `git checkout` the pre-merge commit) restores the fully synchronous
   `_build_file_inventory` loop. This is the highest-effort option and
   should only be used if options 1-2 do not resolve the issue.

**Why there is no soft kill-switch**: adding one now (e.g. an
`SIMPLICIO_MAPPER_DISABLE_ASYNC_PIPELINE` env var that branches
`build_artifacts()` back to a kept-alive synchronous code path) would mean
maintaining two parallel implementations of the file-inventory stage
indefinitely, doubling the surface that needs testing and doubling the
risk that they silently drift apart in behavior (exactly the
`OutputEquivalenceTest` this pipeline relies on to prove they are
byte-for-byte identical today would need to keep being true against a
non-deleted second implementation). This is a deliberate trade-off, not an
oversight -- documented here so it is a known, discussed limitation instead
of an implicit assumption.

## Troubleshooting

### A file shows up in `degraded.timed_out_files`

- **Symptom**: the written `project-map.json`'s `degraded.timed_out_files`
  list is non-empty; that file is missing from the run's `files` array.
- **Cause**: that file's read+parse did not complete within
  `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` (default 30s) -- typically a stalled
  network filesystem, a very large file that also happens to sit right at
  or above the 250KB skip threshold boundary, or genuine host I/O
  starvation under heavy concurrent load.
- **Diagnose**: re-run with a higher
  `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` (e.g. `120`) and see if the file
  completes -- if it does, the original timeout was simply too tight for
  that host/filesystem. If it still times out, check the file's actual
  size/location (`ls -la <path>`, confirm it is not a remote mount that
  is itself degraded).
- **Fix**: raise `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` for that environment, or
  investigate/fix the underlying slow filesystem. This is never a
  correctness bug in the pipeline itself -- it is the pipeline correctly
  refusing to let one slow file hang an entire run.

### Run is slower than expected / higher memory than expected

- **Symptom**: wall time or peak RSS is higher than the numbers in
  `docs/async-pipeline-after-benchmark.md` /
  `docs/async-pipeline-after-benchmark-linux-container.md` for a
  similarly-sized tree.
- **Diagnose**: check `os.cpu_count()` on the host vs. the benchmark
  machine (the concurrency default scales with core count, so a
  higher-core host will use more concurrent file handles/threads, which
  can raise peak RSS on a memory-constrained host even though it is
  usually faster overall); check whether `uvloop` is active
  (`python3 -c "import uvloop"` -- if it raises, it is not, and the
  stdlib loop is in use, which is correct-but-slower, not broken).
- **Fix**: lower `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` to trade wall
  time for lower peak concurrency/memory footprint; this is the same lever
  as "Rollback / disable" option 1 above.

### Cache/SQLite errors (`diskcache`, `FileProcessingCache`)

- **Symptom**: an error referencing `sqlite3`, `diskcache`, or a "file still
  in use" / locked-file error around `.simplicio/cache/`.
- **Cause**: `FileProcessingCache` opens one SQLite connection per worker
  *thread* (`threading.local`-backed) the first time that thread touches
  the cache. `_process_one_file` in `async_pipeline.py` explicitly calls
  `cache.close()` from the same worker thread right after that file's
  cache access specifically to avoid leaking per-thread connections across
  `asyncio`'s reused default executor -- if you see a locked/in-use error
  on `.simplicio/cache/` right after a run (most commonly observed as a
  Windows "file still in use" error when something else immediately tries
  to remove that directory), the cause is very likely something *external*
  to the pipeline still holding a handle (an editor, an antivirus scanner,
  a previous still-running process), not the pipeline itself leaking a
  connection -- the explicit per-file `close()` call exists precisely to
  rule the pipeline out as the source of this class of bug.
- **Diagnose**: confirm no other process has `.simplicio/cache/*.db` open
  (on Linux: `lsof | grep .simplicio/cache`; on Windows: Process Explorer's
  "Find Handle" against the cache directory path).
- **Fix**: close the other process/handle, or delete `.simplicio/cache/`
  entirely and let the next run rebuild it from scratch (cache is a pure
  performance optimization -- deleting it is always safe, only slower,
  never lossy).

### Event-loop conflicts (`RuntimeError: asyncio.run() cannot be called from a running event loop`)

- **Symptom**: calling the sync `build_artifacts()` from code that is
  itself already running inside an event loop (e.g. from within an async
  web framework request handler, a Jupyter notebook cell, or another
  `asyncio.run()`-managed context) raises exactly this `RuntimeError`.
- **Cause**: the sync adapter does `asyncio.run(build_artifacts_async(...))`
  internally; `asyncio.run()` itself refuses to be called when a loop is
  already running in the current thread -- this is standard `asyncio`
  behavior, not something specific to this pipeline.
- **Fix**: if your caller is already inside an event loop,
  `await build_artifacts_async(...)` directly instead of calling the sync
  `build_artifacts()` -- this is exactly why `build_artifacts_async` is
  exposed as a first-class native async API rather than only an
  implementation detail behind the sync wrapper (ADR-009's own design
  goal: "adicionar API async nativa sem `asyncio.run()` aninhado"). Do not
  attempt to work around this by spawning a new thread just to call the
  sync wrapper from inside an async context -- call the async function
  directly.

## Cross-references

- Design and full plan-step history: `.specs/architecture/ADR-009-async-mapping-pipeline.md`
- Before/after numbers (Windows, original issue #235 finalization pass):
  `docs/async-pipeline-baseline-benchmark.md`,
  `docs/async-pipeline-after-benchmark.md`
- Before/after numbers (Linux container, this issue #264):
  `docs/async-pipeline-after-benchmark-linux-container.md`
- Raw JSON evidence: `docs/evidence/async-pipeline-baseline-benchmark.json`,
  `docs/evidence/async-pipeline-after-benchmark.json`,
  `docs/evidence/async-pipeline-after-benchmark-linux-container.json`
- Implementation: `simplicio_mapper/mapper/async_pipeline.py`,
  `simplicio_mapper/mapper/emit.py` (sync adapter)
- Tests: `tests/python/test_async_pipeline.py`,
  `tests/python/test_mapper_async_inventory.py`,
  `tests/python/test_async_pipeline_docs.py` (this issue -- asserts the
  configuration surface documented above stays in sync with the code)
