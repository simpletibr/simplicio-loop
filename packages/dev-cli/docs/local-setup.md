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
