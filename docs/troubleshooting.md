# Troubleshooting

Use this file to capture repeatable fixes. Prefer concrete commands and log paths.

## Port Already In Use

- Symptom: app fails to bind `<PORT>`.
- Diagnose: list processes listening on the port.
- Fix: stop the previous local server or change the configured port.

## Database Connection Fails

- Symptom: startup or tests fail while connecting to `<DATABASE_REQUIREMENT>`.
- Diagnose: verify VPN/network, host, credentials, migrations and seed data.
- Fix: connect required network, start local database, or update environment variables.

## Authentication Fails

- Symptom: redirect loop, 401/403, callback error, missing user profile.
- Diagnose: confirm `<AUTH_FLOW>`, redirect URI, client id, cookies and local HTTPS.
- Fix: update auth config or use documented demo flow.

## Frontend Calls Wrong API

- Symptom: UI loads but data comes from another environment or fails.
- Diagnose: inspect frontend config and server logs.
- Fix: set API URL to `<BACKEND_URL>` for local execution.

## Build Fails With Locked Files

- Symptom: compiler cannot copy or overwrite build artifacts.
- Diagnose: a local server or compiler process is holding the file.
- Fix: stop the running app, shut down build servers, then rebuild.

## Playwright Browser Or FFmpeg Missing

- Symptom: E2E fails before opening the page or video cannot be recorded.
- Diagnose: check Playwright install output.
- Fix:

```bash
npx playwright install
npx playwright install ffmpeg
```

## Async mapping pipeline (`AsyncMappingPipeline`, ADR-009, `index`/`map`/`scan`)

Full operational guide: `docs/async-pipeline-operations.md` (config knobs
`SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`/
`SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`/`SIMPLICIO_MAPPER_FILE_TIMEOUT_S`,
uvloop, Windows fallback, cancellation/backpressure, rollback/disable).
Quick index of symptoms below; that file has the diagnose/fix detail for
each.

### File Missing From `project-map.json`, Listed In `degraded.timed_out_files`

- Cause: per-file read+parse exceeded `SIMPLICIO_MAPPER_FILE_TIMEOUT_S`
  (default 30s) -- stalled filesystem or genuine I/O starvation.
- Diagnose: re-run with a higher `SIMPLICIO_MAPPER_FILE_TIMEOUT_S`.
- Fix: raise the timeout for that environment, or fix the slow filesystem.

### Run Seems Slow/Hung, Or Uses More Memory Than The Published Benchmark

- Cause: host core count drives the default concurrency cap
  (`min(32, os.cpu_count() * 4)`), so a higher-core host uses more
  concurrent file handles. Normal `auto` runs use the async path at every
  repository size; confirm the execution receipt before assuming a hang.
- Diagnose: compare `os.cpu_count()` to the benchmark host in
  `docs/async-pipeline-after-benchmark.md`; check
  `.simplicio/project-map.json`'s `degraded` object.
- Fix: lower `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`, or make one explicit
  diagnostic/rollback run with `SIMPLICIO_MAPPER_EXECUTION_PROFILE=sync`.

### Bounded `scan --sync` Times Out On A Large Repository

- The timeout receipt is resumable. Inspect
  `.simplicio/partial-scan.json` and `.simplicio/index-state.json`; both
  report `completeness=partial`, measured discovered/processed counts,
  elapsed time, and `eta_seconds=null` with a reason when no defensible ETA
  exists.
- Re-run the same command. A partial checkpoint automatically enables the
  incremental path, which reuses `FileProcessingCache` entries for unchanged
  files instead of discarding completed work. `deep.resuming=true` proves
  that the continuation path was selected.
- Generated/vendor directories in `SKIP_DIRS` (`node_modules`, `.git`,
  common build/cache outputs) are excluded automatically. For generated
  source that must remain visible, control pressure with
  `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`; use
  `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` for slow individual files.
- Never delete `index.lock` while `status.lock_status` reports a live owner.
  The Mapper only reclaims it after PID/start identity proves death,
  including on Windows.

### `.simplicio/cache/` Locked Or "File Still In Use" Right After A Run

- Cause: almost always an external process (editor, AV scanner, a
  previous still-running mapper process) holding the SQLite file, not the
  pipeline itself -- `async_pipeline.py` explicitly closes its per-thread
  cache connection right after each file.
- Diagnose: check for other handles on `.simplicio/cache/*.db`.
- Fix: close the other handle, or delete `.simplicio/cache/` (safe,
  cache-only, rebuilds automatically).

### `RuntimeError: asyncio.run() cannot be called from a running event loop`

- Cause: calling the sync `build_artifacts()` from code already inside an
  event loop, on a run that took the async path.
- Fix: `await build_artifacts_async(...)` directly instead of the sync
  wrapper.

## Stale global `simplicio-mapper` install after a release

- Symptom: a checkout contains a mapper fix, but `simplicio-loop` or an
  operator shell still runs an older globally installed mapper (for issue
  #233, `simplicio-mapper --version` returned `0.23.1` even though the
  timeout fix from PR #232 was already merged on `main`).
- Diagnose: compare all three version sources and the executable location:

```bash
simplicio-mapper --version
python -m pip show simplicio-mapper
python -c "import shutil; print(shutil.which('simplicio-mapper'))"
python -c "from importlib.metadata import version; print(version('simplicio-mapper'))"
```

- Fix: upgrade or force-reinstall the published mapper version that contains
  the fix, then rerun the same probes from the environment that launches the
  Loop:

```bash
python -m pip install --upgrade simplicio-mapper==0.24.1
# If the environment was pinned or shadowed by an older install:
python -m pip install --force-reinstall simplicio-mapper==0.24.1
```

- Verify the issue #233 timeout fix behaviorally with a real bounded scan:
  `simplicio-mapper scan <repo> --json --sync --timeout <n>` must return
  within `timeout + operational margin`; a timeout path emits
  `"phase":"timeout"`, `"failure_reason":"scan_timeout"`,
  `"exit_code":1`, and a follow-up `simplicio-mapper status <repo> --json`
  reports `"lock":false`. A normal scan should emit `"phase":"complete"`
  and the follow-up status should report `"terminal":true`, `"fresh":true`,
  `"lock":false`, `"warnings":[]`.

## Add Project-Specific Issues

### `<SYMPTOM>`

- Cause: `<CAUSE>`
- Diagnose: `<COMMAND_OR_LOG>`
- Fix: `<FIX>`
