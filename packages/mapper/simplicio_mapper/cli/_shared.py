from __future__ import annotations

FOR_LLM_FORMATS = {"toon"}
DEFAULT_TOON_COMMANDS = frozenset({"handoff", "orient"})

# Agent-facing verbs. Extra CLI families stay dispatched when invoked by name
# but must not appear on the default ``--help`` surface.
PUBLIC_COMMANDS = frozenset({"scan", "inspect", "handoff", "ask", "sync"})

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
# per-worktree `.simplicio-loop/` index) with its own versioning lifecycle.
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

HELP_TEXT = """simplicio-mapper

Public agent verbs: scan, inspect, handoff, ask, sync.

USAGE
  simplicio-mapper scan <path> [--json] [--sync] [--await] [--timeout <s>] [--goal <text>] [--target <file>]
  simplicio-mapper inspect <path> [--json] [--for-llm toon] [--await] [--timeout <s>]
  simplicio-mapper handoff <path> [--goal <text>] [--target <file>] [--token-budget <n>] [--json] [--for-llm toon] [--await]
  simplicio-mapper ask <path> <verb> [<arg>] [--depth N] [--limit N] [--json] [--for-llm toon]
  simplicio-mapper sync <path> [--range <spec>|--staged] [--check] [--json]

COMMANDS
  scan <path>      Macro now + deep index in the background.
  inspect <path>   Gate: artifacts exist, are fresh, schema ok.
  handoff <path>   Bounded context pack for downstream agents (TOON default).
  ask <path>       Query callers|callees|reaches|impact|flows|rules|tests-for|term.
                   Results use resolved call edges only.
  sync <path>      Refresh docs/flows a diff affects. --check exits 1 if stale.

OPTIONS
  --json                Machine-readable output.
  --for-llm toon        LLM-facing TOON (handoff defaults to TOON).
  --goal <text>         scan/handoff task goal.
  --target <file>       scan/handoff corridor.
  --token-budget <n>    handoff envelope cap (default 8000).
  --check               sync: report staleness without writing.
  --await               Block until the deep pass is terminal.
  --timeout <s>         Bounded wait for --await (default 120).
  --sync                scan: block on the deep pass.
  --range <spec>        sync: git diff range instead of the working tree.
  --staged              sync: diff staged changes.
  -V, --version         Show version and exit.
  -h, --help            Show this help

Internal modules remain available when invoked by name; they are not
required agent verbs. Notably: `simplicio-mapper snapshot build <path>`
materializes the ContextSnapshot under `.simplicio-loop/context-snapshot.json`.
"""
