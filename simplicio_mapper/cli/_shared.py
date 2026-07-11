from __future__ import annotations

FOR_LLM_FORMATS = {"toon"}

CONFIDENCE_TAG_ORDER = ("MEASURED", "OPERATOR", "CANON", "UNVERIFIED")

CONFIDENCE_RANK = {tag: rank for rank, tag in enumerate(CONFIDENCE_TAG_ORDER)}

INDEX_RESULT_SCHEMA = "simplicio.mapper-index/v1"

INDEX_STATE_SCHEMA = "simplicio.mapper-index-state/v1"

MACRO_MAP_SCHEMA = "simplicio.macro-map/v1"

MAP_JOB_SCHEMA = "simplicio.map-job/v1"

MAP_STATUS_SCHEMA = "simplicio.map-status/v1"

MAP_INSPECTION_SCHEMA = "simplicio.map-inspection/v1"

MAP_HANDOFF_SCHEMA = "simplicio.map-handoff/v1"

ENDPOINT_INVENTORY_SCHEMA = "simplicio.endpoint-inventory/v1"

SCREEN_INVENTORY_SCHEMA = "simplicio.screen-inventory/v1"

SERVICE_FLOWCHART_SCHEMA = "simplicio.service-flowchart/v1"

FLOW_INVENTORY_SCHEMA = "simplicio.flow-inventory/v1"

VISUALIZATION_SCHEMA = "simplicio.visualization-bundle/v1"

DOCS_SYNC_SCHEMA = "simplicio.docs-sync/v1"

DOC_HISTORY_SCHEMA = "simplicio.doc-history/v1"

BUSINESS_RULES_SCHEMA = "simplicio.business-rules/v1"

ONBOARDING_SCHEMA = "simplicio.onboarding/v1"

SPEC_DRIFT_SCHEMA = "simplicio.spec-drift/v1"

FRESHNESS_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".docusaurus",
    "build",
    "dist",
    "coverage",
    "playwright-report",
    "test-results",
    "__pycache__",
    ".pytest_cache",
}

