# Simplicio Integration Contract

This contract defines the machine-readable outputs that `simplicio-dev-cli`,
`simplicio-sprint`, and other tools can consume without depending on the
markdown starter docs.

## Artifact Locations

Default output directory: `.simplicio/`

| Artifact | Schema | Purpose |
|---|---|---|
| `.simplicio/project-map.json` | `simplicio.project-map/v1` | File inventory, architecture signals, entry points, tests, modules, entities, dependencies, recent changes |
| `.simplicio/precedent-index.json` | `simplicio.precedent-index/v1` | High-signal examples tagged by change type, file, language, roles, and snippet |

Generate or refresh them with:

```bash
npx @wesleysimplicio/llm-project-mapper map
npx @wesleysimplicio/llm-project-mapper map --incremental
npx @wesleysimplicio/llm-project-mapper update
simplicio-mapper index --update . --json
```

Use `--watch` for local live updates during longer agent sessions.

## endpoint-inventory.json

Endpoint inventory is emitted on demand, not written into `.simplicio/` by
default:

```bash
simplicio-mapper endpoints ./web --against ./api --json
```

The command returns `simplicio.endpoint-inventory/v1` with:

- `client_calls`: normalized HTTP calls found in frontend/API-client code.
  Python API clients and Angular HttpClient services are supported, including
  direct page calls (`api.patch(...)`, `api._client.put(...)`), `baseUrl`,
  `environment.apiUrl`, and template-string path parameters. Test files and
  route decorators are excluded from client demand.
- `server_routes`: normalized runtime and contract route declarations.
- `counts.runtime_server_routes`: routes mounted by runtime handlers such as
  Azure Functions `HttpTrigger`.
- `counts.contract_routes`: documentation-only declarations such as
  `OpenApiContractControllerBase` controllers.
- `missing_from_server`: client method+path pairs absent from runtime server
  routes.

Consumers should use `missing_from_server` for delivery planning and keep
`contract_routes` as context only unless the target project uses controllers as
runtime handlers.

## project-map.json

Required top-level fields:

```json
{
  "schema": "simplicio.project-map/v1",
  "version": 1,
  "generated_at": "2026-05-27T00:00:00.000Z",
  "update_mode": "full",
  "product": {
    "name": "Example App",
    "stack": "node-react",
    "project_mode": "root"
  },
  "files": [],
  "entry_points": [],
  "test_files": [],
  "config_files": [],
  "modules": [],
  "entities": [],
  "architecture": {
    "signals": [],
    "system_type": "library-or-service"
  },
  "dependencies": {
    "package_manager": "npm",
    "manifest": "package.json",
    "runtime": [],
    "dev": []
  },
  "recent_changes": [],
  "changed_files": [],
  "integration": {
    "dev_cli_mapper": "read .simplicio/project-map.json, then use .simplicio/precedent-index.json for task-specific examples",
    "contract": "SIMPLICIO_INTEGRATION.md"
  }
}
```

Each `files[]` entry is deterministic by `path` and includes:

- `path`
- `language`
- `size_bytes`
- `last_modified`
- `file_hash`
- `git_status`
- `roles`
- `imports`
- `exports`
- `importance`

Consumers should sort or filter by `importance`, `roles`, exact target path,
and `changed_files` before injecting context into an LLM prompt.

## precedent-index.json

Required top-level fields:

```json
{
  "schema": "simplicio.precedent-index/v1",
  "version": 1,
  "source_project_map": ".simplicio/project-map.json",
  "items": []
}
```

Each `items[]` entry includes:

- `id`
- `path`
- `line`
- `language`
- `change_type`
- `tags`
- `summary`
- `snippet`

Consumers should rank by task-token overlap against `summary`, `tags`, `path`,
and `change_type`, then inject only the top few snippets.

## Python Consumer Example

```python
from pathlib import Path
import json

def load_simplicio_context(root: str, target: str):
    base = Path(root) / ".simplicio"
    project_map = json.loads((base / "project-map.json").read_text())
    precedent_index = json.loads((base / "precedent-index.json").read_text())

    files = project_map.get("files", [])
    exact = [f for f in files if f.get("path") == target]
    relevant = exact or sorted(files, key=lambda f: f.get("importance", 0), reverse=True)[:8]
    precedents = precedent_index.get("items", [])[:3]

    return {
        "target": target,
        "files": relevant,
        "architecture": project_map.get("architecture", {}),
        "precedents": precedents,
    }
```

## Backward Compatibility

The JSON artifacts are additive. Existing markdown docs in `.specs/`, `docs/`,
and agent instruction files remain the human-readable source for project
operation. If `.simplicio/` is absent, consumers should fall back to the current
markdown or file-inspection behavior.
