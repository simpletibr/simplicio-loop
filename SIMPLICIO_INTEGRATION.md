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

### Languages with structural extraction

Symbol extraction and the call graph cover, by tier:

- **Original:** Python, JavaScript, TypeScript, C#, Razor, Go, Rust, Java, Kotlin, PHP, Ruby.
- **Tier 1/2 (added):** Dart, C, C++, Swift, Objective-C, Vue, Svelte, Scala — symbols + call graph; **SQL** gets symbol extraction (tables / views / functions / procedures) but is intentionally excluded from the call graph (no call sites).
- **Tier 3 (added):** Elixir, Erlang, Lua, R, Julia, Perl, MATLAB — lightweight symbols + call graph; **HTML templates / XHTML / CSS-family** are now inventoried and get lightweight structural extraction (template IDs/components, CSS selectors) but stay outside the call graph.

Dedicated import parsing exists for JS/TS, Python, C#/Razor, Go, Vue, Svelte,
Dart, Swift, Scala, C/C++ (`#include`), Objective-C (`#import`/`@import`),
Elixir, Erlang, Lua, R, Julia, Perl, MATLAB, and CSS `@import`. Any other
language is still **counted** and inventoried as text without structural
extraction. The optional Rust acceleration crate (ADR-002) only implements
import parsing for the original set; newer languages always take the pure-Python
path.

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
- `flowchart.md`

Remote publication is deliberately not automatic. Exporting to a GitHub Wiki,
Docusaurus tree, Obsidian vault, or another docs target should be a separate
explicit step.

## Service Flowchart Contract

`simplicio-mapper flowchart <path>` produces `simplicio.service-flowchart/v1`
on stdout (with `--json`) and renders Mermaid to `.simplicio/docs/flowchart.md`.
It is a producer artifact: downstream tools such as `simplicio-dev-cli` read it,
they do not generate it. All signals are deterministic or clearly heuristic;
semantic business rules are never inferred — only the rules encoded in the
source are surfaced.

Top-level fields:

- `schema`, `root`, `doc` (path to the rendered Markdown), `counts`.
- `screens[]` — frontend face. Each screen carries `path`, `component`,
  `persona`, `guarded`, `dynamic`, `file`, `scope`, plus:
  - `services[]` — `{method, path, file}` client calls whose source file lives
    in the screen component's module scope.
  - `buttons[]` — `{label, handler, file, line, services[]}` extracted from the
    component template `(click)` handlers; `services[]` is populated only when
    the handler body itself issues an `/api/v1` call.
  - `rules[]` — `{kind, detail}` observable rules: `guard`, `persona`,
    `dynamic-route`, `validator`.
- `unlinked_services[]` — `{method, path, file}` client calls that match no
  screen scope.
- `backend[]` — backend face, one entry per server route (Azure Functions C#
  and FastAPI Python): `method`, `path`, `file`, `layer`, `auth`, `request[]`,
  `response[]`, `external_calls[]`, `external_count`, `db_access`,
  `db_markers[]`, and an ordered `steps[]` list rendered as a per-endpoint
  Mermaid flow.

Heuristic fields (`request`, `response`, `external_*`, `db_*`) must be verified
against the referenced source before being treated as a contract.

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

