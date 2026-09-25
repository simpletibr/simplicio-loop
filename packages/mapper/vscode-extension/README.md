# LLM Project Mapper · VS Code extension

> Sidebar TreeView + commands that surface `.specs/sprints/`, `.skills/` and `.agents/` in VS Code, plus quick actions to open the current task, create ADRs and run the `INIT.md` handoff.

## Features

| Feature | What it does |
|---|---|
| **Sprints TreeView** | Activity-bar icon shows every `.specs/sprints/sprint-XX/` with each `*.task.md` and a status icon (todo/doing/done). |
| **Open current task** | Finds the sprint with `status: doing` (or last sprint) and opens its `doing` task. Bound to the status-bar entry. |
| **Create ADR wizard** | Prompts for a slug, copies `ADR-template.md` to `ADR-NNN-<slug>.md` with the next auto-incremented number, opens it for editing. |
| **Run INIT.md handoff** | Spawns a terminal at the workspace root and runs your chosen CLI (`claude`, `codex`, `copilot`, `cursor`, `aider`) with `INIT.md` piped in. |
| **Status bar** | Live "Sprint 02 · 03-task.task.md" indicator that refreshes whenever `.specs/sprints/**` changes on disk. |

## Activation

Activates automatically when the workspace contains either:

- `.starter-meta.json` (the file the starter writes after bootstrap), or
- any file under `.specs/sprints/`.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `lpm.defaultCli` | `claude` | CLI used by the "Run INIT.md handoff" command. |
| `lpm.specsRoot` | `.specs` | Path (relative to workspace root) of the specs folder. |

## Repository note

This folder is the source tree that will eventually become its own repo
(`wesleysimplicio/llm-project-mapper-vscode`) and be published to the VS Code
Marketplace. While it lives here, devs can clone the monorepo and run the
extension from source:

```bash
cd vscode-extension
npm install
npm run compile
# then press F5 inside VS Code to launch the Extension Development Host
```

## Build

```bash
cd vscode-extension
npm install
npm run compile      # tsc -p ./  → out/
npm test             # node --test test/  (skipped when out/ is empty)
```

The `out/` folder is gitignored — `package.json` `files[]` will be set when the
extension moves to its own repo for publishing.
