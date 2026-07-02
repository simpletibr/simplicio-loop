# Module: scripts

Groups 17 files across 3 detected layers.

## Structure

- Files: 17
- Layers: documentation, script, test
- Entry points: none detected
- Tests: `scripts/test.ps1`, `scripts/test.sh`

## Files

- `scripts/README.md`: Documents product, architecture, operation or contributor workflow. Layers: documentation, script
- `scripts/build_hamt.py`: Defines exported symbols: Leaf, blank_node, build_catalog, canonical_json, finalize. Layers: script
- `scripts/check-placeholders.sh`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/check-version-sync.js`: Defines exported symbols: main, readInitVersion, readPackageVersion, readPyprojectVersion. Layers: script
- `scripts/coverage.js`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/evidence.ps1`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/evidence.sh`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/lint.js`: Defines exported symbols: lintJavaScript, lintJson, lintMarkdown, lintPowerShell, lintShell. Layers: script
- `scripts/render-simplicio-comment.js`: Defines exported symbols: main, readJsonSafe, renderComment, renderDriftSection, renderSyncSection. Layers: script
- `scripts/skillopt/engine.js`: Defines exported symbols: applyEdit, applyEdits, containsDirective, editSignature, escapeRegExp. Layers: script
- `scripts/start.ps1`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/start.sh`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/sync-docs-site.mjs`: Defines exported symbols: copyAssets, ensureDir, extractRange, main, removeDir. Layers: script
- `scripts/test.ps1`: Verifies project behavior through automated tests. Layers: script, test
- `scripts/test.sh`: Verifies project behavior through automated tests. Layers: script, test
- `scripts/update-starter.ps1`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script
- `scripts/update-starter.sh`: Participates in the project implementation; inspect imports and symbols for exact usage. Layers: script

## Public Symbols

- `Leaf`
- `applyEdit`
- `applyEdits`
- `blank_node`
- `build_catalog`
- `canonical_json`
- `containsDirective`
- `copyAssets`
- `editSignature`
- `ensureDir`
- `escapeRegExp`
- `evaluateSplit`
- `extractRange`
- `finalize`
- `hash_hex`
- `heading_anchor`
- `insert_leaf`
- `lintJavaScript`
- `lintJson`
- `lintMarkdown`
- `lintPowerShell`
- `lintShell`
- `log`
- `main`
- `metric`
- `normalize`
- `optimize`
- `parse_agent_terms`
- `parse_agents`
- `parse_args`
- `parse_scalar`
- `readInitVersion`
- `readJsonSafe`
- `readPackageVersion`
- `readPyprojectVersion`
- `reflect`
- `removeDir`
- `renderComment`
- `renderDriftSection`
- `renderSyncSection`
