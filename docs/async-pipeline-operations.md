# Async mapping pipeline -- operational guide (issue #264)

Operator-facing / operational reference for the `AsyncMappingPipeline`
(`simplicio_mapper/mapper/async_pipeline.py`, PR #260,
`simplicio_mapper/mapper/async_io.py`, PR #257,
`simplicio_mapper/mapper/async_inventory.py`, PR #262 -- standalone
reference implementation, not wired into any command), the bounded-
concurrency pipeline behind `simplicio-mapper index|map|scan` (deep pass).
Design and full plan-step history:
`.specs/architecture/ADR-009-async-mapping-pipeline.md`. This document
covers configuration, rollback/disable, and troubleshooting -- for raw
before/after numbers, read `docs/async-pipeline-baseline-benchmark.md`,
`docs/async-pipeline-after-benchmark.md`,
`docs/async-pipeline-after-benchmark-linux-container.md`,
`docs/async-pipeline-dispatch-benchmark.md`, and
`docs/async-inventory-benchmark.md`.

This is a normal-operation reference doc, not a getting-started guide --
see `docs/local-setup.md` for install/run basics.

## What actually runs today

`simplicio_mapper/mapper/emit.py::build_artifacts` (the function every CLI
command calls) does a cheap, content-free file-count probe
(`_fast_file_count`) and then dispatches:

```python
def build_artifacts(cwd, meta=None, incremental=False, output_dir=".simplicio"):
    abs_cwd = os.path.abspath(cwd)
    threshold = _async_pipeline_min_files()
    if _fast_file_count(abs_cwd, threshold) < threshold:
        return _build_artifacts_sync(abs_cwd, meta, incremental, output_dir)
    from .async_pipeline import _install_uvloop_if_available, build_artifacts_async
    _install_uvloop_if_available()
    return asyncio.run(build_artifacts_async(abs_cwd, meta, incremental, output_dir))
```

- **Below `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`** (default `600`,
  see "Configuration knobs" below): the run goes through
  `_build_artifacts_sync`, a restored copy of the original pre-PR-260
  synchronous walk-and-parse-and-write body -- this is the common case for
  most real-world (small/medium) repos this tool maps.
- **At or above the threshold**: the run goes through
  `async_pipeline.build_artifacts_async`
  (`async_pipeline.build_file_inventory_async`, bounded-concurrency,
  `asyncio.to_thread`-based file reads, for the walk-and-parse stage), then
  the symbol-index/call-graph/architecture-inventory/JSON-write stages run
  exactly as before -- those stages are untouched and stay synchronous
  regardless of which path was taken.

`build_artifacts()`'s signature, return value, and on-disk
`.simplicio/*.json` output are identical on both paths and covered by
`OutputEquivalenceTest` (byte-for-byte equivalence, sync vs. async, with
and without a shared cache).

## Configuration knobs

All env vars below are read fresh on every call (not cached at import
time), so they can be set per-invocation.

| Variable | Default | Effect | Invalid/out-of-range input |
|---|---|---|---|
| `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` | `600` | File-count threshold (`_fast_file_count`, early-exiting once reached) below which `build_artifacts` routes to the plain synchronous pipeline instead of the async one -- see "What actually runs today" above and "Rollback / disable" below. | Non-integer or `<= 0` is **ignored**, falling back to the default. |
| `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` | `min(32, os.cpu_count() * 4)` | Caps in-flight file read+parse tasks (a single `asyncio.Semaphore`). Never unbounded, regardless of setting; only applies once a run is on the async path. | Non-integer or `<= 0` is **ignored**, falling back to the default (not zero, not unbounded) -- verified by `test_env_override_controls_the_cap` in `tests/python/test_async_pipeline.py`. |
| `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` | `30.0` | Per-file wall-clock budget (`asyncio.wait_for` around each file's read+parse) on the async path. A file that exceeds this is recorded in `degraded.timed_out_files` and dropped from the inventory -- the run itself is not aborted. | Non-numeric or `<= 0` is **ignored**, falling back to `30.0` -- verified by `test_per_file_timeout_env_override`. |

Example, forcing the async path on a smaller tree and lowering both async
knobs for a slow/constrained environment (e.g. a network-mounted repo, or a
CI runner with few cores):

```bash
SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES=1 \
  SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=8 SIMPLICIO_MAPPER_FILE_TIMEOUT_S=10 \
  simplicio-mapper index /path/to/project
```

```powershell
$env:SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES = "1"
$env:SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES = "8"
$env:SIMPLICIO_MAPPER_FILE_TIMEOUT_S = "10"
simplicio-mapper index C:\path\to\project
```

Setting `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=1` effectively serializes
the async pipeline's own file-level concurrency (one file in flight at a
time) -- useful for isolating whether a problem is concurrency-related, but
**not equivalent to the synchronous pipeline** (it still goes through
`asyncio.to_thread` per file, still pays event-loop/task-scheduling
overhead per file; see "Known limitation" below). To genuinely bypass the
async pipeline, use `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` instead
(see "Rollback / disable" below).

