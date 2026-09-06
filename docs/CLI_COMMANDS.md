# Simplicio Mapper: command and feature index

This is the discovery contract for humans, LLMs and agent integrations. The
Python package is the canonical mapper; the Node package is the scaffold and
compatibility surface. Source files remain authoritative and all generated
`.simplicio/` artifacts are disposable, versioned evidence.

## Entry points

| Entry point | Purpose | Help |
| --- | --- | --- |
| `simplicio-mapper` | Canonical Python mapper and artifact/query CLI | `simplicio-mapper --help` |
| `llm-project-mapper` | Alias for the Python CLI | `llm-project-mapper --help` |
| `npx @wesleysimplicio/llm-project-mapper` | Node scaffolder and mapper compatibility CLI | `npx @wesleysimplicio/llm-project-mapper --help` |
| `build-hamt-catalog` | Build the bounded AGENTS/skill catalog | `build-hamt-catalog --help` |
| `apply-edits` | Apply a validated structured edit payload | `apply-edits --help` |
| `skillopt` | Optimize/select a skill from a suite | `skillopt --help` |

Every public entry point must explain its operation through `--help`/`-h`.
Read the help for the exact level being invoked before executing it.

## Canonical Python commands

| Command | What it does | Help contract |
| --- | --- | --- |
| `index <path>` | Create or refresh the full `.simplicio/` map | `simplicio-mapper index --help` |
| `map [--root <dir>]` | Run the default mapping workflow | `simplicio-mapper map --help` |
| `update [--root <dir>]` | Incrementally refresh the map | `simplicio-mapper update --help` |
| `macro <path>` | Emit a shallow project skeleton without full content reads | `simplicio-mapper macro --help` |
| `scan <path>` | Start a macro plus deep background scan | `simplicio-mapper scan --help` |
| `status <path>` | Report scan phase, lock and map-job state | `simplicio-mapper status --help` |
| `inspect <path>` | Return a rich machine-readable map/cache inspection | `simplicio-mapper inspect --help` |
| `handoff <path>` | Select bounded, task-aware context for a downstream agent | `simplicio-mapper handoff --help` |
| `orient <path>` | Build a task-oriented context pack from a task file/JSON/stdin | `simplicio-mapper orient --help` |
| `endpoints <path>` | Inventory client calls and server routes | `simplicio-mapper endpoints --help` |
| `screens <path>` | Inventory frontend routes and screens | `simplicio-mapper screens --help` |
| `flowchart <path>` | Render screen-to-service-to-backend Mermaid flowcharts | `simplicio-mapper flowchart --help` |
| `flows <path>` | Derive end-to-end flows from the call graph | `simplicio-mapper flows --help` |
| `visualize <path>` | Write a renderer-neutral visualization bundle | `simplicio-mapper visualize --help` |
| `preview <path>` | Read a bounded, read-only source preview | `simplicio-mapper preview --help` |
| `docs <path>` | Render architecture and inventory Markdown | `simplicio-mapper docs --help` |
| `export-docs <path>` | Copy rendered Markdown to a target directory | `simplicio-mapper export-docs --help` |
| `sync <path>` | Refresh only docs/flows affected by a Git diff | `simplicio-mapper sync --help` |
| `history <path>` | List versioned `.simplicio/history/` snapshots | `simplicio-mapper history --help` |
| `diff <path>` | Compare two history snapshots semantically | `simplicio-mapper diff --help` |
| `delta <path>` | Emit an initial graph or deterministic incremental delta | `simplicio-mapper delta --help` |
| `ask <path> <verb> [arg]` | Query callers, callees, reachability, impact, flows, rules, tests or terms | `simplicio-mapper ask --help` |
| `business <path>` | Extract business rules, state machines and glossary | `simplicio-mapper business --help` |
| `survey <path>` | Build a new-developer onboarding report | `simplicio-mapper survey --help` |
| `drift <path>` | Detect spec, placeholder, orphan-code and stale-doc drift | `simplicio-mapper drift --help` |
| `snapshot <verb>` | Manage context snapshots through its own subcommand parser | `simplicio-mapper snapshot --help` |

