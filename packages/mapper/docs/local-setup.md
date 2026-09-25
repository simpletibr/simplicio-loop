# Local Setup

Use this file to make local execution reproducible for humans and agents.

## Prerequisites

- Runtime: `<NODE_DOTNET_PYTHON_GO_JAVA_VERSION>`
- Package manager: `<NPM_PNPM_YARN_NUGET_PIP_POETRY>`
- Database: `<DATABASE_REQUIREMENT>`
- External access: `<VPN_OR_NONE>`
- Secrets: `<WHERE_TO_GET_ENV_VARS>`

## Environment Variables

| Variable | Required | Example | Notes |
|---|---:|---|---|
| `<ENV_NAME>` | yes | `<VALUE>` | `<NOTES>` |
| `SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES` | no | `8` | Caps in-flight file read+parse tasks in the async mapping pipeline (`index`/`map`/`scan`). Default `min(64, os.cpu_count() * 4)`. See `docs/async-pipeline-operations.md`. |
| `SIMPLICIO_MAPPER_FILE_TIMEOUT_S` | no | `10` | Per-file timeout (seconds) for the async mapping pipeline; a file exceeding it is recorded as `degraded` and skipped, run continues. Default `30.0`. See `docs/async-pipeline-operations.md`. |
| `SIMPLICIO_MAPPER_EXECUTION_PROFILE` | no | `auto` | Adaptive mapper pipeline profile. Supported local values today: `auto`, `sync`, `async`; reserved future values `thread`, `process`, `hub` fall back deterministically to `auto`. |
| `SIMPLICIO_MAPPER_NO_ASYNC_PIPELINE` | no | `1` | Operational rollback kill switch: forces the safe synchronous mapper pipeline even when calibration/env would select async. |

## Install

```bash
<INSTALL_COMMAND>
```

## Start

```bash
./scripts/start.sh
# or
./scripts/start.ps1
```

Expected services:

| Service | URL | Health check |
|---|---|---|
| Frontend | `<FRONTEND_URL>` | `<FRONTEND_HEALTH>` |
| Backend | `<BACKEND_URL>` | `<BACKEND_HEALTH>` |

## Validate

```bash
./scripts/test.sh
# or
./scripts/test.ps1
```

## Demo Access

- Flow: `<AUTH_FLOW>`
- Demo user: `<DEMO_USER_OR_NONE>`
- Demo password location: `<PASSWORD_LOCATION_OR_NONE>`

Do not commit real credentials. If demo credentials are required, point to the internal safe location.

## Evidence

```bash
BASE_URL=<FRONTEND_URL> ./scripts/evidence.sh
# or
$env:BASE_URL="<FRONTEND_URL>"; ./scripts/evidence.ps1
```