## `uvloop` opt-in (Linux/macOS only)

- `_install_uvloop_if_available()` in `async_pipeline.py` attempts
  `import uvloop` and, on success, installs `uvloop.EventLoopPolicy()` as
  the process's event loop policy before the async pipeline runs.
- **Windows**: never attempted (`sys.platform == "win32"` short-circuits to
  `False` immediately) -- this matches upstream `uvloop`, which does not
  ship Windows wheels.
- **Linux/macOS with `uvloop` not installed** (the default state of a
  fresh `pip install simplicio-mapper` -- confirmed as the actual behavior
  observed in a real container run for issue #264, see
  `docs/async-pipeline-after-benchmark-linux-container.md`): the `import`
  raises `ModuleNotFoundError`/`ImportError`, caught and treated as "not
  available" -- the stdlib `asyncio` event loop is used, silently, with no
  error, no warning, and no behavior change other than not getting
  uvloop's speedup.
- **Linux/macOS with `uvloop` installed**: the policy is installed and
  used automatically -- there is no environment variable to opt out of
  uvloop specifically once it is importable in the environment (the only
  way to avoid it is to not have `uvloop` installed, to run on Windows, or
  to stay under the size-based dispatch threshold so the run never reaches
  the async path at all). This path is verified today only via
  `unittest.mock` in `UvloopSelectionTest` (mocked
  `sys.platform`/`sys.modules`), **not** against a real `uvloop`
  installation actually driving the event loop -- an honestly-documented
  gap inherited from ADR-009.
- **Not currently exposed as a packaging extra.** The ADR originally
  proposed `simplicio-mapper[uvloop]`; `pyproject.toml`'s
  `[project.optional-dependencies]` today only declares `dev`. To opt in
  manually: `pip install uvloop` (non-Windows only) alongside
  `simplicio-mapper` -- no `simplicio-mapper` config or flag needed once
  it's importable, it activates automatically on the next async-path run.
- To confirm which loop is active: uvloop, once installed, replaces
  `asyncio`'s default event loop *policy* process-wide for the lifetime of
  the process; there is no CLI flag to print this today (a reasonable ask
  for a future `--verbose`/`--diagnostics` flag, not implemented here).

### Windows fallback

