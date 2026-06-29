---
title: CLI Flags
description: CLI flags and update mode behavior from the main README.
sidebar_position: 1
---
#### Full flag list

| Flag | Purpose |
|---|---|
| `-y, --yes` | Non-interactive (defaults: no `.gitignore` append, skip CLI handoff) |
| `-f, --force` | Overwrite starter template files. **Never** touches user instruction files (`AGENTS.md`, `CLAUDE.md`, `INIT.md`, `.github/copilot-instructions.md`, `.gitignore`) |
| `--update` | Safe update mode for an existing overlay: force starter files, leave `.gitignore` untouched, skip handoff |
| `--dry-run` | Print actions without writing |
| `--cli <key>` | Pick CLI for `INIT.md` handoff: `claude`, `codex`, `copilot`, `cursor`, `deepseek`, `kimi`, `minimax`, `glm`, `hermes`, `openclaw`, `aider`, `other`, `skip` |
| `--append-gitignore <yes\|no>` | Append recommended ignores to `.gitignore` |
| `--skip-meta` | Do not write `.starter-meta.json` |
| `--silent` | Minimal output |
| `-v, --version` | Print version |
| `-h, --help` | Show help |

##### Python mapper flags

| Flag | Purpose |
|---|---|
| `index <path>` | Scriptable mapper refresh. Returns `0` when updated, already fresh, or locked/skipped; returns `1` on failure |
| `docs <path>` | Render `.simplicio/docs/*.md` from the architecture inventory |
| `export-docs <path> --target <dir>` | Copy rendered Markdown docs to a local docs/wiki target |
| `--docs` | Render Markdown docs after `map` or `index` |
| `--no-docs` | Keep `map` / `index` JSON-only |
| `--docs-only` | Render Markdown docs without emitting the index JSON payload |
| `--json-only` | Compatibility alias for JSON-only refresh workflows |
| `--changed-only` | Compatibility alias for incremental refresh workflows |
| `--background` | Start a detached index refresh and log to `.simplicio/background-index.log` |
| `--json` | Emit stable JSON contracts such as `simplicio.mapper-index/v1` |
| `--update` | Compatibility alias for index refresh workflows |
| `--verbose` | Show index refresh progress |
| `--out <dir>` | Artifact directory, defaulting to `.simplicio` |

#
