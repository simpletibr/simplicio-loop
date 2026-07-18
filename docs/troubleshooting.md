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

## Async mapping pipeline (`AsyncMappingPipeline`, ADR-009)

Full operational guide: `docs/async-pipeline-operations.md` (env vars,
uvloop, Windows fallback, cancellation/backpressure, rollback). Quick
index of symptoms below; that file has the diagnose/fix detail.

### File Missing From `project-map.json`, Listed In `degraded.timed_out_files`

- Cause: per-file read+parse exceeded `SIMPLICIO_MAPPER_FILE_TIMEOUT_S`
  (default 30s) -- stalled filesystem or genuine I/O starvation.
- Diagnose: re-run with a higher `SIMPLICIO_MAPPER_FILE_TIMEOUT_S`.
- Fix: raise the timeout for that environment, or fix the slow filesystem.

### Run Slower Or Uses More Memory Than The Published Benchmark

- Cause: host core count drives the default concurrency cap
  (`min(32, os.cpu_count() * 4)`), so a higher-core host uses more
  concurrent file handles.
- Diagnose: compare `os.cpu_count()` to the benchmark host in
  `docs/async-pipeline-after-benchmark.md`.
- Fix: lower `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`.

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
  event loop.
- Fix: `await build_artifacts_async(...)` directly instead of the sync
  wrapper.

## Add Project-Specific Issues

### `<SYMPTOM>`

- Cause: `<CAUSE>`
- Diagnose: `<COMMAND_OR_LOG>`
- Fix: `<FIX>`
