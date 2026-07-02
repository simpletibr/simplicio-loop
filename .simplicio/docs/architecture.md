# @wesleysimplicio/llm-project-mapper Architecture Inventory

Generated from `.simplicio` machine-readable artifacts. Statements below are derived from repository structure, imports, symbols and deterministic heuristics.

## Coverage

- Files: 378
- Modules: 20
- Layers: 10
- Symbols: 914
- Relationships: 1000
- Tests: 70

## Modules

- `.`: 31 files; layers: asset, config, documentation
- `.agents`: 6 files; layers: documentation, ui
- `.claude`: 7 files; layers: asset
- `.codex`: 5 files; layers: asset, config
- `.github`: 21 files; layers: asset, code, documentation, ui
- `.skills`: 46 files; layers: asset, documentation, test, ui
- `.specs`: 19 files; layers: documentation, test
- `READMEs`: 15 files; layers: documentation
- `bin`: 8 files; layers: code, entrypoint
- `docs`: 18 files; layers: documentation, entrypoint
- `docs-site`: 58 files; layers: asset, code, config, documentation
- `examples`: 1 files; layers: asset
- `packaging`: 4 files; layers: code, config, documentation
- `presentation`: 2 files; layers: documentation
- `rust`: 4 files; layers: code, config, documentation
- `scripts`: 17 files; layers: documentation, script, test
- `simplicio_mapper`: 17 files; layers: code, domain, entrypoint, model
- `tests`: 45 files; layers: config, documentation, entrypoint, test
- `video`: 45 files; layers: asset, code, config, documentation, entrypoint, ui
- `vscode-extension`: 9 files; layers: asset, code, config, documentation, test

## Layers

- `asset`: 59 files across 9 modules
- `code`: 55 files across 8 modules
- `config`: 15 files across 8 modules
- `documentation`: 177 files across 15 modules
- `domain`: 1 files across 1 modules
- `entrypoint`: 8 files across 5 modules
- `model`: 1 files across 1 modules
- `script`: 17 files across 1 modules
- `test`: 70 files across 5 modules
- `ui`: 11 files across 4 modules

## Module Dependency Diagram

```mermaid
flowchart TB
  n["."]
  agents[".agents"]
  claude[".claude"]
  codex[".codex"]
  github[".github"]
  skills[".skills"]
  specs[".specs"]
  READMEs["READMEs"]
  bin["bin"]
  docs["docs"]
  docs_site["docs-site"]
  examples["examples"]
  packaging["packaging"]
  presentation["presentation"]
  rust["rust"]
  scripts["scripts"]
  simplicio_mapper["simplicio_mapper"]
  tests["tests"]
  video["video"]
  vscode_extension["vscode-extension"]
  bin --> scripts
  tests -->|5 edges| simplicio_mapper
```

<details><summary>Full list</summary>

- . (`.`)
- .agents (`.agents`)
- .claude (`.claude`)
- .codex (`.codex`)
- .github (`.github`)
- .skills (`.skills`)
- .specs (`.specs`)
- READMEs (`READMEs`)
- bin (`bin`)
- docs (`docs`)
- docs-site (`docs-site`)
- examples (`examples`)
- packaging (`packaging`)
- presentation (`presentation`)
- rust (`rust`)
- scripts (`scripts`)
- simplicio_mapper (`simplicio_mapper`)
- tests (`tests`)
- video (`video`)
- vscode-extension (`vscode-extension`)

</details>


## Top Symbols

- `sanitize` (function) in `.github/workflows-templates/telemetry-worker.js:30`
- `EditError` (class) in `bin/apply-edits.js:50`
- `resolveSafe` (function) in `bin/apply-edits.js:56`
- `readIfExists` (function) in `bin/apply-edits.js:71`
- `requireString` (function) in `bin/apply-edits.js:80`
- `planEdit` (function) in `bin/apply-edits.js:92`
- `computePlan` (function) in `bin/apply-edits.js:103`
- `countOccurrences` (function) in `bin/apply-edits.js:214`
- `replaceN` (function) in `bin/apply-edits.js:226`
- `applyEdits` (function) in `bin/apply-edits.js:252`
- `parseArgs` (function) in `bin/apply-edits.js:308`
- `main` (function) in `bin/apply-edits.js:338`
- `readSafe` (function) in `bin/auto-map.js:22`
- `exists` (function) in `bin/auto-map.js:30`
- `slugify` (function) in `bin/auto-map.js:34`
- `humanizeName` (function) in `bin/auto-map.js:42`
- `safeTitle` (function) in `bin/auto-map.js:51`
- `commandExists` (function) in `bin/auto-map.js:56`
- `walk` (function) in `bin/auto-map.js:63`
- `collectTextFiles` (function) in `bin/auto-map.js:84`
- `parsePackageJson` (function) in `bin/auto-map.js:94`
- `detectPackageManager` (function) in `bin/auto-map.js:102`
- `detectUrls` (function) in `bin/auto-map.js:109`
- `firstDefined` (function) in `bin/auto-map.js:154`
- `inferInstallCommand` (function) in `bin/auto-map.js:161`
- `inferCommands` (function) in `bin/auto-map.js:172`
- `quote` (function) in `bin/auto-map.js:175`
- `inferDatabase` (function) in `bin/auto-map.js:235`
- `inferAuthFlow` (function) in `bin/auto-map.js:245`
- `inferTeam` (function) in `bin/auto-map.js:256`
- `inferDomain` (function) in `bin/auto-map.js:272`
- `getGitRemote` (function) in `bin/auto-map.js:284`
- `collectTopDirectories` (function) in `bin/auto-map.js:298`
- `collectEntities` (function) in `bin/auto-map.js:309`
- `collectFeatures` (function) in `bin/auto-map.js:333`
- `collectTodos` (function) in `bin/auto-map.js:350`
- `collectIntegrations` (function) in `bin/auto-map.js:366`
- `inferSystemType` (function) in `bin/auto-map.js:387`
- `renderVision` (function) in `bin/auto-map.js:394`
- `renderDomain` (function) in `bin/auto-map.js:450`