`--json` is the machine-facing output mode where supported. `--for-llm toon`
is available on the context-heavy commands listed by the help text. Preserve
the returned `schema` and reject unknown major schema versions.

After `index` proves a complete, fresh, unlocked canonical map, it also
materializes deterministic read-only project descriptors below
`.skills/_generated/` and `.agents/_generated/`, with the active registry and
content-addressed generation receipts under `.catalog/`. Non-canonical or dirty
Git worktrees remain preview-only, and deleting `.simplicio/*.json` does not
delete or rewrite the last-known-good descriptors.

## Routed command families

These families are dispatched before the legacy mapper parser and therefore
have their own help. They are still public commands and must be included in
CLI audits.

| Family | Operations | Help discovery |
| --- | --- | --- |
| `contract` | `validate <path>...` against versioned schemas | `simplicio-mapper contract --help`, `simplicio-mapper contract validate --help` |
| `contracts` | Validate contract fixtures and compatibility surfaces | `simplicio-mapper contracts --help` |
| `doctor` | `--contracts`, `--cross-repo`, `--fast` ecosystem diagnostics | `simplicio-mapper doctor --help` |
| `canonical` | `build`, `status`, `verify`, `gc` for the content-addressed default-branch map | `simplicio-mapper canonical --help`, `simplicio-mapper canonical <verb> --help` |
| `benchmark` | `pipeline-threshold`, `shadow-rollout` calibration and evidence | `simplicio-mapper benchmark --help`, `simplicio-mapper benchmark <verb> --help` |
| `background` | `status`, `cancel`, `resume`, `doctor`, `gc` for detached scans | `simplicio-mapper background --help`, `simplicio-mapper background <verb> --help` |
| `mapper-store` | Canonical MapperStore status/capabilities/conformance and explicit legacy absorb, plus governed migrations | `simplicio-mapper mapper-store --help`, `simplicio-mapper mapper-store <canonical-status\|capabilities\|conformance\|absorb-legacy> --help` |
| `store-migrations` | Store migration compatibility wrapper | `simplicio-mapper store-migrations --help` |
| `scoped-handoff` | Bounded scoped context and handoff | `simplicio-mapper scoped-handoff --help` |
| `fast-handoff` | Emit the Mapper-to-Fast handoff contract | `simplicio-mapper fast-handoff --help` |
| `fast-certify` | Certify Mapper and Fast manifests together | `simplicio-mapper fast-certify --help` |
| `prototype-context` | Produce bounded Prototype-First context | `simplicio-mapper prototype-context --help` |
| `schema-compat` | Classify schema changes as compatible or breaking | `simplicio-mapper schema-compat --help` |
| `version` | Print release identity and protocol/schema metadata | `simplicio-mapper version --help` |
| `release-manifest` | Generate or check the local component release manifest | `simplicio-mapper release-manifest --help` |
| `changelog` | Emit a machine-readable changelog report and rollback hint | `simplicio-mapper changelog --help` |
| `ecc` | Inspect the pinned ECC checkout or emit bounded advisory guidance | `simplicio-mapper ecc --help`, `simplicio-mapper ecc doctor --help`, `simplicio-mapper ecc pack --help` |

## Safe operating sequence

```text
--help -> index/map -> inspect/status -> handoff/orient -> ask/diff/preview
-> implementation by Dev CLI -> tests/evidence -> sync/delta -> release manifest
```

Mapper observes and packages context. It does not authorize effects or replace
tests, review or source control. Use `simplicio-dev-cli` for mechanical source
edits, `simplicio-fast` for snapshots/PlanDAG, Runtime for policy/effects and
Loop for retries/convergence.