Schema: `simplicio.mechanical-edit/v1` (mapper context envelope). The
contract was originally tracked through
[`simplicio-runtime#69`](https://github.com/wesleysimplicio/simplicio-runtime/issues/69);
this repository implements the **producer half** so an LLM planner can
plan compact JSON edits without rewriting whole files.

Runtime compatibility note: current `simplicio-runtime` executor inputs
are `simplicio.edit-plan/v1`, and executor results are
`simplicio.edit-result/v1`. The mapper envelope below is an anchor/context
producer, not a replacement executor schema. Runtime adapters must compile
the selected file, optional `expect_sha256`, and operations into the
standard edit plan before calling `simplicio edit`; this repository must
not fork the runtime edit schemas.

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

## Two-tier async mapper (issue #120)

Schemas: `simplicio.macro-map/v1`, `simplicio.map-job/v1`, `simplicio.map-status/v1`.
Decision record: [`ADR-003`](.specs/architecture/ADR-003-two-tier-async-mapper.md).

The default synchronous behavior of `map`/`index` is unchanged. This adds a fast
lane (macro) and a typed way to start + poll the deep pass.

### `macro` — instant shallow skeleton

```bash
simplicio-mapper macro . --json
```

`simplicio.macro-map/v1` is derived from filenames plus a few manifests
(`package.json`, `pyproject.toml`, `.starter-meta.json`) only — **no per-file
content reads**, no symbol/call-graph pass. It is sub-second and therefore
`confidence: "shallow"`.

| Field | Meaning |
|---|---|
| `product` | `name`, `stack`, `project_mode` |
| `counts` | `files`, `by_language{}`, `screens`, `endpoint_files`, `tests`, `modules` |
| `modules[]` | top-level dirs with `file_count` (desc) |
| `layers[]` | path-derived layers with `file_count` (desc) |
| `entry_points[]` | files whose stem is an entrypoint or `package.json` main/bin |
| `config_files[]` | known manifests + `*config*`/`*rc` files |
| `git` | `head`, `dirty` |
| `confidence` | always `"shallow"` for this schema |

Screen/endpoint/test counts are path heuristics, not content-verified — treat
them as hints.

### `scan` — macro now + deep in background

```bash
simplicio-mapper scan . --json            # async: returns phase=macro_done
simplicio-mapper scan . --sync --json     # synchronous deep: phase=complete
simplicio-mapper scan . --await --timeout 60 --json   # block until terminal
```

Returns a `simplicio.map-job/v1` envelope immediately and persists it to
`.simplicio/map-job.json`:

| Field | Meaning |
|---|---|
| `phase` | `macro_done` (async) · `complete`/`failed` (sync or after `--await`) |
| `sync` | whether the deep pass ran synchronously (`CI=true` forces this) |
| `macro` | the inline `simplicio.macro-map/v1` |
| `deep` | `state_path`, `lock_path`, `poll`; plus `pid`/`log` in async mode |

`CI=true` (or `--sync`) runs the deep pass synchronously and returns a complete
envelope with artifacts present. The deep pass reuses the detached `index`
machinery and is lock-guarded by `index.lock` against concurrent deep runs.

### `status` — poll the deep pass

```bash
simplicio-mapper status . --json
simplicio-mapper status . --await --timeout 30 --json
```

`simplicio.map-status/v1` derives `phase` deterministically:

1. `index.lock` present → `deep_running`
2. else artifacts present and `index-state.json` signature is fresh → `complete`
3. else `map-job.json` exists but no fresh artifacts and no lock → `failed`
4. else → `unknown`

`--await` (shared by `scan` and `status`) blocks until the phase leaves
`deep_running` or the bounded `--timeout` (default 120s) fires.

## Context Packs and Hash-Based Cache (issue #115)

Schemas: `simplicio.context-pack/v1` and `simplicio.context-cache/v1`.
The canonical contracts live in
[`simplicio-runtime#70`](https://github.com/wesleysimplicio/simplicio-runtime/issues/70);
this repository implements the producer half so the mapper, not the LLM,
decides what compact context goes into a prompt.

### Context pack

```python
from simplicio_mapper.context_pack import build_context_pack

pack = build_context_pack(
    root=".",
    targets=[
        {"path": "simplicio_mapper/cli.py", "ranges": [(900, 950)]},
        {"path": "simplicio_mapper/mapper.py", "ranges": [(160, 200)]},
    ],
)
```

The returned envelope:

```json
{
  "schema": "simplicio.context-pack/v1",
  "repo": {
    "mapper_schema": "simplicio.mapper-index/v1",
    "root_hash": "<sha256 of the absolute root path>"
  },
  "pack_hash": "<sha256 over all snapshot+range hashes>",
  "files": [
    {
      "path": "...",
      "language": "python",
      "snapshot_hash": "<sha256 of the whole file>",
      "line_count": 1234,
      "compact": false,
      "ranges": [
        {
          "start_line": 900,
          "end_line": 950,
          "range_hash": "<sha256 of the slice>",
          "snippet": ["first line", "last line"]
        }
      ],
      "symbols": [{"name": "...", "kind": "...", "line": 0, "hash": "..."}],
      "callers": ["a/file.py"],
      "imports": ["b/file.py"],
      "tests": ["tests/test_file.py"]
    }
  ],
  "dependencies": { "package_manager": "...", "manifest": "..." },
  "recent_changes": [ "..." ],
  "needs_broader_context": false,
  "needs_broader_context_reason": ""
}
```

`build_context_pack` accepts pre-loaded `project_map`, `symbol_index`, and
`call_graph` dicts; otherwise it reads them from `.simplicio/`. When any
of the three is absent — or a target is missing / unreadable, or a range
is out-of-bounds — the function still returns a pack but sets
`needs_broader_context=True` and lists the concrete reasons. **The mapper
does not pretend compact context is enough when anchors, hashes, or
symbol coverage are missing.**

### Context cache

```python
from simplicio_mapper.context_cache import ContextCache

cache = ContextCache(".simplicio/context-cache.json")
hit = cache.get(file_or_pack_hash)
if hit is None:
    summary = summarize_via_llm(...)  # caller-supplied
    cache.set(file_or_pack_hash, summary)
```

Stored on disk as a single JSON document with shape
`{"schema": "simplicio.context-cache/v1", "entries": {...}}`. Entries are
keyed by any opaque hash string the caller chooses — typically
`snapshot_hash`, `range_hash`, or the overall `pack_hash` — so a change in
the underlying file invalidates the cached summary naturally. Writes are
persisted immediately; multiple processes pick up the latest value on
their next load.

### Fixtures

`tests/fixtures/ctx-pack-host/` ships four small multi-language fixtures
(`sample.ts`, `sample.py`, `sample.json`, `sample.md`) used by the test
suite to verify language detection and snippet emission. Large-file
behavior is exercised in a temp-dir generated test (`huge.py` with more
than `COMPACT_LINE_THRESHOLD` lines).

## Native Runtime Contract (issue #95)

The unified native Simplicio runtime — coordinating
`simplicio-mapper` + `simplicio-dev-cli` + `simplicio-prompt` +
`simplicio-sprint` + a local LLM (`llama.cpp` / GGUF) as a single local
program — depends on this repository for the **fast context layer**.
Everything in this section is a stable contract: a breaking change requires a
schema bump and an ADR.

When the runtime itself runs `simplicio map`, it wraps adapter execution as
`simplicio.map-result/v1` with artifact paths and fallback status. The
mapper still emits its own adapter payloads (`simplicio.mapper-index/v1`,
`simplicio.project-map/v1`, and related artifact schemas); those are input
artifacts for the runtime wrapper, not replacements for
`simplicio.map-result/v1`.

### Commands and `--json` payloads

| Command | Path | JSON schema | Stable fields |
|---|---|---|---|
| `simplicio-mapper index <path> --json` | stdout | `simplicio.mapper-index/v1` | `status`, `fingerprint`, `project_map_path`, `precedent_path`, `file_count`, `precedent_count`, `duration_ms`, `error?`, `skipped_reason?` |
| `simplicio-mapper map [--root <dir>] [--json]` | stdout when `--json` | mirrors the index payload above | same — emit the same shape so orchestrators do not branch on command name |
| `simplicio-mapper update [--root <dir>] [--json]` | stdout when `--json` | mirrors the index payload above | same |
| `simplicio-mapper macro <path> --json` | stdout | `simplicio.macro-map/v1` | `schema`, `product`, `counts.*`, `modules[]`, `layers[]`, `entry_points[]`, `config_files[]`, `git`, `confidence` |
| `simplicio-mapper scan <path> [--sync] [--await] --json` | stdout + `.simplicio/map-job.json` | `simplicio.map-job/v1` | `schema`, `phase`, `sync`, `macro`, `deep.{state_path,lock_path,poll,pid?,log?}` |
| `simplicio-mapper status <path> [--await] --json` | stdout | `simplicio.map-status/v1` | `schema`, `phase`, `lock`, `fresh`, `state_path`, `updated_at?` |
| `simplicio-mapper endpoints <path> --against <root> --json` | stdout | `simplicio.endpoint-inventory/v1` | `schema`, `counts.client_calls`, `counts.server_routes`, `client_calls[]`, `server_routes[]`, `missing_from_server[]` |
| `simplicio-mapper screens <path> --json` | stdout | `simplicio.screen-inventory/v1` | `schema`, `routes[]`, `personas[]`, `guards[]` |
| `simplicio-mapper flowchart <path> --json` | stdout + `.simplicio/docs/flowchart.md` | `simplicio.service-flowchart/v1` | `schema`, `doc`, `counts.*`, `screens[]`, `unlinked_services[]`, `backend[]` |
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
  `simplicio.screen-inventory/v1`, `simplicio.service-flowchart/v1`,
  `simplicio.mapper-index/v1`,
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
