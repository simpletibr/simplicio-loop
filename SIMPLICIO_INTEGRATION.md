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
| `.simplicio/architecture-inventory.json` | `simplicio.architecture-inventory/v1` | Living module/layer inventory with responsibilities, evidence, tests, symbols, and relationships |
| `.simplicio/symbol-index.json` | `simplicio.symbol-index/v1` | Detected classes, functions, methods, exports, file and line evidence |
| `.simplicio/call-graph.json` | `simplicio.call-graph/v1` | Import and heuristic caller/callee relationships with confidence scores |
| `.simplicio/docs/*.md` | `simplicio.architecture-docs/v1` | Human-readable Markdown derived from the JSON artifacts for wiki/docs review |

Generate or refresh them with:

```bash
npx @wesleysimplicio/llm-project-mapper map
npx @wesleysimplicio/llm-project-mapper map --incremental
npx @wesleysimplicio/llm-project-mapper update
simplicio-mapper index --update . --json
simplicio-mapper docs . --json
simplicio-mapper export-docs . --target ./wiki-export --json
simplicio-mapper index . --docs --background
```

Use `--watch` for local live updates during longer agent sessions.
Use `--docs` with `map` or `index` when the markdown wiki view should be
refreshed in the same run. Use `--background` when the refresh should continue
without blocking the foreground workflow; concurrent refreshes are guarded by
`.simplicio/index.lock`. Use `--docs-only` for Markdown-only regeneration, and
the compatibility aliases `--json-only` / `--changed-only` when orchestrators
need those explicit modes.

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
  routes, including `sources` with the client/page files that require them.

Consumers should use `missing_from_server` for delivery planning and keep
`contract_routes` as context only unless the target project uses controllers as
runtime handlers.

### Endpoint path normalization

Both `client_calls` and `server_routes` paths are normalized by a small set of
project-agnostic rules:

- query strings (`?...`) are stripped;
- a leading slash is inserted when missing and duplicate slashes are collapsed;
- placeholder segments such as `${foo}` and `{foo}` collapse to `{id}`;
- UUIDv4-shaped segments collapse to `{id}`;
- pure-numeric segments (e.g. `/users/42`) collapse to `{id}`.

Slug segments that do not match any of the rules above are left as-is. If a
project needs collection-specific collapsing (e.g. `/projects/<slug>` → `{id}`),
emit the route from the upstream client with a placeholder (`${projectId}`) or a
numeric example so the normalizer can recognize it; the mapper itself no longer
embeds project-specific resource names.

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

## architecture-inventory.json

Required top-level fields:

```json
{
  "schema": "simplicio.architecture-inventory/v1",
  "version": 1,
  "source_project_map": ".simplicio/project-map.json",
  "source_symbol_index": ".simplicio/symbol-index.json",
  "source_call_graph": ".simplicio/call-graph.json",
  "modules": [],
  "layers": [],
  "files": [],
  "relationships": [],
  "coverage": {}
}
```

This artifact is evidence-first. Module and layer entries point back to real
files, and relationship entries carry a `confidence` score. Consumers should
treat confidence below `1.0` as useful routing context, not proof.

## symbol-index.json and call-graph.json

`symbol-index.json` records detected symbols with:

- `name`
- `qualified_name`
- `kind`
- `language`
- `defined_in`
- `line`
- `evidence`

`call-graph.json` records two relationship types:

- `imports`: file-to-file dependencies resolved from local imports.
- `calls`: heuristic caller/callee links between files and symbols.

These artifacts intentionally prefer conservative, reviewable evidence over
LLM-generated prose. Missing or ambiguous relationships should be treated as
unknown rather than absent.

## Markdown docs

Render human-readable docs from the JSON artifacts:

```bash
simplicio-mapper docs . --json
simplicio-mapper index . --docs --json
simplicio-mapper index . --docs --background
simplicio-mapper index . --docs-only --json
simplicio-mapper export-docs . --target ./wiki-export --json
```

Generated files live under `.simplicio/docs/` by default:

- `architecture.md`
- `layers.md`
- `call-graph.md`
- `modules.md`
- `modules/<module>.md`

Remote publication is deliberately not automatic. Exporting to a GitHub Wiki,
Docusaurus tree, Obsidian vault, or another docs target should be a separate
explicit step.

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

## Mechanical Edit Contract (issue #110)