HELP_TEXT = """simplicio-mapper map

Generate or update machine-readable mapper artifacts.

USAGE
  simplicio-mapper index <path> [--json] [--for-llm toon] [--tagged] [--confidence <tag>] [--geometry] [--verbose] [--update]
  simplicio-mapper macro <path> [--json]
  simplicio-mapper scan <path> [--json] [--sync] [--await] [--timeout <s>]
  simplicio-mapper status <path> [--json] [--await] [--timeout <s>]
  simplicio-mapper inspect <path> [--json] [--for-llm toon] [--await] [--timeout <s>]
  simplicio-mapper handoff <path> [--goal <text>|--task-file <file>|--task-batch-file <file>] [--task-fingerprint <sha>] [--target <file>] [--minimum-query-coverage <0..1>] [--json] [--for-llm toon] [--await] [--timeout <s>]
  simplicio-mapper orient <path> (--task-file <file>|--task-json <file>|--stdin) [--target <file>] [--limit <n>] [--json] [--for-llm toon]
  simplicio-mapper endpoints <path> [--against <server-root>] [--json]
  simplicio-mapper screens <path> [--json]
  simplicio-mapper flowchart <path> [--json]
  simplicio-mapper flows <path> [--json]
  simplicio-mapper visualize <path> [--json]
  simplicio-mapper preview <path> (--path <file>|--entity-id <id>) [--json]
  simplicio-mapper sync <path> [--range <spec>|--staged] [--check] [--json]
  simplicio-mapper history <path> [--json]
  simplicio-mapper diff <path> --from <id> --to <id> [--json]
  simplicio-mapper ask <path> <verb> [<arg>] [--depth N] [--limit N] [--effect T] [--category C] [--json] [--for-llm toon]
  simplicio-mapper business <path> [--json]
  simplicio-mapper survey <path> [--target <file>] [--json]
  simplicio-mapper drift <path> [--scope all|product|template] [--check] [--threshold N] [--json]
  simplicio-mapper docs <path> [--json]
  simplicio-mapper export-docs <path> --target <dir> [--json]
  simplicio-mapper map [--root <dir>] [--incremental] [--watch]
  simplicio-mapper update [--root <dir>] [--watch]
  simplicio-mapper contract validate <path> [<path> ...]
  simplicio-mapper doctor --contracts [--cross-repo] [<path> ...]

OPTIONS
  index <path>          Idempotently create or refresh .simplicio artifacts.
  macro <path>          Instant shallow project skeleton (no content reads).
  scan <path>           Macro now + deep index in background (map-job envelope).
  status <path>         Report deep-pass phase from lock/state/map-job.
  inspect <path>        Rich machine-readable inspection over status/index/cache.
  handoff <path>        Status + compact context-pack for downstream agents.
  endpoints <path>      Extract client/server HTTP endpoint inventory.
  screens <path>        Extract frontend route/screen inventory.
  flowchart <path>      Render screen->service->backend mermaid flowchart docs.
  flows <path>          Derive stack-neutral end-to-end flows from the call graph.
  visualize <path>      Write a versioned renderer-neutral visualization bundle.
  preview <path>        Read a bounded, read-only source preview.
  sync <path>           Regenerate only the docs/flows a diff affects.
  history <path>        List .simplicio/history/ snapshots (created by map/sync).
  diff <path>           Semantic delta between two history snapshots.
  ask <path> <verb>     Query artifacts: callers|callees|reaches|impact|flows|rules|tests-for|term.
  business <path>       Extract observable business rules, state machines and glossary.
  survey <path>         New-developer onboarding report (run/reading order/flows/rules).
  drift <path>          Spec-drift: placeholders, orphan specs/code, stale docs.
  docs <path>           Render architecture inventory markdown under .simplicio/docs.
  export-docs <path>    Copy rendered markdown docs to a local target directory.
  contract validate <path>...
                        Validate mapper-artifact JSON file(s)/dir(s) against
                        the versioned schemas in
                        contracts/mapper-artifacts/v1/schemas/ (issue #157).
  doctor --contracts    Validate contracts/mapper-artifacts/v1/ and
                        contracts/ecosystem/v1/ fixtures against their
                        schemas; exit 0 when all valid (issue #164).
  --range <spec>        sync: git diff range (e.g. main..HEAD) instead of the working tree.
  --staged              sync: diff staged changes instead of the working tree.
  --check               sync: report staleness without writing (exit 1 if stale).
  --from <id>           diff: source snapshot id.
  --to <id>             diff: target snapshot id.
  --retention <n>       Max history snapshots kept (default 50, oldest GC'd first).
  --threshold <n>       drift: max findings allowed before --check fails (default 10).
  --against <dir>       Compare endpoint client calls against server routes.
  --target <file|dir>   handoff: required target hint; export-docs: destination.
  --goal <text>         handoff: normalized task goal used for relevance ranking.
  --task-file <file>    handoff: Markdown/Gherkin/JSON task parsed into task intent.
  --task-batch-file <file>
                        handoff: JSON list/object of tasks; emits plan-only batch envelope.
  --task-json <file>    orient: JSON task input.
  --stdin               orient: read the raw task from stdin.
  --task-fingerprint <sha>
                        handoff: stable upstream task identity for cache/hash keys.
  --minimum-query-coverage <0..1>
                        handoff: minimum lexical coverage before context is sufficient (default 0.2).
  --docs                Render markdown docs after map/index.
  --no-docs             Keep map/index JSON-only.
  --docs-only           Render markdown docs without refreshing JSON first.
  --json-only           Compatibility alias for --no-docs.
  --changed-only        Compatibility alias for incremental refresh workflows.
  --background          Start an index refresh in a detached background process.
  --sync                scan: run the deep pass synchronously (also when CI=true).
  --await               scan/status/inspect/handoff: block until the deep pass is terminal.
  --timeout <s>         Bounded wait for --await (default 120).
  --json                Emit structured index output.
  --for-llm <format>    index/inspect/handoff/ask: emit payload as <format>
                         instead of JSON. Supported: toon (Token-Oriented
                         Object Notation, see docs/toon-benchmark.md for
                         measured reduction on this repo's own artifacts).
                         Fallback arrays (if any) are logged as
                         toon_fallbacks JSON on stderr.
  --tagged               index: attach Asolaria confidence tags
                         (MEASURED/OPERATOR/CANON/UNVERIFIED) to counts.
  --confidence <tag>     index: keep only counts at least as strong as
                         <tag> (implies --tagged; never silently drops a
                         weaker entry, see confidence_filtered_out).
  --geometry             index: attach REALMATHPOS/FNV-1a64/sha16/
                         citizenIdentity addressing per artifact path
                         (Algorithms of Asolaria addressing geometry).
  --update              Compatibility alias for index refresh workflows.
  --verbose             Show progress during index refreshes.
  --root <dir>          Project root to map. Defaults to cwd.
  --stack <name>        Stack hint when .starter-meta.json is absent.
  --product-name <name> Product name hint when .starter-meta.json is absent.
  --out <dir>           Artifact directory. Defaults to .simplicio.
  --path <file>         Preview a validated path inside the mapped root.
  --entity-id <id>      Preview a file or symbol addressed by bundle entity id.
  --line <n>            Preview starting line (default 1).
  --max-lines <n>       Preview line limit (default 200).
  --max-bytes <n>       Preview byte limit (default 16384).
  --allow-full-content  Explicitly opt in to full-content preview with warning.
  --incremental         Record changed files and update existing artifacts.
  --watch               Re-run mapping when local files change.
  --silent              Minimal output.
  -V, --version         Show version and exit.
  -h, --help            Show this help
"""