Windows always uses the stdlib `asyncio` event loop
(`ProactorEventLoop`/`SelectorEventLoop`, whichever `asyncio` itself
selects by default on the running Python version) -- there is nothing to
configure here; it is the same code path as "Linux/macOS with uvloop not
installed" above, just unconditional rather than import-dependent. All
benchmark numbers in `docs/async-pipeline-baseline-benchmark.md`,
`docs/async-pipeline-after-benchmark.md`, and
`docs/async-pipeline-dispatch-benchmark.md` were measured on Windows, so
Windows is in fact this pipeline's most-measured platform to date; Linux is
covered by `docs/async-pipeline-after-benchmark-linux-container.md` (issue
#264) plus the full focused test suite passing on Linux (26 passed, 1
skipped -- see that file for the skip's explanation). macOS remains
unverified in any sandbox available to date.

## Cancellation and backpressure

- **Backpressure**: bounded by the semaphore described above -- there is no
  separate queue-depth or backpressure knob beyond
  `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`; lowering that value is the
  correct lever if you need to reduce peak concurrent I/O/memory pressure
  on the async path. A task acquires the semaphore before starting its
  read+parse and releases it in a `finally`, so a slow file never
  permanently occupies a concurrency slot beyond its own timeout.
- **Per-file timeout**: fails soft. A file that exceeds
  `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` is recorded under
  `project-map.json`'s `degraded.timed_out_files` and excluded from the
  inventory; the rest of the run completes normally. There is currently no
  separate "run has taken too long overall" budget -- only the per-file
  timeout exists.
- **Cancellation**: if the coroutine running `build_artifacts_async` (or
  the `asyncio.run()` wrapping it in the sync adapter) is cancelled or
  interrupted (e.g. `Ctrl+C` from the CLI, or a caller cancelling the
  surrounding `asyncio` task if embedding this as a library), every
  in-flight per-file task is explicitly cancelled and drained (`await
  asyncio.gather(*tasks, return_exceptions=True)`) before the cancellation
  propagates, and every semaphore acquisition is released via `finally` --
  no task or leaked semaphore permit is left running past the pipeline's
  own return (`CancellationTest` in `tests/python/test_async_pipeline.py`
  exercises this directly). One caveat inherited from `asyncio.to_thread`
  itself and documented in ADR-009: cancelling the `await` does not forcibly
  kill the underlying OS thread mid-syscall; a thread already blocked in a
  blocking `open()`/read may finish that one syscall before the executor
  reclaims it. This is a known Python stdlib limitation, not a bug specific
  to this pipeline.
- **Writes stay atomic regardless of cancellation**: the `.simplicio/*.json`
  writes (`_write_json_stable`, tmp-file + `os.replace`) happen only after
  every async inventory task has been awaited, in a single-threaded,
  sequential pass, exactly as on the sync path. A cancelled run never
  partially writes an artifact file.

## Rollback / disable behavior

Two independent levers exist today, at different granularity:

1. **`SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` set to an arbitrarily
   large value is a deterministic, always-available kill-switch.** Since
   `build_artifacts` routes to `_build_artifacts_sync` whenever the
   pre-run file count is below this threshold, setting it above any repo
   you will ever map (e.g. `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES=999999999`)
   forces every run through the fully-synchronous, pre-PR-260 code path,
   with no code change or package rollback required. This supersedes an
   earlier documented gap ("no runtime kill-switch exists") -- it does now,
   as of the size-based dispatch follow-up (ADR-009 plan step 11).
2. **Tune around it instead of disabling it.** Most reported problems on
   the async path (slow runs, high memory, timeouts) are addressed by
   `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` and
   `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` above without touching code or
   forcing the sync path.

If a deeper rollback is ever needed (e.g. a bug in `_build_artifacts_sync`
itself, not just "avoid the async path"), the remaining options, in order
of preference:

3. **Pin to a pre-async release.** Since `build_artifacts()`'s signature and
   output are unchanged, downgrading the installed `simplicio-mapper`
   version to the last release before PR #260 landed
   (`pip install "simplicio-mapper==<version>"`) is a real, working
   rollback path -- confirm the exact last pre-async version against the
   CHANGELOG/release tags before pinning, since this document does not
   hardcode a version number that will drift out of date.
4. **Revert PR #260 on a local branch** if you are running from source and
   need a code-level rollback rather than a package pin or env var --
   `git revert` (or `git checkout` the pre-merge commit) restores the
   fully synchronous `_build_file_inventory` loop unconditionally. This is
   the highest-effort option and should only be used if options 1-3 do not
   resolve the issue.

**Why there was no soft kill-switch for a while, and why there is one
now**: ADR-009's original ship did not include a dedicated "disable async"
switch, because the sync public API (`build_artifacts()`) was preserved
exactly and the async rewrite was additive/internal rather than a new
opt-in surface a caller chooses to enable -- adding a second maintained
code path was seen as doubling the surface that needs testing. Issue
#264's after-benchmark then showed a genuine small/medium-tree performance
regression from going unconditionally async, which is what motivated the
size-based dispatch follow-up (plan step 11) -- that follow-up's threshold
env var happens to also function as the kill-switch this document
previously said did not exist. `_build_artifacts_sync` is a restored,
tested copy of the pre-#260 loop, not a second implementation invented from
scratch, so the "doubling the maintained surface" concern is bounded to
keeping that restored function in sync with `graph.py`/`parse.py`, which
`OutputEquivalenceTest` and the dispatch-boundary regression tests
continue to guard.

## Known limitation: async can be slower than sync on small/medium trees

Real measurements gathered for issue #264
(`docs/async-inventory-benchmark.md`) show the production-wired
`async_pipeline.build_file_inventory_async` running **slower** than the
plain sync `_build_file_inventory` loop for cold-cache runs at every
measured size, on this Windows machine (0.14x-0.34x of sync's wall time,
i.e. 3x-7x slower), and roughly at parity for warm-cache runs. The
full-pipeline after-benchmark
(`docs/async-pipeline-after-benchmark.md`) showed the same effect at the
whole-`build_artifacts()` level for small (0.53x) and medium (0.67x)
trees. This is reported honestly, not smoothed over -- see ADR-009's
"Evidence update" and step 10/11 sections for the full numbers, the
standalone `async_inventory` module's contrasting (positive) results, and
the working hypothesis for the difference (`asyncio`/thread-pool
scheduling overhead outweighing I/O-wait when there isn't much I/O-wait to
begin with).

The size-based dispatch (`SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`,
default `600`, see "What actually runs today" above) exists specifically
to route small/medium trees back to the synchronous path so this
regression is no longer user-visible by default
(`docs/async-pipeline-dispatch-benchmark.md`) -- but if you force the
async path onto a small tree (e.g. for testing, via a very low threshold),
expect it to be measurably slower than the default sync path, not faster.

Operators on I/O-constrained environments (slow disks, network
filesystems) where cold-cache reads genuinely dominate wall time may see
different results than this Windows-local-disk measurement; this doc does
not claim the regression generalizes to every environment, only that it is
real on the platforms measured so far.

## Troubleshooting

### A file shows up in `degraded.timed_out_files`

- **Symptom**: the written `project-map.json`'s `degraded.timed_out_files`
  list is non-empty; that file is missing from the run's `files` array.
- **Cause**: that file's read+parse (on the async path) did not complete
  within `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` (default 30s) -- typically a
  stalled network filesystem, a very large file that also happens to sit
  right at or above the 250KB skip threshold boundary, or genuine host I/O
  starvation under heavy concurrent load.
- **Diagnose**: re-run with a higher `SIMPLICIO_MAPPER_FILE_TIMEOUT_S`
  (e.g. `120`) and see if the file completes -- if it does, the original
  timeout was simply too tight for that host/filesystem. If it still times
  out, check the file's actual size/location (`ls -la <path>`, confirm it
  is not a remote mount that is itself degraded).
