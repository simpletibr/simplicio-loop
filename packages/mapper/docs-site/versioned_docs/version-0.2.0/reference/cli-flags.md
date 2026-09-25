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
| `--update` | Safe update mode for an existing overlay: force starter files, update `.gitignore`, skip handoff |
| `--dry-run` | Print actions without writing |
| `--cli <key>` | Pick CLI for `INIT.md` handoff: `claude`, `codex`, `copilot`, `cursor`, `deepseek`, `kimi`, `minimax`, `glm`, `hermes`, `openclaw`, `aider`, `other`, `skip` |
| `--append-gitignore <yes\|no>` | Append recommended ignores to `.gitignore` |
| `--skip-meta` | Do not write `.starter-meta.json` |
| `--silent` | Minimal output |
| `-v, --version` | Print version |
| `-h, --help` | Show help |
