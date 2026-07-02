# Module: packaging

Groups 4 files across 3 detected layers.

## Structure

- Files: 4
- Layers: code, config, documentation
- Entry points: none detected
- Tests: none detected

## Files

- `packaging/npm/README.md`: Documents product, architecture, operation or contributor workflow. Layers: documentation
- `packaging/npm/bin/simplicio-mapper.js`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: code
- `packaging/npm/lib/python-shim.js`: Defines exported symbols: ensureAndRun, ensureInstalled, ensureVirtualenv, entrypointCandidates, findPython. Layers: code
- `packaging/npm/package.json`: Configures tooling, build, runtime or packaging behavior. Layers: config

## Public Symbols

- `ensureAndRun`
- `ensureInstalled`
- `ensureVirtualenv`
- `entrypointCandidates`
- `findPython`
- `probe`
- `resolveEntrypoint`
- `run`
- `sanitizePackageName`
- `venvPython`
- `venvRoot`