- **Fix**: raise `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` for that environment, or
  investigate/fix the underlying slow filesystem. This is never a
  correctness bug in the pipeline itself -- it is the pipeline correctly
  refusing to let one slow file hang an entire run.

### A run "hangs" or takes far longer than expected

- **Diagnose**: check `.simplicio/project-map.json`'s top-level `degraded`
  object after the run completes -- `timed_out_files` lists any file that
  hit the per-file timeout (the run itself always completes; it does not
  hang waiting for a single slow file).
- If the *whole run* seems slow (not stuck) on a small/medium tree, see
  "Known limitation" above first -- confirm whether the run actually took
  the async path (a tree at or above
  `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`); if so, this may be
  expected behavior for cold-cache runs on this OS/environment, not a hang.
- **Fix**: lower `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` to fail soft on slow
  files sooner, and/or lower `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` if the
  environment has limited I/O bandwidth and high concurrency is causing
  contention rather than parallel speedup; this is the same lever as
  "Rollback / disable" option 2 above.

### Files missing from `project-map.json` that exist on disk

- **Cause**: either the file hit `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` (check
  `degraded.timed_out_files`), or it hit the pre-existing (unrelated to
  async) large-file skip threshold (check
  `degraded.skipped_large_files`/`degraded.large_file_limit_bytes`), or a
  transient `OSError` on `os.stat` (permission, file deleted mid-scan) --
  silently skipped on both the sync and async paths, matching pre-existing
  behavior.
