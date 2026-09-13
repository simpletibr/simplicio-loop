from __future__ import annotations

FOR_LLM_FORMATS = {"toon"}
DEFAULT_TOON_COMMANDS = frozenset({"handoff", "orient"})

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

# Canonical-map read-safe CLI surface (issue #266, ADR-008 migration step 7).
# Net-new, isolated schemas -- `canonical build`/`canonical status` never
# reuse `INDEX_RESULT_SCHEMA`/`MAP_STATUS_SCHEMA` because they describe a
# different artifact family (the cross-worktree canonical manifest, not the
# per-worktree `.simplicio/` index) with its own versioning lifecycle.
CANONICAL_BUILD_SCHEMA = "simplicio.canonical-build/v1"
CANONICAL_BUILD_SCHEMA_VERSION = 1

CANONICAL_STATUS_SCHEMA = "simplicio.canonical-status/v1"
CANONICAL_STATUS_SCHEMA_VERSION = 1

FRESHNESS_SKIP_DIRS = {
    ".git",
    ".catalog",
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

HELP_TEXT = """simplicio-mapper scan

Default route: macro now, user --target/--goal corridor in the foreground, deep index in the background.

USAGE
  simplicio-mapper [<path>] [--goal <text>] [--target <file>] [--json]
  simplicio-mapper index <path> [--json] [--for-llm toon] [--tagged] [--confidence <tag>] [--geometry] [--verbose] [--update]
  simplicio-mapper macro <path> [--json]
  simplicio-mapper scan <path> [--json] [--sync] [--await] [--timeout <s>] [--goal <text>] [--target <file>]
  simplicio-mapper status <path> [--json] [--await] [--timeout <s>]
  simplicio-mapper inspect <path> [--json] [--for-llm toon] [--await] [--timeout <s>]
  simplicio-mapper handoff <path> [--goal <text>|--task-file <file>|--task-batch-file <file>] [--task-fingerprint <sha>] [--target <file>] [--minimum-query-coverage <0..1>] [--token-budget <n>] [--execution-context] [--limit <n>] [--json] [--for-llm toon] [--await] [--timeout <s>]
  simplicio-mapper orient <path> (--task-file <file>|--task-json <file>|--stdin) [--target <file>] [--limit <n>] [--json] [--for-llm toon]
  simplicio-mapper endpoints <path> [--against <server-root>] [--json]
  simplicio-mapper screens <path> [--json]
  simplicio-mapper flowchart <path> [--json]
  simplicio-mapper flows <path> [--json]
  simplicio-mapper visualize <path> [--json] [--clustering-config <file>]
  simplicio-mapper preview <path> (--path <file>|--entity-id <id>) [--json]
  simplicio-mapper sync <path> [--range <spec>|--staged] [--check] [--json]
  simplicio-mapper history <path> [--json]
  simplicio-mapper diff <path> --from <id> --to <id> [--json]
  simplicio-mapper ask <path> <verb> [<arg>] [--depth N] [--limit N] [--effect T] [--category C] [--json] [--for-llm toon]
  simplicio-mapper business <path> [--json]
  simplicio-mapper survey <path> [--target <file>] [--json]
  simplicio-mapper drift <path> [--scope all|product|template] [--check] [--threshold N] [--json]
  simplicio-mapper delta <path> [--json] [--out <dir>] [--changed-paths p1,p2] [--full-rescan]
  simplicio-mapper snapshot build <path> [--json]
  simplicio-mapper snapshot summary <path> [--json]
  simplicio-mapper snapshot validate <path> [<path> ...]
  simplicio-mapper snapshot dag <path> [--json]
  simplicio-mapper docs <path> [--json]
  simplicio-mapper export-docs <path> --target <dir> [--json]
  simplicio-mapper map [<path>] [--goal <text>] [--target <file>] [--json]
  simplicio-mapper update [--root <dir>] [--watch]
  simplicio-mapper contract validate <path> [<path> ...]
  simplicio-mapper doctor --contracts [--cross-repo] [<path> ...]
  simplicio-mapper doctor --fast [manifest.json] [--json]
  simplicio-mapper fast-handoff [path] [--changed-path file] [--base-commit sha]
  simplicio-mapper fast-certify --mapper mapper.json --fast fast.json
  simplicio-mapper ecc doctor [--ecc-root <path>] [--json]
  simplicio-mapper ecc pack [--stage planning] [--role mapper-planner] [--json]
  simplicio-mapper canonical build <path> [--json]
  simplicio-mapper canonical status <path> [--json]
  simplicio-mapper canonical verify <path> [--json] [--storage-root <dir>] [--config-fingerprint <value>] [--limit <n>]
  simplicio-mapper canonical gc <path> [--apply] [--json]
  simplicio-mapper benchmark pipeline-threshold [path] [--sizes N,N,N] [--runs N] [--out <dir>] [--json]
  simplicio-mapper benchmark shadow-rollout [path] [--out <dir>] [--json]
  simplicio-mapper version [--json] [--root <dir>]
  simplicio-mapper release-manifest [--json] [--root <dir>] [--check-registry] [--update-registry-baseline]
  simplicio-mapper release-governance parity|classify|reconcile|sign|verify|promote|rollback [options]
  simplicio-mapper changelog [--json] [--version X.Y.Z] [--root <dir>] [--no-migration]

OPTIONS
  index <path>          Idempotently create or refresh .simplicio artifacts.
  macro <path>          Instant shallow project skeleton (no content reads).
  scan <path>           Macro now + deep index in background (map-job envelope).
  background status|cancel|resume|doctor|gc <path> [--json]
  status <path>         Report deep-pass phase from lock/state/map-job.
  inspect <path>        Rich machine-readable inspection over status/index/cache.
  handoff <path>        Status + compact context-pack for downstream agents.
  endpoints <path>      Extract client/server HTTP endpoint inventory.
  screens <path>        Extract frontend route/screen inventory.
  flowchart <path>      Render screen->service->backend mermaid flowchart docs.
  flows <path>          Derive stack-neutral end-to-end flows from the call graph.
  visualize <path>      Write a versioned renderer-neutral visualization bundle.
                        Optional clustering thresholds/hints come from JSON config.
  preview <path>        Read a bounded, read-only source preview.
  sync <path>           Regenerate only the docs/flows a diff affects.
  history <path>        List .simplicio/history/ snapshots (created by map/sync).
  diff <path>           Semantic delta between two history snapshots.
  ask <path> <verb>     Query artifacts: callers|callees|reaches|impact|flows|rules|tests-for|term.
  business <path>       Extract observable business rules, state machines and glossary.
  survey <path>         New-developer onboarding report (run/reading order/flows/rules).
  drift <path>          Spec-drift: placeholders, orphan specs/code, stale docs.
  delta <path>          Emit an initial graph snapshot or deterministic incremental delta.
  snapshot build <path>  Build the canonical ContextSnapshot artifact used by fast-handoff.
  snapshot summary <path> Read a previously built ContextSnapshot summary.
  snapshot validate ... Validate ContextSnapshot files against the shipped contract.
  snapshot dag <path>   Build the context DAG and journal.
  docs <path>           Render architecture inventory markdown under .simplicio/docs.
  export-docs <path>    Copy rendered markdown docs to a local target directory.
  contract validate <path>...
                        Validate mapper-artifact JSON file(s)/dir(s) against
                        the versioned schemas in
                        contracts/mapper-artifacts/v1/schemas/ (issue #157).
  doctor --contracts    Validate contracts/mapper-artifacts/v1/ and
                        contracts/ecosystem/v1/ fixtures against their
                        schemas; exit 0 when all valid (issue #164).
  doctor --fast         Diagnose Simplicio Fast manifest availability,
                        capability compatibility and generation handle.
  canonical build <path>
                        Build (or reuse, content-addressed) the canonical
                        default-branch manifest via the existing builder
                        (issue #266).
  canonical status <path>
                        Read-only: redacted key/digest, freshness against
                        the current default-branch commit, build-in-progress
                        state, and worktree-overlay counts. Never builds or
                        writes anything (issue #266).
  canonical verify <path>
                        Independent parity proof between the composed
                        EffectiveMapView (canonical manifest + worktree
                        overlay) and a full remap of the same worktree;
                        exit 0 on match, 1 on mismatch/failure (issue #267).
  canonical gc <path>   Conservative, crash-safe GC of interrupted
  ecc doctor            Inspect the opt-in ECC checkout and policy.
  ecc pack              Emit bounded ECC guidance for a planning stage.
                        promotions and stale canonical-map snapshots under
                        the ADR-008 content-addressed storage root. Dry-run
                        by default; pass --apply to actually delete
                        (issue #268).
  benchmark pipeline-threshold [path]
                        Measure THIS machine's real sync-vs-async mapping-
                        pipeline crossover and cache the result at
                        <out>/pipeline-calibration.json. The result is
                        retained as local benchmark/receipt metadata;
                        normal auto execution remains async (issue #279
                        Phase-0, ADR-011).
  benchmark shadow-rollout [path]
                        Run the CONFIGURED sync/async pipeline profile for
                        real, shadow-run the other profile in an isolated
                        temp dir, and compare wall time + output
                        equivalence -- never promotes the candidate; the
                        real caller always gets the configured profile's
                        result. Writes a receipt to
                        <out>/pipeline-shadow.json (issue #279 plan step
                        15, ADR-011).
  version [--json]      Show mapper version. With --json, emit the
                        machine-readable release identity, artifact digest,
                        protocols and schema versions required by issue #280.
  release-manifest      Phase-0, local, offline generator for the
                        simplicio.component-release/v1 manifest: version,
                        commit SHA, and every schema-version constant this
                        package publishes. No signing/SBOM/network calls
                        (issue #280, ADR-010). --check-registry /
                        --update-registry-baseline maintain the committed
                        schema-version-registry baseline used to catch
                        unintentional schema-version drift.
  release-governance     Fail-closed release gates for registry parity,
                        manifest-level compatibility, Ed25519 signing,
                        CycloneDX SBOM, missed-event reconciliation,
                        canary-to-stable promotion, and deterministic
                        rollback/revocation (issue #280).
  changelog              Machine-readable extraction of CHANGELOG.md
                        (simplicio.changelog-report/v1): version, date and
                        sections copied verbatim, plus a rollback_hint
                        (pip install simplicio-mapper==<previous>) per
                        entry and a migration cross-reference against
                        `schema-compat` for the current/latest entry
                        (issue #280 step 9). --version filters to one
                        entry; --no-migration skips the schema-compat
                        cross-reference.
  --config-fingerprint <value>
                        canonical verify: override the mapping-config
                        fingerprint segment of the canonical key (default is
                        a stable placeholder -- no config knobs are exposed
                        at this surface yet).
  --range <spec>        sync: git diff range (e.g. main..HEAD) instead of the working tree.
  --staged              sync: diff staged changes instead of the working tree.
  --check               sync: report staleness without writing (exit 1 if stale).
  --from <id>           diff: source snapshot id.
  --to <id>             diff: target snapshot id.
  --retention <n>       Max history snapshots kept (default 50, oldest GC'd first).
  --threshold <n>       drift: max findings allowed before --check fails (default 10).
  --against <dir>       Compare endpoint client calls against server routes.
  --target <file|dir>   scan/handoff: foreground corridor; export-docs: destination.
  --goal <text>         scan/handoff: task goal for ranking the foreground corridor.
  --task-file <file>    handoff: Markdown/Gherkin/JSON task parsed into task intent.
  --task-batch-file <file>
                        handoff: JSON list/object of tasks; emits plan-only batch envelope.
  --task-json <file>    orient: JSON task input.
  --stdin               orient: read the raw task from stdin.
  --task-fingerprint <sha>
                        handoff: stable upstream task identity for cache/hash keys.
  --minimum-query-coverage <0..1>
                        handoff: minimum lexical coverage before context is sufficient (default 0.2).
  --token-budget <n>    handoff: maximum for the final serialized envelope; oversized context
                        is replaced by bounded expansion handles (default 8000).
  --execution-context   handoff: add simplicio.execution-context/v1 without changing the outer contract.
  --docs                Render markdown docs after map/index.
  --no-docs             Keep map/index JSON-only.
  --docs-only           Render markdown docs without refreshing JSON first.
  --json-only           Compatibility alias for --no-docs.
  --changed-only        Compatibility alias for incremental refresh workflows.
  --background          Start an index refresh in a detached background process.
  --sync                scan: block on the deep pass (also when CI=true). Default is background.
  --await               scan/status/inspect/handoff: block until the deep pass is terminal.
  --timeout <s>         Bounded wait for --await (default 120).
  --json                Emit structured index output.
  --for-llm <format>    emit payload as <format> (supported: toon).
                         handoff and orient default to TOON for LLM context;
                         --json is an explicit machine-readable override.
                         Set SIMPLICIO_TOON=0 to disable the default.
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
  --canonical-reuse      index/scan: opt in to reusing a validated canonical
                         default-branch manifest (issue #269, ADR-008) when
                         this worktree's HEAD matches it and is clean. Falls
                         back to the full legacy map on any miss/mismatch
                         (never serves stale data). Default off; also
                         settable via SIMPLICIO_MAPPER_CANONICAL_REUSE=1.
  --no-canonical-reuse   Explicitly disable canonical reuse (default).
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
  --full-rescan          Ignore incremental state and request a consumer resync snapshot.
  --snapshot <file>      Optional graph snapshot path for delta consumers.
  --changed-paths <list> Comma-separated repository-relative paths affected by this scan.
  --watch               Re-run mapping when local files change.
  --silent              Minimal output.
  -V, --version         Show version and exit.
  -h, --help            Show this help
"""
