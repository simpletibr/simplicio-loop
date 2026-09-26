# simplicio-mapper

> README globalization release: the GitHub README now ships with 15 language entry points, Star History, ecosystem graph, and a proof-first structure. The package contract below remains the canonical PyPI technical reference.


Python-first project mapper for the Simplicio ecosystem. It scans a repository
and emits machine-readable artifacts that agents and tooling can consume
without parsing the human-readable markdown docs:

- `.simplicio-loop/project-map.json` (`simplicio.project-map/v1`) — file inventory,
  architecture signals, entry points, tests, modules, entities, dependencies
  and recent changes.
- `.simplicio-loop/precedent-index.json` (`simplicio.precedent-index/v1`) —
  high-signal code examples tagged by change type, file, language, roles and
  snippet.
- `.simplicio-loop/architecture-inventory.json`
  (`simplicio.architecture-inventory/v1`) — modules, layers, responsibilities,
  evidence pointers, tests, symbols and relationships.
- `.simplicio-loop/symbol-index.json` (`simplicio.symbol-index/v1`) — detected
  classes, functions, methods and exports with file/line evidence.
- `.simplicio-loop/call-graph.json` (`simplicio.call-graph/v1`) — import and
  heuristic caller/callee relationships with confidence scores.

The full contract is documented in
[SIMPLICIO_INTEGRATION.md](https://github.com/simpletibr/simplicio-loop/blob/main/packages/mapper/SIMPLICIO_INTEGRATION.md).

## Install

Requires Python 3.10+. The package installs lightweight performance dependencies
(`orjson` for JSON serialization and `diskcache` for persistent file-processing cache).

```bash
pip install simplicio-mapper
```

## Usage

```bash
# Map the current directory into .simplicio-loop/
simplicio-mapper map

# Refresh artifacts and record changed files since the last run
simplicio-mapper update

# Idempotent orchestration entry point for SendSprint and other runners
simplicio-mapper index path/to/project --json
simplicio-mapper index --update path/to/project --json

# Compare frontend/API-client calls against runtime server routes
simplicio-mapper endpoints path/to/web --against path/to/api --json

# Render architecture inventory markdown for wiki/docs review
simplicio-mapper docs path/to/project --json
simplicio-mapper export-docs path/to/project --target ./wiki-export --json
simplicio-mapper index path/to/project --docs --background

# Map another project root, with hints when .starter-meta.json is absent
simplicio-mapper map --root path/to/project --stack python --product-name "My App"

# Re-run automatically while files change locally
simplicio-mapper map --watch
```

The `llm-project-mapper` console script is provided as an alias.

### Options

| Option | Description |
|---|---|
| `index <path>` | Scriptable index command. Returns `0` when refreshed or already fresh, `1` on failure. Quiet by default. |
| `endpoints <path>` | Extract normalized client calls and server routes, including Python API clients, direct page-level Python calls and Angular HttpClient services. Use `--against <server-root>` to report `missing_from_server` with source files using schema `simplicio.endpoint-inventory/v1`. |
| `docs <path>` | Render architecture inventory Markdown under `.simplicio-loop/docs/`. |
| `export-docs <path>` | Copy rendered Markdown docs to a local target directory. Remote publication is intentionally opt-in and not automatic. |
| `--against <dir>` | Server/API project root for endpoint comparison. |
| `--target <dir>` | Local target directory for `export-docs`. |
| `--docs` | Render Markdown docs after `map` or `index`. |
| `--no-docs` | Keep `map`/`index` JSON-only. |
| `--docs-only` | Render the Markdown docs without emitting the index JSON payload. |
| `--json-only` | Compatibility alias for keeping `map`/`index` JSON-only. |
| `--changed-only` | Compatibility alias for incremental refresh workflows. |
| `--background` | Start a detached index refresh and write `.simplicio-loop/background-index.log`. |
| `--json` | Emit stable `simplicio.mapper-index/v1` output for the `index` command. |
| `--update` | Compatibility alias for index refresh workflows. |
| `--verbose` | Show progress during `index` refreshes. |
| `--root <dir>` | Project root to map. Defaults to the current directory. |
| `--out <dir>` | Artifact directory. Defaults to `.simplicio-loop`. |
| `--stack <name>` | Stack hint when `.starter-meta.json` is absent. |
| `--product-name <name>` | Product name hint when `.starter-meta.json` is absent. |
| `--incremental` | Record changed files and update existing artifacts. |
| `--watch` | Re-run mapping when local files change. |
| `--silent` | Minimal output. |
| `-V`, `--version` | Show version and exit. |
| `-h`, `--help` | Show help. |

## Consuming the artifacts

```python
from pathlib import Path
import json

base = Path(".simplicio-loop")
project_map = json.loads((base / "project-map.json").read_text())
precedents = json.loads((base / "precedent-index.json").read_text())

top_files = sorted(
    project_map["files"], key=lambda f: f.get("importance", 0), reverse=True
)[:8]
```

## License

MIT