- **Fix**: re-run with a higher `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` if the
  file is legitimately large/slow to read, not actually hung.

### Cache/SQLite errors (`diskcache`, `FileProcessingCache`)

- **Symptom**: an error referencing `sqlite3`, `diskcache`, or a "file still
  in use" / locked-file error around `.simplicio/cache/`.
- **Cause**: `FileProcessingCache` opens one SQLite connection per worker
  *thread* (`threading.local`-backed) the first time that thread touches
  the cache. `_process_one_file` in `async_pipeline.py` explicitly closes
  that per-thread connection right after each file's cache access
  specifically to avoid leaking per-thread connections across `asyncio`'s
  reused default executor -- if you see a locked/in-use error on
  `.simplicio/cache/` right after a run (most commonly observed as a
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
  `asyncio.run()`-managed context) raises exactly this `RuntimeError`. This
  only happens when the run actually takes the async path -- a run that
  dispatches to `_build_artifacts_sync` never calls `asyncio.run()`.
- **Cause**: the async adapter path does
  `asyncio.run(build_artifacts_async(...))` internally; `asyncio.run()`
  itself refuses to be called when a loop is already running in the
  current thread -- this is standard `asyncio` behavior, not something
  specific to this pipeline.
- **Fix**: if your caller is already inside an event loop, `await
  build_artifacts_async(cwd, meta, incremental, output_dir)` directly
  instead of calling the sync `build_artifacts()` -- this is exactly why
  `build_artifacts_async` is exposed as a first-class native async API
  rather than only an implementation detail behind the sync wrapper
  (ADR-009's own design goal: "adicionar API async nativa sem
  `asyncio.run()` aninhado"). Do not attempt to work around this by
  spawning a new thread just to call the sync wrapper from inside an async
  context -- call the async function directly.

### `uvloop` not activating on Linux/macOS

- **Cause**: `uvloop` is not installed (`pip install uvloop`), or
  `sys.platform == "win32"` (uvloop is never attempted on Windows, by
  design -- not a bug), or the run never reached the async path at all
  (tree below `SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`).
- **Diagnose**: `python -c "import uvloop"` -- if this raises
  `ImportError`, that's why. There is no packaged
  `simplicio-mapper[uvloop]` extra today (see "`uvloop` opt-in" above); it
  must be installed as a separate, manual step. Also confirm the run
  actually crossed the size-based dispatch threshold.

## Cross-references

- Design and full plan-step history: `.specs/architecture/ADR-009-async-mapping-pipeline.md`
- Implementation: `simplicio_mapper/mapper/async_pipeline.py`,
  `simplicio_mapper/mapper/async_io.py`,
  `simplicio_mapper/mapper/async_inventory.py`,
  `simplicio_mapper/mapper/emit.py` (dispatch, sync adapter,
  `_build_artifacts_sync`, `_fast_file_count`)
- Before/after numbers (Windows, original issue #235 finalization pass):
  `docs/async-pipeline-baseline-benchmark.md`,
  `docs/async-pipeline-after-benchmark.md`
- Before/after numbers (Linux container, issue #264):
  `docs/async-pipeline-after-benchmark-linux-container.md`
- Dispatch/crossover benchmark (size-based dispatch, plan step 11):
  `docs/async-pipeline-dispatch-benchmark.md`
- Inventory-stage-only benchmark (issue #264):
  `docs/async-inventory-benchmark.md`
- Raw JSON evidence: `docs/evidence/async-pipeline-baseline-benchmark.json`,
  `docs/evidence/async-pipeline-after-benchmark.json`,
  `docs/evidence/async-pipeline-after-benchmark-linux-container.json`,
  `docs/evidence/async-pipeline-dispatch-benchmark.json`,
  `docs/evidence/async-inventory-benchmark.json`
- Tests: `tests/python/test_async_pipeline.py`,
  `tests/python/test_mapper_async_inventory.py`,
  `tests/python/test_mapper_async_io.py`,
  `tests/python/test_pipeline_dispatch.py` (dispatch logic),
  `tests/python/test_async_pipeline_docs.py` (asserts the configuration
  surface documented above stays in sync with the code)
