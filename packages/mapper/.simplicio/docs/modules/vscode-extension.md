# Module: vscode-extension

Groups 9 files across 5 detected layers.

## Structure

- Files: 9
- Layers: asset, code, config, documentation, test
- Entry points: none detected
- Tests: `vscode-extension/test/scan.test.js`

## Files

- `vscode-extension/.gitignore`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: asset
- `vscode-extension/LICENSE`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: asset
- `vscode-extension/README.md`: Documents product, architecture, operation or contributor workflow. Layers: documentation
- `vscode-extension/package-lock.json`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: asset
- `vscode-extension/package.json`: Configures tooling, build, runtime or packaging behavior. Layers: config
- `vscode-extension/src/extension.ts`: Defines exported symbols: SprintNode, SprintsProvider, TaskNode, activate, createAdr. Layers: code
- `vscode-extension/src/scan.ts`: Defines exported symbols: listSprints, readFirstHeading, readStatus, safeRead, statusIcon. Layers: code
- `vscode-extension/test/scan.test.js`: Verifies project behavior through automated tests. Layers: test
- `vscode-extension/tsconfig.json`: Configures tooling, build, runtime or packaging behavior. Layers: config

## Public Symbols

- `SprintNode`
- `SprintsProvider`
- `TaskNode`
- `activate`
- `createAdr`
- `deactivate`
- `getSpecsRoot`
- `getWorkspaceRoot`
- `iconForStatus`
- `listSprints`
- `mkTmp`
- `openCurrentTask`
- `readFirstHeading`
- `readStatus`
- `refreshStatusBar`
- `rmTmp`
- `runInitHandoff`
- `safeRead`
- `statusIcon`
- `statusLabel`
- `writeFile`
