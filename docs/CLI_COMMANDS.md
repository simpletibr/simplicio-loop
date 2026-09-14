# Simplicio Fast: command and feature index

This is the discovery contract for humans, LLMs and agent integrations.
Fast owns semantic project memory, bounded context, PlanDAG compilation,
generation/overlay coordination, guarded changesets and deterministic
receipts. Source files remain authoritative; snapshots are disposable
derived state.

## Entry points

| Entry point | Purpose | Help |
| --- | --- | --- |
| `simplicio-fast` | Snapshot, context, PlanDAG, changeset and workspace CLI | `simplicio-fast --help` |
| `simplicio-fast-cross-repo` | Validate the pinned cross-repository stack lock | `simplicio-fast-cross-repo --help` |

Every public command and nested action must explain its purpose through
`--help`/`-h`. Read help at the exact level being invoked before execution.

## Top-level commands

| Command | Function | Help |
| --- | --- | --- |
| `build`, `refresh`, `ingest` | Create or incrementally update the binary semantic snapshot. Default `--mapper-mode integrated` requires `--mapper-handoff`; bootstrap is an explicit development fallback | `simplicio-fast <command> --help` |
| `query`, `search` | Resolve symbols through snapshot indexes | `simplicio-fast <command> --help` |
| `context` | Return bounded, hash-verified source spans for an LLM | `simplicio-fast context --help` |
| `navigate` | Follow one bounded structural relation from a canonical handle | `simplicio-fast navigate --help` |
| `impact` | Return typed imports, references, calls and tests | `simplicio-fast impact --help` |
| `stats` | Report snapshot generation and section statistics | `simplicio-fast stats --help` |
| `query-plan` | Explain the deterministic query/index budget plan | `simplicio-fast query-plan --help` |
| `segments` | Publish, validate or map immutable snapshot sections | `simplicio-fast segments --help` |
| `understand`, `plan` | Turn a natural-language task into bounded context or a PlanDAG | `simplicio-fast <command> --help` |
| `delivery` | Prepare a guarded delivery receipt. Mutation owner is simplicio-dev-cli; `--write` requires `SIMPLICIO_FAST_ALLOW_WRITE=1` | `simplicio-fast delivery --help` |
| `apply` | Legacy dry-run changeset validator. Mutation owner is simplicio-dev-cli; `--write` requires `SIMPLICIO_FAST_ALLOW_WRITE=1` | `simplicio-fast apply --help` |
| `doctor` | Diagnose installation, integration and snapshot integrity | `simplicio-fast doctor --help` |
| `rollout` | Record shadow/canary/integrated rollout transitions | `simplicio-fast rollout --help` |
| `serve` | Run the small user CRUD HTTP proof-of-concept | `simplicio-fast serve --help` |
| `semantic-score` | Rank bounded candidates with Runtime-aware fallback | `simplicio-fast semantic-score --help` |
| `capabilities` | Report parser, SDK, adapter, security and engine capabilities | `simplicio-fast capabilities --help` |
| `parser-payload` | Convert a validated Mapper handoff to parser-adapter JSON | `simplicio-fast parser-payload --help` |
| `pin`, `release`, `gc`, `watch` | Protect, release, collect or refresh workspace generations | `simplicio-fast <command> --help` |
| `base`, `overlay`, `delta`, `handoff`, `merge` | Build and query canonical/isolated workspace views | `simplicio-fast <command> --help` |

## Changeset actions

`changeset` is a public command family. Each action has its own help:

| Action | Function |
| --- | --- |
| `prepare` | Compile JSON intent into a sealed binary changeset |
| `validate` | Validate a binary changeset against source hashes and leases |
| `seal` | Copy and verify a binary changeset into sealed output |
| `inspect` | Inspect binary metadata without exposing raw offsets |
| `export-json` | Export a binary changeset as versioned JSON |
| `materialize` | Legacy materialize through Dev CLI. Mutation owner is simplicio-dev-cli; `--write` requires `SIMPLICIO_FAST_ALLOW_WRITE=1` |
| `reconcile` | Reconcile a locked unknown Dev CLI effect before retry |
| `recover` | Recover an incomplete binary journal tail |

Use: `simplicio-fast changeset <action> --help`.

## Cross-repository validation

`simplicio-fast-cross-repo validate --file stack-lock.json --profile
`loop-standalone` validates pinned Mapper/Dev/Fast/Loop compatibility and
emits `simplicio.fast.cross-repo-receipt/v1` JSON. The operation is
read-only and fail-closed.

## Source-file size limit

Snapshot build paths (`build`, `refresh`, `ingest`, and the auto-bootstrap used by
`understand` / `plan` when no snapshot exists) reject a source file larger than
**80 MB** (`83_886_080` bytes) by default. Raise or lower the bound per invocation
with `--max-file-bytes` (not `--max-bytes`, which only bounds context delivery).

Files larger than the effective limit fail with `SourceFileTooLarge` before parse.
A ~10 MB generated bundle is accepted under the 80 MB default.

## Safe operating sequence

```text
--help -> ingest --mapper-handoff <file> -> context/query
Mutation: simplicio-dev-cli edit --plan <json> --apply
```

Fast does not replace Mapper extraction or simplicio-dev-cli source mutation.
Default snapshot output is `.simplicio/fast/project.sfast`. Do not read `.sfast`
offsets directly.