Schema: `simplicio.mechanical-edit/v1` (envelope) and
`simplicio.mechanical-edit-result/v1` (executor result). The canonical
contract lives in
[`simplicio-runtime#69`](https://github.com/wesleysimplicio/simplicio-runtime/issues/69);
this repository implements the **producer half** so an LLM planner can
plan compact JSON edits without rewriting whole files.

### What the mapper produces

Use `simplicio_mapper.mechanical_edit.build_context(root, selections)` to
build a context envelope:

```python
from simplicio_mapper.mechanical_edit import build_context

envelope = build_context(
    root=".",
    selections=[
        ("simplicio_mapper/mapper.py", 99, 102),
        ("simplicio_mapper/mapper.py", 180, 199),
        ("simplicio_mapper/cli.py", 1, 20),
    ],
)
```

The returned dict matches:

```json
{
  "schema": "simplicio.mechanical-edit/v1",
  "context": {
    "mapper_schema": "simplicio.mapper-index/v1",
    "context_hash": "<sha256 of all per-file snapshot+range hashes>",
    "files": [
      {
        "path": "simplicio_mapper/cli.py",
        "language": "python",
        "snapshot_hash": "<sha256 of the whole file>",
        "selected_ranges": [
          {
            "start_line": 1,
            "end_line": 20,
            "before_hash": "<sha256 of the 1..20 slice>",
            "must_contain": [
              "\"\"\"Command-line entry point for simplicio-mapper.",
              "from .mapper import write_mapping_artifacts"
            ]
          }
        ]
      }
    ]
  }
}
```

### Guarantees

- **Stable.** Identical `(path, start, end)` selections on an unchanged tree
  always produce the same `snapshot_hash`, `before_hash`, and overall
  `context_hash`. The test suite enforces this across repeated runs.
- **Drift-detecting.** A consumer that captured a `before_hash` will see a
  different value if the file changes underneath; the executor rejects the
  edit when the anchor no longer matches.
- **Refuses unsafe inputs.** Missing files raise `FileNotFoundError`;
  binary files (NUL byte in the first 8 KiB or non-UTF-8 decode) raise
  `ValueError`. The mapper never silently emits an ambiguous anchor — the
  caller must either widen the snapshot or hand off a different file.
- **Compact above threshold.** Files longer than
  `COMPACT_LINE_THRESHOLD` (2000 lines by default) omit `must_contain`
  snippets so the envelope stays small; the `before_hash` is still
  emitted, which is enough for the executor to anchor.
- **Language-aware.** `language` follows the same detection used by
  `project-map.json` (`typescript`, `python`, `json`, `markdown`, etc.).
- **Canonical schema only.** This module must not introduce a repo-local
  variation. The contract is owned by
  [`simplicio-runtime#69`](https://github.com/wesleysimplicio/simplicio-runtime/issues/69).

### Fixtures

`tests/fixtures/mech-edit-host/` ships small deterministic files in four
text languages (`sample.ts`, `sample.py`, `sample.json`, `sample.md`) plus
a binary file (`binary.bin`) used by the refusal test. Producers in
downstream repositories can copy these as ready-made parity inputs.

## Native Runtime Contract (issue #95)

The unified native Simplicio runtime — coordinating
`simplicio-mapper` + `simplicio-dev-cli` + `simplicio-prompt` +
`simplicio-sprint` + a local LLM (`llama.cpp` / GGUF) as a single local
program — depends on this repository for the **fast context layer**.
Everything in this section is a stable contract: a breaking change requires a
schema bump and an ADR.

### Commands and `--json` payloads

| Command | Path | JSON schema | Stable fields |
|---|---|---|---|
| `simplicio-mapper index <path> --json` | stdout | `simplicio.mapper-index/v1` | `status`, `fingerprint`, `project_map_path`, `precedent_path`, `file_count`, `precedent_count`, `duration_ms`, `error?`, `skipped_reason?` |
| `simplicio-mapper map [--root <dir>] [--json]` | stdout when `--json` | mirrors the index payload above | same — emit the same shape so orchestrators do not branch on command name |
| `simplicio-mapper update [--root <dir>] [--json]` | stdout when `--json` | mirrors the index payload above | same |
| `simplicio-mapper endpoints <path> --against <root> --json` | stdout | `simplicio.endpoint-inventory/v1` | `schema`, `counts.client_calls`, `counts.server_routes`, `client_calls[]`, `server_routes[]`, `missing_from_server[]` |
| `simplicio-mapper screens <path> --json` | stdout | `simplicio.screen-inventory/v1` | `schema`, `routes[]`, `personas[]`, `guards[]` |
| `simplicio-mapper docs <path> --json` | stdout | `simplicio.architecture-docs/v1` envelope | `docs_root`, `counts.files`, `files[].path`, `files[].kind` |
| `simplicio-mapper export-docs <path> --target <dir> --json` | stdout | same envelope as `docs` plus `target` | `target`, `docs_root`, `counts.files` |
| `simplicio-mapper docs <path>` (no `--json`) | `.simplicio/docs/*.md` | `simplicio.architecture-docs/v1` markdown | `architecture.md`, `layers.md`, `call-graph.md`, `modules.md`, `modules/<module>.md` |
| `simplicio-mapper index|map|update --docs-only` | `.simplicio/docs/*.md` | same markdown set | renders without rewriting JSON; useful for refresh-only-docs flows |
| `simplicio-mapper index|map|update --background` | `.simplicio/background-index.log` | best-effort log | detached refresh; lock-guarded against the foreground |

All `--json` outputs are single-line JSON (no trailing newline beyond the
final `\n` from `print`). The native runtime should consume them with
`json.loads(stdout.strip())`.

### Exit codes (orchestration contract)

| Code | Meaning |
|---|---|
| `0` | Wrote or refreshed artifacts, or an `index` run found state already-fresh and reused it (per CHANGELOG `0.6.4`). |
| `1` | Failure. JSON `status="failed"` and a non-empty `error` string are emitted when `--json` is set. |
| `2` | Skipped: fingerprint matched and artifacts were present, no work needed. The native runtime should treat exit 2 as a successful no-op, not an error. |

### Lock and cache behavior for concurrent agents

The native runtime fans out many local logical agents that may all want to
read the same `.simplicio/` artifacts. The mapper guarantees:

- **Foreground vs background refresh exclusion.** `simplicio-mapper index`
  (and its `map` / `update` aliases) takes an exclusive lock at
  `.simplicio/index.lock` for the duration of a refresh. When another refresh
  is already running, the call returns immediately with exit `0`,
  `status="skipped"`, and `skipped_reason="locked"` (CHANGELOG `0.7.1`).
  Consumers should retry after observing the locked status rather than block.
- **Atomic artifact writes.** All JSON artifacts are written via
  temp-file + atomic rename (CHANGELOG `0.7.0`), so concurrent readers always
  see a consistent file — never a partially written JSON.
- **Per-file cache.** Heavy per-file work (hashing, role detection, import
  parsing) is memoized in `.simplicio/cache/` via `diskcache`. The cache key
  combines `path`, `size_bytes`, and `mtime_ns`, so external edits
  invalidate naturally.
- **Cross-process safety.** `diskcache` uses SQLite under the hood; the
  mapper does not add a second lock. Multiple readers of the JSON artifacts
  are safe with no coordination.

### Changed-file incremental refresh

Two equivalent invocation styles exist for the same code path:

```bash
simplicio-mapper map --incremental    # canonical
simplicio-mapper map --changed-only   # orchestrator-facing alias
simplicio-mapper update               # legacy alias, equivalent to --incremental
```

The incremental refresh only re-emits `files[]` and `precedents[]` entries
whose `(path, size, mtime)` triple changed; the rest of the artifact is
preserved from the previous run. The schema, ordering, and importance scoring
remain identical to a full refresh — only the cost changes.

### Timing and cache stats

The `index` command emits `duration_ms` in every JSON payload (wrote /
skipped / failed). The native runtime can use it to:

- detect cold-start regressions on a per-repo basis (compare `duration_ms`
  for `status="wrote"` against rolling baselines);
- attribute token / time savings against a baseline that doesn't use the
  mapper at all;
- decide whether to fan out to background refresh based on observed
  foreground cost.

Per-artifact write counts are exposed under `counts.*` for the
`endpoints` / `screens` / `docs` commands. The `index` payload's
`file_count` and `precedent_count` provide an equivalent dimension for the
main mapping pipeline.

### Stability guarantees

- All schemas (`simplicio.project-map/v1`, `simplicio.precedent-index/v1`,
  `simplicio.architecture-inventory/v1`, `simplicio.symbol-index/v1`,
  `simplicio.call-graph/v1`, `simplicio.endpoint-inventory/v1`,
  `simplicio.screen-inventory/v1`, `simplicio.mapper-index/v1`,
  `simplicio.mapper-index-state/v1`) are SemVer-locked: additive fields are
  allowed inside `v1`; renames and removals require `v2` plus an ADR.
- `simplicio-mapper --version` is sourced from `package.json`,
  `pyproject.toml`, and `simplicio_mapper.__version__` simultaneously and
  verified in CI by `scripts/check-version-sync.js`.
- The Node mapper at `bin/cli.js` and the Python mapper at
  `simplicio_mapper.mapper` are kept in parity by
  `tests/python/test_parity.py` (issue #98). Any heuristic divergence is a
  bug.

### Native runtime adoption checklist

When integrating from the unified runtime:

1. Call `simplicio-mapper index <repo> --json` before each agent
   dispatch; treat exit `2` as a successful no-op.
2. Parse the JSON payload and follow `project_map_path` /
   `precedent_path` for the actual artifacts.
3. Read JSON artifacts with `json.loads`. Never tail or partially parse —
   atomic writes guarantee whole-file consistency.
4. Observe `skipped_reason="locked"`; back off and retry rather than
   block.
5. Track `duration_ms` in your telemetry to attribute speedups.
6. Cache `fingerprint` per-agent; only re-read artifacts when the
   fingerprint changes.
