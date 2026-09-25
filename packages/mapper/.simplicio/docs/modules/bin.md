# Module: bin

Groups 8 files across 2 detected layers.

## Structure

- Files: 8
- Layers: code, entrypoint
- Entry points: `bin/apply-edits.js`, `bin/build-hamt-catalog`, `bin/cli.js`, `bin/skillopt.js`
- Tests: none detected

## Files

- `bin/apply-edits.js`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint
- `bin/auto-map.js`: Defines exported symbols: collectEntities, collectFeatures, collectIntegrations, collectTextFiles, collectTodos. Layers: code
- `bin/build-hamt-catalog`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint
- `bin/cli.js`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint
- `bin/hook-runner.js`: Defines exported symbols: runHook. Layers: code
- `bin/map.js`: Defines exported symbols: parseArgs, printHelp, readJsonSafe, runMapCli, runOnce. Layers: code
- `bin/mapper-artifacts.js`: Defines exported symbols: buildArchitectureInventory, buildArtifacts, buildCallGraph, buildFileInventory, buildPrecedentItems. Layers: code
- `bin/skillopt.js`: Starts a CLI, runtime or package entrypoint. Layers: entrypoint

## Public Symbols

- `EditError`
- `addEdge`
- `applyEdits`
- `ask`
- `autoMapProject`
- `buildArchitectureInventory`
- `buildArtifacts`
- `buildCallGraph`
- `buildFileInventory`
- `buildPrecedentItems`
- `buildProfile`
- `buildProjectsList`
- `buildSymbolIndex`
- `callExpressions`
- `candidateImportTargets`
- `chooseCli`
- `collectArchitectureSignals`
- `collectCorpus`
- `collectEntities`
- `collectFeatures`
- `collectIntegrations`
- `collectTextFiles`
- `collectTodos`
- `collectTopDirectories`
- `commandExists`
- `computePlan`
- `copyTemplate`
- `copyToClipboard`
- `countAcceptedEdits`
- `countOccurrences`
- `defaultPersonas`
- `detectChangedFiles`
- `detectExistingInstructionFiles`
- `detectPackageManager`
- `detectPreservedUserFiles`
- `detectProductNameIn`
- `detectProjectMode`
- `detectStack`
- `detectStackIn`
- `detectUrls`
