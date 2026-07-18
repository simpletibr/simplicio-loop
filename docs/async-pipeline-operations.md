# Async mapping pipeline -- operator guide (issue #264)

Operational reference for the async file-inventory pipeline that powers
every `simplicio-mapper index`/`map`/`scan` (deep pass) run today. Design:
`.specs/architecture/ADR-009-async-mapping-pipeline.md`. Implementation:
`simplicio_mapper/mapper/async_pipeline.py` (PR #260),
`simplicio_mapper/mapper/async_io.py` (PR #257),
`simplicio_mapper/mapper/async_inventory.py` (PR #262, standalone reference
implementation, not wired into any command). Evidence:
`docs/async-inventory-benchmark.md` / `docs/evidence/async-inventory-benchmark.json`.

This is a normal-operation reference doc, not a getting-started guide --
see `docs/local-setup.md` for install/run basics.

## What actually runs today

`simplicio_mapper/mapper/emit.py::build_artifacts` (the function every CLI
command calls) is a thin sync adapter:

```python
def build_artifacts(cwd, meta=None, incremental=False, output_dir=".simplicio"):
    from .async_pipeline import _install_uvloop_if_available, build_artifacts_async
    _install_uvloop_if_available()
    return asyncio.run(build_artifacts_async(cwd, meta, incremental, output_dir))
```

So every `index`/`map`/`scan` run always goes through
`async_pipeline.build_artifacts_async`, which itself calls
`async_pipeline.build_file_inventory_async` (bounded-concurrency,
`asyncio.to_thread`-based file reads) for the walk-and-parse stage, then
runs the symbol-index/call-graph/architecture-inventory/JSON-write stages
exactly as before -- those stages are untouched and stay synchronous.

There is currently **no way to opt out at runtime** -- see "Rollback /
disable" below.

## Configuration knobs

Both env vars are read fresh on every call (not cached at import time), so
they can be set per-invocation.

| Variable | Default | Effect | Invalid/out-of-range input |
|---|---|---|---|
| `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` | `min(32, os.cpu_count() * 4)` | Caps in-flight file read+parse tasks (a single `asyncio.Semaphore`). Never unbounded, regardless of setting. | Non-integer or `<= 0` is **ignored**, falling back to the default (not zero, not unbounded) -- verified by `test_env_override_controls_the_cap` in `tests/python/test_async_pipeline.py`. |
| `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` | `30.0` | Per-file wall-clock budget (`asyncio.wait_for` around each file's read+parse). A file that exceeds this is recorded in `degraded.timed_out_files` and dropped from the inventory -- the run itself is not aborted. | Non-numeric or `<= 0` is **ignored**, falling back to `30.0` -- verified by `test_per_file_timeout_env_override`. |

Example, lowering both for a slow/constrained environment (e.g. a
network-mounted repo, or a CI runner with few cores):

```bash
SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=8 SIMPLICIO_MAPPER_FILE_TIMEOUT_S=10 \
  simplicio-mapper index /path/to/project
```

```powershell
$env:SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES = "8"
$env:SIMPLICIO_MAPPER_FILE_TIMEOUT_S = "10"
simplicio-mapper index C:\path\to\project
```

Setting `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=1` effectively serializes
the async pipeline's own file-level concurrency (one file in flight at a
time) -- useful for isolating whether a problem is concurrency-related, but
**not equivalent to the old pre-#260 sync code path** (it still goes
through `asyncio.to_thread` per file, still pays event-loop/task-scheduling
overhead per file; see "Known limitation: async can be slower than sync on
this OS" below).

## `uvloop` opt-in

- Linux/macOS only (`sys.platform != "win32"`); Windows **always** uses the
  stdlib `asyncio` event loop -- there is no configuration to change this,
  by design (`uvloop` does not ship Windows wheels upstream either).
- Lazy `try: import uvloop / except ImportError` inside
  `_install_uvloop_if_available()` (`async_pipeline.py`) -- never a hard
  dependency. If `uvloop` is not installed, or the import fails for any
  reason, the stdlib event loop is used silently, with no error and no
  behavior change other than the loop implementation.
- **Not currently exposed as a packaging extra.** The ADR originally
  proposed `simplicio-mapper[uvloop]`; `pyproject.toml`'s
  `[project.optional-dependencies]` today only declares `dev`. To opt in
  manually: `pip install uvloop` (non-Windows only) alongside
  `simplicio-mapper` -- no `simplicio-mapper` config or flag needed once
  it's importable, it activates automatically on the next run.
- To confirm which loop is active: uvloop, once installed, replaces
  `asyncio`'s default event loop *policy* process-wide for the lifetime of
  the process; there is no CLI flag to print this today (a reasonable ask
  for a future `--verbose`/`--diagnostics` flag, not implemented here).

## Cancellation / backpressure semantics

- **Backpressure**: bounded by the single `asyncio.Semaphore` sized by
  `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` -- no unbounded `asyncio.gather`,
  no per-file fire-and-forget task. A task acquires the semaphore before
  starting its read+parse and releases it in a `finally`, so a slow file
  never permanently occupies a concurrency slot beyond its own timeout.
- **Per-file timeout**: fails soft. A file that exceeds
  `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` is recorded under
  `project-map.json`'s `degraded.timed_out_files` and excluded from the
  inventory; the rest of the run completes normally. There is currently no
  separate "run has taken too long overall" budget -- only the per-file
  timeout exists.
- **Cancellation** (e.g. `Ctrl+C`, or a caller cancelling the surrounding
  `asyncio` task if embedding this as a library): `asyncio.CancelledError`
  propagates cleanly. In-flight tasks are explicitly cancelled and
  awaited-drained (not just left to `asyncio.gather`'s own cancellation),
  and every semaphore acquisition is released via `finally`, so no
  orphaned task or leaked semaphore permit survives the call returning or
  raising (`CancellationTest` in `tests/python/test_async_pipeline.py`
  exercises this directly).
- **Known `asyncio.to_thread` limitation, documented not hidden**:
  cancelling the coroutine that's awaiting a `to_thread` call cancels *the
  await*, not the underlying OS thread -- a thread that's mid-syscall (e.g.
  blocked in `open()`/`.read()`) keeps running until that syscall returns,
  even after the pipeline itself has returned/raised due to cancellation.
  This is a stdlib limitation, not specific to this implementation.
- **Writes stay atomic regardless of cancellation**: the five
  `.simplicio/*.json` writes (`_write_json_stable`, tmp-file + `os.replace`)
  happen only after every async inventory task has been awaited, in a
  single-threaded, sequential pass, exactly as before this pipeline
  existed. A cancelled run never partially writes an artifact file.

## Rollback / disable

**There is currently no runtime kill-switch** to force `build_artifacts`
back onto the pre-#260 fully-synchronous code path -- `build_artifacts`
unconditionally calls `asyncio.run(build_artifacts_async(...))`. This is a
real, documented gap (see ADR-009's "Evidence update" section), not an
oversight hidden here.

If the async pipeline needs to be disabled for an operator (correctness
regression, unexpected environment interaction, etc.), the deterministic
options today, in order of preference:

1. **Pin/revert to a pre-async release.** `simplicio-mapper` versions
   published before PR #260 landed still ship the fully-synchronous
   `_build_file_inventory`-based `build_artifacts`. Check
   `CHANGELOG.md`/PyPI release history for the version immediately before
   this PR merged, and pin to it (`pip install "simplicio-mapper==<version>"`).
2. **Reduce concurrency to 1** (`SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES=1`)
   as a partial mitigation for concurrency-specific symptoms (e.g.
   suspected races, resource contention under high fan-out) -- this does
   **not** revert to the old code path and does not address the measured
   cold-run performance regression documented below, since that regression
   is not concurrency-related.
3. **File a follow-up issue** to add an explicit kill-switch env var
   (e.g. `SIMPLICIO_MAPPER_DISABLE_ASYNC_PIPELINE=1`) that routes
   `build_artifacts` through `_build_file_inventory` (still present in
   `simplicio_mapper/mapper/parse.py`, unused by production code today but
   not deleted) instead of the async adapter. Not implemented as part of
   issue #264, which is documentation/evidence-only and explicitly out of
   scope for changing `async_pipeline.py`'s behavior.

## Known limitation: async can be slower than sync on this OS

Real measurements gathered for issue #264
(`docs/async-inventory-benchmark.md`) show the production-wired
`async_pipeline.build_file_inventory_async` running **slower** than the
plain sync `_build_file_inventory` loop for cold-cache runs at every
measured size, on this Windows machine (0.14x-0.34x of sync's wall time,
i.e. 3x-7x slower), and roughly at parity for warm-cache runs. This is
reported honestly, not smoothed over -- see ADR-009's "Evidence update"
section for the full numbers, the standalone `async_inventory` module's
contrasting (positive) results, and the working hypothesis for the
difference. Operators on I/O-constrained environments (slow disks, network
filesystems) where cold-cache reads genuinely dominate wall time may see
different results than this Windows-local-disk measurement; this doc does
not claim the regression generalizes to every environment, only that it is
real on the one measured here.

## Troubleshooting

### A run "hangs" or takes far longer than expected

- **Diagnose**: check `.simplicio/project-map.json`'s top-level
  `degraded` object after the run completes -- `timed_out_files` lists any
  file that hit the per-file timeout (the run itself always completes; it
  does not hang waiting for a single slow file).
- If the *whole run* seems slow (not stuck), see "Known limitation" above
  first -- this may be expected behavior on this OS/environment for
  cold-cache runs, not a hang.
- **Fix**: lower `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` to fail soft on slow
  files sooner, and/or lower `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` if the
  environment has limited I/O bandwidth and high concurrency is causing
  contention rather than parallel speedup.

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

### Cache/SQLite (`diskcache`) issues -- "file still in use" on Windows, or a locked/corrupt cache

- **Cause**: `FileProcessingCache` (`diskcache`, SQLite-backed) opens one
  connection per worker *thread*. The async pipeline explicitly closes that
  per-thread connection right after each file's cache access
  (`_process_one_file`'s `_parse_and_release_thread_local_connection`) to
  avoid leaking a file handle for the process lifetime on Windows -- if you
  see a `.simplicio/cache` directory that won't delete immediately after a
  run, ensure no other process (editor, antivirus scan, a second mapper
  run) still has the SQLite file open, then retry.
- **Fix for a suspected corrupt cache**: delete `.simplicio/cache/` and
  re-run (equivalent to a cold run; safe, the cache is purely a
  performance optimization, never a source of truth).

### Event-loop conflicts ("`asyncio.run() cannot be called from a running event loop`")

- **Cause**: `build_artifacts` (sync) calls `asyncio.run(...)`, which
  raises `RuntimeError` if invoked from code that is *already* inside a
  running event loop (e.g. calling `build_artifacts()` from inside an
  `async def` handler, a Jupyter notebook cell already running an event
  loop, or another async framework's request handler).
- **Fix**: if you are already inside an event loop, `await
  build_artifacts_async(cwd, meta, incremental, output_dir)` directly
  instead of calling the sync `build_artifacts` wrapper -- import it from
  `simplicio_mapper.mapper.async_pipeline`.

### `uvloop` not activating on Linux/macOS

- **Cause**: `uvloop` is not installed (`pip install uvloop`), or
  `sys.platform == "win32"` (uvloop is never attempted on Windows, by
  design -- not a bug).
- **Diagnose**: `python -c "import uvloop"` -- if this raises
  `ImportError`, that's why. There is no packaged
  `simplicio-mapper[uvloop]` extra today (see "`uvloop` opt-in" above); it
  must be installed as a separate, manual step.

## Links

- Design: `.specs/architecture/ADR-009-async-mapping-pipeline.md`
- Implementation: `simplicio_mapper/mapper/async_pipeline.py`,
  `simplicio_mapper/mapper/async_io.py`,
  `simplicio_mapper/mapper/async_inventory.py`
- Tests: `tests/python/test_async_pipeline.py`,
  `tests/python/test_mapper_async_inventory.py`,
  `tests/python/test_mapper_async_io.py`
- Evidence: `docs/async-inventory-benchmark.md`,
  `docs/evidence/async-inventory-benchmark.json`,
  `docs/async-pipeline-baseline-benchmark.md` (historical, frozen),
  `docs/evidence/async-pipeline-baseline-benchmark.json` (historical,
  frozen)
