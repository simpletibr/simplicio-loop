# Privacy

> What `@wesleysimplicio/llm-project-mapper` collects, when, and how to turn it off.

## TL;DR

- **Default is OFF.** Nothing is sent unless you explicitly opt in.
- **Even when opted in**, no payload is sent unless the environment variable `LLM_PROJECT_MAPPER_TELEMETRY_URL` is set to a HTTPS endpoint. The starter ships no default beacon URL.
- **Strictly anonymous.** No PII, no paths, no project name, no hostname, no username, no git remote, no env vars.
- **One POST per `npx` run**, fire-and-forget with a 1.5s timeout. Failures are silent.

## What is collected (when opted in)

| Field | Example | Why |
|---|---|---|
| `starter_version` | `0.2.2` | Track which version is in use to size deprecations. |
| `stack` | `next-ts`, `dotnet`, `fastapi`, `unknown` | Understand which stacks pick the starter. |
| `project_mode` | `root` or `monorepo` | Verify monorepo detection works in the wild. |
| `preset` | `nextjs` or `null` | See which presets see real use. |
| `node_version` | `22.5.1` | Decide engines minimum bumps. |
| `os` | `linux`, `darwin`, `win32` | Prioritize OS bug fixes. |
| `arch` | `x64`, `arm64` | Same. |
| `cli_runtime` | `@wesleysimplicio/llm-project-mapper` | Distinguish from bash/PowerShell installers if those ever start posting. |
| `timestamp` | ISO 8601 UTC | De-duplicate retries. |

## What is **never** collected

- Product name / `package.json#name`.
- Working directory or any file path.
- Hostname, username, env vars beyond the explicit list above.
- Git remote URL or repository name.
- The contents of `.starter-meta.json` (the file itself is local-only).

## How to opt in / out

Precedence (last wins):

1. Config file `~/.config/llm-project-mapper/telemetry.json` (`{"enabled": true|false}`).
2. Environment variable `LLM_PROJECT_MAPPER_TELEMETRY=on|off|0|1`.
3. CLI flag `--telemetry on|off`.

The flag persists the choice into the config file, so a one-shot `npx ... --telemetry on` is sticky across runs.

### Hard kill switches (always win)

- `CI=true` (or any truthy `CI` env var) — the starter never posts telemetry in CI.
- `--dry-run` — never posts.
- `LLM_PROJECT_MAPPER_TELEMETRY=0|off` — overrides everything except `CI`.
- No `LLM_PROJECT_MAPPER_TELEMETRY_URL` configured — there is nowhere to post to, so nothing is sent.

## Backend

The starter does **not** operate a default telemetry endpoint. If you want to collect aggregate stats from your team's installs, deploy your own endpoint and configure `LLM_PROJECT_MAPPER_TELEMETRY_URL` on each dev machine.

A reference Cloudflare Worker template lives at [`.github/workflows-templates/telemetry-worker.js`](.github/workflows-templates/telemetry-worker.js).

## Source

Telemetry code is small and review-friendly: search `bin/cli.js` for `telemetryEnabled`, `persistTelemetryChoice`, and `maybeSendTelemetry`.
