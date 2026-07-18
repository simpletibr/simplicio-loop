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

## Async mapping pipeline (`index`/`map`/`scan`)

- Symptom: a mapper run seems slow/hung, files missing from
  `project-map.json`, a Windows "file still in use" error on
  `.simplicio/cache`, or `asyncio.run() cannot be called from a running
  event loop`.
- Diagnose/fix: see `docs/async-pipeline-operations.md` (config knobs
  `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`/`SIMPLICIO_MAPPER_FILE_TIMEOUT_S`,
  rollback/disable, and a dedicated troubleshooting section for each of
  these symptoms).

## Add Project-Specific Issues

### `<SYMPTOM>`

- Cause: `<CAUSE>`
- Diagnose: `<COMMAND_OR_LOG>`
- Fix: `<FIX>`
