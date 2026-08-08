# Changelog

## Unreleased

### Fixed

- Reject unknown ContextGraph contract schema majors before exposing partial
  graph data, while preserving validated additive minor contracts through a
  shared Python, Node and optional Rust compatibility fixture.

### Added

- Generate deterministic, read-only project skills and agents after a fresh,
  complete canonical index; preserve content-addressed last-known-good
  generations under `.catalog` and leave human `.skills`/`.agents` untouched.

## [0.26.15] - 2026-08-03

### Changed
- Scoped data roots: **core/runtime** at `~/.simplicio/data`; **project** at
  `<repo>/.simplicio/data/<slug>` (slug from git remote / SIMPLICIO_PROJECT /
  Codex·Cursor·Claude·Gemini workspace name). Memories and DBs no longer mix.
- Default home store is `~/.simplicio/data` (not bare `~/data`).

### Added
- `store/project_scope.py` + `data status|unify --repo|--project` scopes block.

## [0.26.14] - 2026-08-03

### Added
- Single-SQLite memory unification: `$SIMPLICIO_DATA_DIR/memory.sqlite` is the only SoT (MapperStore + FTS5).
- CLI `simplicio-mapper data unify` — ensure schema, absorb legacy neural, bridge into MapperStore, rebuild FTS.
- `init`/`absorb` always run unify so Runtime/MCP see loaded data via `SIMPLICIO_MEMORY_DB=…/memory.sqlite`.
- Receipt `memory-unify-receipt.json` + `CANONICAL_MEMORY.txt` under the data root.
- Mapper↔Fast link status in `data status|unify|init --repo` (`mapper_fast`): handoff modules, Fast binary, project-map/.sfast.
- Layout documents Mapper extract → Fast `.sfast` vs global memory SoT split.

### Fixed
- `fast_certification` imports on Windows (optional `resource` module).

### Changed
- Legacy `simplicio-memory.sqlite` is absorb/bridge source only (not MCP SoT).

## [0.26.13] - 2026-08-03

### Added
- Ecosystem data catalog: Mapper owns every durable bank under `SIMPLICIO_DATA_DIR`.
- CLI `simplicio-mapper data layout|status|absorb|init` with absorb-from-legacy (`~/.simplicio/**`).
- Manifest `ecosystem-data-catalog.json` written on absorb; env hints for `SIMPLICIO_DATA_DIR` and `SIMPLICIO_MEMORY_DB`.

## [0.26.12] - 2026-08-03

### Added
- Neural bank centralization: package Runtime seeds.sql, memory-schema.sql, and migrations under simplicio_mapper/store/neural/assets/.
- CLI `simplicio-mapper neural init|absorb|status|seed` — Mapper owns SIMPLICIO_DATA_DIR/simplicio-memory.sqlite.
- absorb copies ~/.simplicio/memory/simplicio-memory.sqlite into Mapper data root with backup + migrations.

## [0.26.11] - 2026-08-02

- Publish the cross-agent command and feature index for the Python and Node
  entrypoints, including the routed contract, canonical, benchmark, release,
  and handoff surfaces.
- Keep `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `llms.txt`, and Copilot guidance
  aligned so LLMs discover the same capabilities and use `--help` before every
  public operation.

## [0.26.10] - 2026-08-02

### Added

- Publish the merged MapperStore conformance, crash-recovery, rollback, and
  cross-repository evidence slices for the Mapper release train (#472, #481).

## [0.26.9] - 2026-08-01

### Fixed

- Classify unavailable quality-gate tools consistently on localized Windows
  systems (PR #470).

## [0.26.8] - 2026-08-01

### Fixed

- Make the release quality gate deterministic on Windows when subprocess output
  uses non-CP1252 bytes (PR #467).

## [0.26.6] - 2026-08-01

### Fixed

- Prevent partial index state from being reported as already fresh (PR #429, Runtime #3711).
- Persist detached worker terminal receipts and verify Windows Runtime scans reach fresh, complete state.

## [0.26.3] - 2026-07-31

### Fixed

- Make concurrent deep-index callers wait on the shared per-worktree lock.
- Keep detached mapping workers on the same package import root as the parent process.

## [0.26.2] - 2026-07-30

### Fixed

- Ship a portable Codex hook bridge so PostToolUse and UserPromptSubmit do
  not reference missing scripts or shell-specific environment variables.

## [0.26.1] - 2026-07-30

### Changed

- Publish the Python-first Mapper compatibility line used by Loop 3.38.11,
  Dev CLI 0.18.1, and Fast 2.0.18.

## [0.26.0] - 2026-07-28

### Added

- Added `tested_by`, `fixed_with`, and `reverts` edges to
  `simplicio.context-history/v1` without exporting author/subject/diff content;
  provenance now documents Mapper ownership and Fast as consumer (#373).
- Added `simplicio.prism-task-facts/v1` for bounded Prism task projection:
  declared/observed write-set namespaces, dependency/test/resource hints,
  hard/soft conflict candidates, coverage/fidelity/abstention, and
  order-independent batch projection for up to 10 tasks (#393).
- Added `simplicio.prism-work-delta/v1` for incremental invalidation between
  PrismTaskFacts generations, including affected tasks, conflict diffs, and
  `safe_to_reuse_context` as a fact (never mutation authority) (#394).
- Added internal HBP-style binary codec (`HBP1`) for Prism contracts with
  content-addressed framing, tamper rejection, external JSON adapters, and
  capability negotiation. JSON remains boundary-only (#395).
- Added optional `simplicio.mapper.semantic-index/v1` deterministic semantic
  enrichment that never creates factual edges; ML mode fails closed without a
  Runtime InferenceBackend (#377).

### Notes

- GitHub already carried an untagged/local `0.25.0` line; this is the first
  PyPI publish of the post-0.24.2 ContextGraph/Prism surface as `0.26.0`.

## [0.25.0] - 2026-07-26

### Added

- Added canonical `ContextSnapshot` provenance to opt-in execution-context
  handoffs. The bounded `ContextPack` now carries the exact snapshot digest,
  revision, root hash, and snapshot id consumed by downstream Dev CLI
  verification (simplicio-dev-cli#300).
- Added the opt-in `handoff --execution-context` producer for the deterministic
  `simplicio.execution-context/v1` per-task envelope, including exact source
  spans/hashes, graph/test/precedent provenance, stable expansion handles,
  explicit fidelity/abstention/budget receipts, boundary redactions, packaged
  schema/fixture assets, and a reproducible cold/warm benchmark (issue #350).
- Added atomic terminal inspection receipts and bounded timeout handoff
  behavior so worker death, timeout and lock state remain auditable.
- Added resumable timeout checkpoints, heartbeat/progress state and automatic
  incremental retry without repeating completed mapping work (issue #357).
- Added the capability-negotiated Simplicio Fast backend adapter while keeping
  Mapper as the public canonical ContextGraph producer (issue #358).
- Added the versioned machine-first Mapper-to-Fast handoff with stable
  generations, artifact checksums, canonical-map identity, changed-path deltas
  and parsed/reused/degraded/fallback receipts (issue #360).
- Added Fast shadow certification with precision/recall per relation and
  language, reproducible divergence samples, canary gates, compatibility
  policy, observability and configuration-only rollback (issue #359).

### Changed

- Added raw, reproducible 10-run benchmark evidence for Fast adapter,
  handoff concurrency and cold/warm/incremental certification workloads.
- Expanded cross-language contract fixtures for Python, TypeScript, Rust and
  C# without exposing internal mmap offsets.


## [0.24.2] - 2026-07-21

### Added

- Added the local/offline Mapper quality gate with strict internal-format
  scanning, Python/Node/package checks, optional Runtime verification, and
  Markdown-only evidence reports.

### Changed

- Removed Mapper-specific hosted GitHub Actions quality workflows; release
  verification is now runnable locally without CI charges.
- Added Windows-compatible npm.cmd invocation to the local quality gate.

## [0.24.1] - 2026-07-18

### Fixed

- Cut an actual tagged/published release containing the `0.24.0` timeout
  fix (bounded synchronous scans, terminal `phase=timeout` receipts with
  `failure_reason=scan_timeout`, `exit_code=1`, and dead-owner lock
  recovery — `simplicio_mapper/cli/_status_engine.py`,
  `simplicio_mapper/cli/_background.py`) and the additional canonical-map
  and async-pipeline work merged since (issues #235, #236) that had piled
  up on top of the untagged `0.24.0` version bump (issue #233).

### Release process notes (issue #233)

- **Root cause of the drift**: the `0.24.0` version bump (commit
  `caa54aa`, "release: simplicio-mapper v0.24.0 (#253)") updated
  `package.json`/`pyproject.toml`/`simplicio_mapper/__init__.py` and the
  changelog, but **no `v0.24.0` git tag was ever created and no PyPI
  publish ran** for it — `git tag -l` on this repo stops at `v0.23.1`.
  Thirteen further commits (issues #235, #236, plus a perf fix) landed on
  `main` afterward without another version bump, so any operator who
  installed `simplicio-mapper` from PyPI was still resolving `0.23.1`,
  exactly as reported in issue #233, even though `origin/main`'s source
  tree had long since carried the PR #232 timeout fix (and more).
- **How to detect a stale install**: compare `simplicio-mapper --version`
  (or `pip show simplicio-mapper`) against the latest tag in
  `git tag -l 'v*' --sort=-v:refname | head -1` / the latest GitHub
  Release. A mismatch — especially an installed version at or below
  `0.23.1` — means the operator does not have the PR #232 timeout fix and
  must reinstall.
- **How to upgrade**: `pip install --upgrade simplicio-mapper==0.24.1`
  (or `pip install --force-reinstall simplicio-mapper==0.24.1` if the
  environment previously pinned `0.23.1`). Verify with
  `simplicio-mapper --version` and `pip show simplicio-mapper` reporting
  the same `0.24.1`, then confirm the fix behaviorally: a bounded
  `scan --json --sync --timeout <n>` against a slow/blocked root
  surfaces `phase=timeout`, `failure_reason=scan_timeout`, `exit_code=1`,
  and leaves no orphaned lock (`status --json` shows `lock=false` on the
  next run); a normal `scan --json --sync --timeout 30` produces
  `phase=complete`, `exit_code=0`, and `status --json` reports
  `terminal=true`, `fresh=true`, `lock=false`, `warnings=[]`.
- **Rollback**: `pip install simplicio-mapper==0.23.1` restores the prior
  published release if `0.24.1` regresses in the field; there is no
  `0.24.0` PyPI artifact to roll back to, since it was never published.
- This entry intentionally does not reopen or modify the PR #232
  implementation itself — the fix already lives in
  `simplicio_mapper/cli/_status_engine.py` /
  `simplicio_mapper/cli/_background.py` and is covered by
  `tests/python/test_cli_coverage.py`; this release only closes the
  publish/tag/install gap around it.
- **Local pre-publish validation performed** (no PyPI credentials
  required): `python -m build` produces a clean `simplicio_mapper-0.24.1`
  sdist + wheel, and `twine check dist/*` reports `PASSED` for both
  artifacts against an up-to-date `packaging`/`twine` toolchain (an
  ancient system-installed `packaging` release can misreport the wheel's
  `License-File` metadata field as invalid — that is a local toolchain
  issue, not a defect in the built artifact, and does not block the real
  upload).
- **Windows-only verification still pending real Windows access**: the
  `stdin=DEVNULL`/`WinError 6` fix (issue #231) and the `taskkill`
  recovery path cannot be exercised from a Linux sandbox. A precise,
  runnable checklist for an operator with Windows + the published
  `0.24.1` install is documented in
  `docs/windows-verification-issue-233.md` so that final verification is
  a checklist, not a research task.

## [0.24.0] - 2026-07-17

### Fixed

- Make synchronous scans run in a bounded worker with terminal timeout
  receipts and safe dead-owner lock recovery (issues #201 and #230).
- Prevent Windows background/index workers from inheriting invalid stdin
  handles under pytest and non-interactive hosts (issue #231).
- Pin `stdin=DEVNULL` on the Windows `taskkill` call used to recover a
  timed-out/orphaned index worker, closing the same inherited-stdin failure
  class on the kill path (issue #231).
- Surface lock evidence (`lock_status`/`lock_reason_code`, including the new
  `lock_acquired` reason code) directly on `index --json` output, not only
  via `status`, and close out issue #201's remaining acceptance criteria with
  process-level regression coverage: live full-schema lock never stolen,
  crash/kill of a real background worker never wedges `status --await`, and
  two concurrent `index` invocations against the same root never both run
  the deep pass (issue #201).
- Exclude nested `.claude/worktrees/` checkouts from the mapped file
  universe across the main walk, freshness signatures, and query cache
  path scan, while preserving root-level `.claude/` configuration such as
  `settings.json` and `skills/*.md` (issue #234).
- Extend the stdin=DEVNULL fix to every remaining git/CLI/runtime
  subprocess call in the package (not just the background index worker and
  the taskkill path above), fixing the same WinError 6 on any host with a
  captured/closed stdin (issue #231).

## [0.23.1] - 2026-07-13

### Fixed

- Harden ContextSnapshot fidelity abstention and broader-context signaling.
- Publish measured installed-consumer and historical closure audit receipts.
- Keep retrieval budget, penalty, and acceptance-audit evidence synchronized.

## [0.23.0] - 2026-07-12

### Added

- Incremental Merkle DAG + change journal for context identity (issue #208, Step 2).
- Context snapshot schema, identity and CLI (issue #208, Step 1 — AC 1-2).
- Simplicio Agent as canonical mapper consumer; hermes kept as deprecated alias (issue #209).

## [0.22.0] - 2026-07-12

### Added

- Persistent, token-budgeted retrieval indexing for task context selection (issue #199).
- Stable retrieval-index receipts for downstream dev-cli consumers.

### Fixed

- Safe recovery of orphaned mapper index locks.


## [0.20.0] - 2026-07-11

### Added

- Deterministic task orientation, task-aware handoff, task batches, and AC/RN traceability contracts.
- Behavioral scorecard, cross-repository conformance, and product/template drift gates.
- Versioned visualization bundles, provenance, safe previews, and normalized diagnostics.
- Crash-safe index lock recovery and strict Runtime response validation.

## [0.19.0] - 2026-07-09

### Added

- Token/context budget guard in CI (`scripts/token_budget.py`, issue #174):
  estimates token cost for `AGENTS.md`/`CLAUDE.md`, the largest
  `simplicio_mapper/` modules, and the committed `.simplicio/*.json`-shaped
  contract fixtures, and fails the `python-ci.yml` `python-tests` job when
  any artifact grows more than 25% above the committed baseline
  (`scripts/token_budget_baseline.json`). Default estimator is the stdlib
  heuristic `heuristic:chars-div-4`, with `tiktoken` used automatically when
  installed. `--self-test` proves the guard fails on a simulated regression.
- Native delegation for `ask impact` and `ask tests-for` (issue #174),
  extending the existing `ask precedent` pattern to the two verbs measured
  as most expensive locally (`scripts/measure_verbs.py`,
  `scripts/measure_verbs_report.json`): `ask impact` is delegated behind
  `SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT`, `ask tests-for` behind
  `SIMPLICIO_MAPPER_NO_RUNTIME_TESTS_FOR`. Both validate the
  `simplicio.ask/v1` envelope, apply a 10s timeout, and fall back to the
  existing local implementation on any failure (missing binary, kill-switch,
  non-zero exit, timeout, malformed JSON, or schema mismatch) — no silent
  fake-pass.
- Savings ledger per verb (`simplicio_mapper/savings.py`): every native
  delegation hit records a `simplicio.savings-event/v1` entry to
  `.simplicio/ledger/savings-events.jsonl`
  (`source=native-delegation:<verb>`, `proof_kind` always `"estimated"`),
  mirroring the `simplicio-dev-cli` savings-event format without importing
  its code. Opt out with `SIMPLICIO_DISABLE_RUN_LOG`.

## [0.18.0] - 2026-07-07

### Changed

- CI/template hardening: fixed the self-repo guard in `ci.yml`/`dod.yml`
  after the repository rename to `wesleysimplicio/simplicio-mapper`,
  reduced Playwright to Chromium-only for this CLI-centric suite, added
  Python coverage gating (`pytest-cov`, floor 88%), pip caching, a
  non-blocking dependency-audit job, Dependabot config for npm/pip/cargo/
  GitHub Actions, Trusted Publishing OIDC wiring for PyPI, and a new
  guarded `publish-npm.yml` for the still-active npm scaffolder channel.
- Mapper core: deep artifact builds now memoize file contents within a run
  (single-read reuse across parse/precedent/symbol/call-graph passes),
  emit deterministic `project_map.degraded` metadata, record skipped large
  files, extract imports/symbols for Go/Rust/Java/Kotlin/PHP/Ruby, and
  build up to three ranked precedents per file with deterministic
  round-robin capping.
- Docs/spec sync: README no longer hardcodes a stale local version claim or
  overstates Node/Python parity, `AGENTS.md`/`CLAUDE.md` now describe npm as
  an active scaffolder channel, `docs/YOOL_TUPLE_HAMT.md` became a stub that
  points to the root canonical spec, and `scripts/check-doc-sync.js` now
  checks/regenerates that relationship too.

## [0.17.0] - 2026-07-07

### Added

- `ask precedent "<query>"` verb — searches the native `simplicio` runtime's
  SQLite/FTS5 precedent memory when the binary is available (`simplicio
  precedent search --json`), falling back to local tag-overlap ranking over
  `.simplicio/precedent-index.json` otherwise. First real precedent *query*
  capability in this repo (previously only built the index, never searched
  it). Native results carry `source: "runtime-precedent-search"`; the local
  fallback carries `source: "local-tag-overlap"`, both capped at the top 5
  matches.

## [0.16.0] - 2026-07-07

### Added

- `scripts/dogfood.py` — self-dogfooding (issue #165): runs the real,
  packaged `simplicio-mapper index . --json` CLI against this repo's own
  working tree, validates the result against the versioned
  mapper-artifacts contract (`contracts/mapper-artifacts/v1/`, issue
  #157), and publishes a stable, committed snapshot
  (`project-map.json`/`precedent-index.json`/`architecture-inventory.json`
  + `_meta.json`) in `examples/ecosystem-dogfood/`. `--check` verifies the
  snapshot without regenerating it. The cross-repo leg of the full recipe
  (mapper + simplicio-dev-cli + simplicio-loop working together) is
  documented, not executed, in `examples/ecosystem-dogfood/README.md` — it
  needs separate checkouts of all three repos, which a single-repo
  session/PR cannot safely orchestrate. `SIMPLICIO_ECOSYSTEM.md` (a
  generated file, issue #156) gained a "Dogfooding" section from its
  generator; `README.md`/`README.pt-BR.md` gained a "See it in action on
  our own repos" section. `tests/python/test_dogfood.py` covers `--check`
  against the committed snapshot and a real `regenerate()` run against a
  synthetic fixture.

### Changed

- Root `.md` consolidation follow-up (issue #161, ADR-007 addendum):
  `PRIVACY.md` and `SHOWCASE.md` moved to `docs/PRIVACY.md`/`docs/SHOWCASE.md`.
  Updated the 2 markdown links (`README.md`, `README.pt-BR.md`), the CLI
  help text (`bin/cli.js`), and the template comment
  (`.github/workflows-templates/telemetry-worker.js`); dropped the now-
  redundant standalone `package.json` `files` entries (`docs/` already
  ships them). Everything else evaluated in ADR-007 stays at root for the
  same documented reasons (standing cross-repo convention, `TEMPLATE_PATHS`
  membership or direct sibling of a `TEMPLATE_PATHS` file, or heavy
  cross-linking) — see the ADR-007 addendum for the file-by-file
  reasoning.

- `simplicio_mapper/mapper.py` (~1830 lines) split into the
  `simplicio_mapper/mapper/` package — `parse.py` (discovery/read: filesystem
  walk, text/import/symbol regex parsing, per-file role/importance tagging,
  precedent extraction, ~654 lines), `graph.py` (call-graph, symbol-index,
  architecture-inventory, macro-map construction, ~643 lines), `emit.py`
  (`.simplicio/*.json` serialization + rendered architecture docs, ~544
  lines), with `mapper/__init__.py` re-exporting the full original API
  (including internal `_prefixed` helpers other modules import directly) so
  `from simplicio_mapper.mapper import X` is unchanged. Pure move-and-wire
  refactor — verified byte-identical (modulo `generated_at`) output on
  `write_mapping_artifacts`/`write_architecture_docs`/`build_macro_map`
  against `tests/fixtures/parity-host`, before vs after. Adds
  `tests/python/test_mapper_{parse,graph,emit}.py` (direct unit tests per
  new module, imported straight from the submodule, not just the
  re-exported package surface). [#159]

### Added

- `simplicio_mapper/toon.py` — TOON (Token-Oriented Object Notation)
  encoder/decoder (`encode_toon`/`decode_toon`), a lossless, token-lean
  alternative to JSON for LLM prompt payloads (uniform arrays of objects
  collapse into a tabular block instead of repeating keys per element; see
  https://github.com/toon-format/toon). Wired into `simplicio-mapper index`
  and `simplicio-mapper handoff` via a new `--for-llm toon` flag.
  [#144]
- TOON encoder: the tabular path now accepts cells whose value is a list of
  scalars (`[a,b,c]` inline within a row), which is the mapper's own real
  array shape (`files[].exports/imports/roles`, `precedent-index.items[].tags`).
  Measured reduction on this repo's own survey artifacts went from
  7.1%/4.5%/8.4% to 28.3%/21.2%/0.1% char reduction (~37%/35%/0.5% on an
  approximate-token basis) — see `docs/toon-benchmark.md`. `decode_toon`
  now raises `TOONDecodeError` (a `ValueError`) on any malformed/truncated
  input instead of a bare `IndexError`, and rejects row/field-count
  mismatches instead of silently dropping data.
  `encode_toon_with_report()`/`--for-llm toon` now report which arrays (if
  any) fell back to embedded JSON and why (`toon_fallbacks`, logged to
  stderr on the CLI). `--for-llm toon` is now also wired on `inspect` and
  `ask`. [#148]
- `TOON-CONTRACT.md` — canonical spec for the ecosystem's TOON wire format
  and decode-error contract, plus `fixtures/toon-golden/` (a golden
  conformance corpus covering the known bug classes across the ecosystem's
  8 codecs: quoting, truncated tabular blocks, list cells, row/field
  mismatches, the `[1]`-scalar ambiguity) and a runner
  (`scripts/toon_contract_runner.py` / `tests/python/test_toon_contract.py`,
  `tests/unit/toon-contract.test.js`). `scripts/sync_toon_contract.py`
  gates local drift between the contract/corpus and their committed hash.
  [#149]
- `simplicio-mapper index --tagged`/`--confidence <tag>` — Asolaria
  confidence-tagging discipline (MEASURED/OPERATOR/CANON/UNVERIFIED) on the
  `counts` payload, with filtered-out entries always recorded (no
  deflate-gate). `simplicio-mapper index --geometry` — REALMATHPOS/
  FNV-1a64/sha16/citizenIdentity addressing per artifact path. P0 slice of
  the Asolaria integration proposal; P1/P2 documented as explicit follow-up
  in `docs/asolaria-integration.md`. [#150]

## [0.15.0] - 2026-07-02

### Added

Standalone SVG diagram artifacts ([#146](https://github.com/wesleysimplicio/simplicio-mapper/issues/146),
extends the Diagram contract from [#135](https://github.com/wesleysimplicio/simplicio-mapper/issues/135)).
Every Mermaid diagram type in `simplicio_mapper/diagrams.py` now has a
pure-Python, dependency-free SVG sibling (`render_flowchart_svg`,
`render_call_sequence_svg`, `render_state_diagram_svg`) — same determinism,
truncation-guardrail and adversarial-label-escaping guarantees as the
Mermaid renderer, written under `.simplicio/docs/diagrams/**` and linked
from the parent Markdown doc.

- `architecture.md`, `layers.md` link their standalone SVG next to the
  existing Mermaid block.
- `call-graph.md` gains an actual diagram (file-level flowchart) — it was
  previously a plain list.
- `flows.md` wires up the `sequenceDiagram` call-chain renderer that existed
  in `diagrams.py` since #135 but was never called, plus an SVG per flow
  (steps + sequence).
- `business-flows.md` gets an SVG per state machine.
- `export-docs` copies `.svg` alongside `.md` so exported image links keep
  resolving in the target directory.
- All new SVG artifacts are regenerated by the same paths that already
  regenerate their parent doc — full `docs`/`map` build and diff-driven
  `sync` (F5, #136) for architecture/layers/call-graph/flows.

## [0.14.0] - 2026-07-02

### Added

Flow Documentation Engine (epic [#131](https://github.com/wesleysimplicio/simplicio-mapper/issues/131),
spec `.specs/product/flow-documentation-spec.md`): ten commands that turn the
mapper's structural artifacts into technical + business flow documentation
that stays in sync with the code and keeps history. Full contracts in
[SIMPLICIO_INTEGRATION.md](SIMPLICIO_INTEGRATION.md#flow-documentation-engine-epic-131).

- `simplicio-mapper flows` — stack-neutral end-to-end flow inventory derived
  from the call graph (`simplicio.flow-inventory/v1`), generalizing the
  web-only `flowchart` command. [#133]
- `simplicio_mapper/diagrams.py` — deterministic Mermaid renderer (flowchart,
  sequence, state diagrams) with sanitized ids, escaped labels, and an
  explicit node/edge truncation guardrail, now used by `architecture.md` and
  `layers.md`. [#135]
- `simplicio-mapper sync` — diff-driven docs sync: maps a git diff to
  affected symbols/flows/docs and regenerates only what changed
  (`simplicio.docs-sync/v1`); `--check` reports staleness for CI without
  writing. [#136]
- `simplicio-mapper history` / `simplicio-mapper diff` — append-only
  architecture snapshots with semantic deltas and a generated
  `architecture-changelog.md`, garbage-collected by `--retention`. [#137]
- `simplicio-mapper survey` — the "new developer, day one" onboarding report
  (`simplicio.onboarding/v1`): how to run, reading order, main flows,
  business rules/glossary, conventions, help sources. [#132]
- `simplicio-mapper business` — observable business rules (limits,
  permission gates, validation, side-effects, invariants), state machines
  and a domain glossary cross-referenced against `.specs/product/DOMAIN.md`
  (`simplicio.business-rules/v1`). [#134]
- `simplicio-mapper ask` — low-token structured queries over already-built
  artifacts: `callers`/`callees`/`reaches`/`impact`/`flows`/`rules`/
  `tests-for`/`term` (`simplicio.ask/v1`). [#141]
- `simplicio-mapper drift` — spec-drift detection: unresolved template
  placeholders, orphan spec references, orphan high-impact code, and stale
  docs, plus a spec→code traceability matrix (`simplicio.spec-drift/v1`).
  [#138]
- `action.yml` — reusable composite GitHub Action that comments PR-affected
  flows and spec-drift status (idempotent, degrades gracefully on fork
  PRs); dogfooded in `.github/workflows/docs-sync.yml`. [#139]
- `template-manifest.json` + ADR-004 — classifies which `.specs/`/`docs/`
  paths are this product's own real content versus generic starter
  scaffolding, so `bin/cli.js` never ships simplicio-mapper's own specs to a
  host project. [#140]

### Changed

- `.specs/sprints/BACKLOG.md` now tracks this product's real backlog
  (rastreável via GitHub Issues) instead of generic template placeholder
  content.

## [0.13.0] - 2026-07-01

### Added
- `simplicio-mapper inspect <path>` — rich machine-readable inspection command
  (`simplicio.map-inspection/v1`) combining deep-pass status, on-disk artifact
  evidence (project map, precedent index, index state, map job, context cache),
  cache summary, and status warnings for downstream tooling.
- `simplicio-mapper handoff <path>` — status plus a compact context-pack
  bundle (`simplicio.map-handoff/v1`) for downstream agent hand-off, sharing
  the `--await`/`--timeout` polling helper already used by `scan`/`status`.
- `ContextCache.keys(limit=...)` on the context cache, used by the new
  `inspect`/`handoff` cache summaries.

### Fixed
- Resolved the version drift between `simplicio_mapper/__init__.py` and the
  `package.json`/`pyproject.toml` release metadata (previously 0.12.0 vs
  0.11.0), which `scripts/check-version-sync.js` now reports as aligned again.

## [0.11.0] - 2026-06-29

### Added
- Tier 3 niche/basic language support in the mapper (Python + Node mirror):
  - **Elixir, Erlang, Lua, R, Julia, Perl, MATLAB** — language detection,
    lightweight symbol extraction, dedicated import parsing, and inclusion in
    the heuristic call graph.
  - **HTML templates / basic web text** — `.heex/.leex/.eex/.erb`,
    `.html/.htm/.xhtml`, and `.css/.scss/.sass/.less` are now inventoried as
    first-class text/code assets instead of being skipped; HTML/template IDs
    and component-like tags plus CSS selectors are extracted as lightweight
    symbols.
  - `.m` files now use a safe heuristic: Objective-C when Objective-C markers
    are present, otherwise MATLAB during deep mapping; shallow/macro mode keeps
    the previous Objective-C default to avoid regressions.
  - Extended `LANGUAGE_BY_EXT`, `TEXT_EXTS`, `_CALL_GRAPH_LANGUAGES`, import
    parsers, symbol extractors, and `context-pack` language labeling.

## [0.10.0] - 2026-06-29

### Added
- Tier 1/2 language support in the mapper (Python + Node mirror):
  - **Dart, C, C++, Swift, Objective-C, Vue, Svelte, Scala** — language
    detection, per-language symbol extraction, dedicated import parsing, and
    inclusion in the call graph.
  - **SQL** — symbol extraction for tables / views / functions / procedures
    (intentionally excluded from the call graph; SQL has no call sites).
  - Extended `LANGUAGE_BY_EXT`, `TEXT_EXTS` and `_CALL_GRAPH_LANGUAGES`; added a
    `_NATIVE_IMPORT_LANGUAGES` guard so new languages always use the pure-Python
    import path (the optional Rust crate only covers the original set).
  - "Languages with structural extraction" section in `SIMPLICIO_INTEGRATION.md`.

## [0.9.0] - 2026-06-29

### Added
- Two-tier async mapper (issue #120):
  - `mapper.build_macro_map(cwd)` + `simplicio-mapper macro <path>` producing the
    sub-second `simplicio.macro-map/v1` skeleton from filenames + manifests only
    (no per-file content reads), with `confidence: "shallow"` (#121).
  - `simplicio-mapper scan <path>` returning a `simplicio.map-job/v1` envelope:
    macro inline + deep-pass pointers, deep in background by default,
    synchronous under `CI=true`/`--sync`, `--await` to block until terminal,
    persisted to `.simplicio/map-job.json` (#122).
  - `simplicio-mapper status <path>` deriving `deep_running|complete|failed|unknown`
    from `index.lock` + `index-state.json` freshness + `map-job.json`, with a
    shared `--await`/`--timeout` helper (#123).
  - `ADR-003-two-tier-async-mapper.md` and a "Two-tier async mapper" section in
    `SIMPLICIO_INTEGRATION.md`.
- `simplicio-mapper flowchart <path>` command and the
  `simplicio.service-flowchart/v1` contract. Builds a two-faced service map
  and renders it as Mermaid in `.simplicio/docs/flowchart.md`:
  - Frontend face — Angular screens linked to the services/endpoints in
    their module scope, clickable buttons (`(click)` handlers) tied to the
    endpoints their handler bodies call, and the *observable* rules encoded
    per screen (route guards, persona gating, dynamic params, form
    validators). Client calls that match no screen scope are listed as
    unlinked services.
  - Backend face — per server route (Azure Functions C# and FastAPI
    Python): layer, auth level, request/response payload types, external
    function-call count, database-access detection, and an ordered process
    flow rendered as a per-endpoint Mermaid diagram.
- `flowchart.md` is now generated as part of `simplicio-mapper docs`,
  `index --docs` and copied by `export-docs`.
- "Service Flowchart Contract" section in `SIMPLICIO_INTEGRATION.md`.

## [0.8.0] - 2026-06-02

### Added
- `simplicio_mapper.mechanical_edit` producer for the canonical
  `simplicio.mechanical-edit/v1` contract (closes #110): `snapshot_hash`,
  `range_hash`, `is_binary`, `extract_file_entry`, and `build_context`,
  with binary/missing-file refusal and large-file compact mode.
- `simplicio_mapper.context_pack` producer for `simplicio.context-pack/v1`
  and `simplicio_mapper.context_cache.ContextCache` for
  `simplicio.context-cache/v1` (closes #115): callers/imports from the
  call graph, related tests from the project map, per-range hashes, and
  `needs_broader_context` with concrete reasons when upstream artifacts
  or stable anchors are missing.
- "Native Runtime Contract" (closes #95), "Mechanical Edit Contract"
  (closes #110), and "Context Packs and Hash-Based Cache" (closes #115)
  sections in `SIMPLICIO_INTEGRATION.md`.
- Python `ruff` configuration and dev extra plus a `python-lint.yml`
  workflow (closes #101).
- `scripts/check-version-sync.js` plus a `version-sync` job in
  `scaffold-self-check.yml` (closes #102).
- `python-ci.yml` matrix workflow running pytest across Python 3.10–3.12
  plus a `cargo test` + `maturin develop` parity check for the Rust crate
  (closes #97); `publish-pypi.yml` now gates on `pytest` passing before
  building distributions.
- Node ↔ Python mapper parity test (`tests/python/test_parity.py`) with
  a deterministic fixture under `tests/fixtures/parity-host/`
  (closes #98).
- Coverage for previously untested CLI paths — `--docs-only`,
  `--json-only`, `--changed-only`, `--stack` / `--product-name` hint
  injection, `index` failure boundary, and the `_watch` loop
  (closes #103).

### Changed
- Endpoint path normalization in `simplicio-mapper endpoints` is now
  project-agnostic (closes #104): the EVT-specific resource regexes are
  gone; only placeholders, UUIDs, and numeric segments collapse to
  `{id}`.
- Docusaurus site renamed from `llm-project-mapper` to `simplicio-mapper`
  (`baseUrl`, `projectName`, navbar / footer URLs) and a `0.7.3` docs
  snapshot was cut so the version dropdown matches the live release
  (closes #100).
- `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and
  `.specs/product/{VISION,DOMAIN,PERSONAS}.md` no longer carry
  `<STACK>` / `<APP_NAME>` / `<PRODUCT_NAME>` placeholders; they now
  describe the real Python + Node + optional Rust stack and the actual
  command surface (closes #99).
- Dropped the `publish-npm.yml` workflow; the project ships PyPI-only
  going forward.

## [0.7.3] - 2026-06-01

### Changed
- Restored the original operational README guide under the new growth-oriented landing page, preserving setup, architecture, video, mapper flags, and endpoint inventory details.
- Added Project DNA notes across localized READMEs and updated the globalization standard to require additive README refreshes rather than replacing repo-specific substance.
- Included the richer README in the Python and npm package metadata for the refreshed documentation release.

## [0.7.2] - 2026-06-01

### Changed
- Rebuilt the README as a multilingual growth page inspired by Understand Anything and 50k+ star repository patterns.
- Added canonical translations under `READMEs/` for the full Simplicio language set and documented the new README globalization standard.
- Included the translations and globalization standard in package source metadata.

All notable changes to **LLM Project Mapper** are documented in this file.

Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]`n`n## [0.21.0] - 2026-07-11`n`n### Added`n`n- Incremental graph deltas, clustering metrics, and Mapper-to-Canvas compatibility fixtures.`n

### Changed
- `simplicio-mapper endpoints` endpoint path normalization is now project-agnostic
  (closes #104). The previously hardcoded EVT-specific collapses for
  `/api/v1/(areas|assessments|disciplines|...)/<slug>`,
  `/api/v1/governance/(skill-versions|skills)/<slug>`,
  `/api/v1/knowledge-assessment/runs/<slug>`,
  `/api/v1/llm-gateway/(runs|skills|traces)/<slug>` and
  `/api/v1/(clients/)?projects/<slug>` have been removed. The normalizer still
  collapses path/query placeholders (`${foo}` / `{foo}`), UUIDs, and numeric ID
  segments — these are stable, generic patterns. Downstream projects that
  relied on slug-after-collection collapsing should switch their fixtures to
  numeric or placeholder IDs (the `simplicio.endpoint-inventory/v1` schema is
  unchanged).

## [0.7.1] - 2026-06-01

### Added
- `simplicio-mapper index|map|update --background` starts a detached refresh
  and writes `.simplicio/background-index.log`, so long-running inventory
  updates can proceed without blocking the foreground workflow.
- `simplicio-mapper index|map|update --docs-only` renders the Markdown wiki
  view without emitting the index JSON payload, useful for docs-only refreshes.
- Compatibility aliases `--json-only` and `--changed-only` for orchestration
  scripts that distinguish JSON-only and changed-file refresh modes.

### Changed
- `simplicio-mapper index` now uses `.simplicio/index.lock` to avoid overlapping
  foreground/background refreshes and returns a stable `status=skipped,
  skipped_reason=locked` JSON contract when another refresh is active.

## [0.7.0] - 2026-06-01

### Added
- Living architecture inventory artifacts:
  `.simplicio/architecture-inventory.json`,
  `.simplicio/symbol-index.json`, and `.simplicio/call-graph.json`, with
  module/layer evidence, symbol file+line metadata, import edges and heuristic
  caller/callee relationships.
- `simplicio-mapper docs <path>` renders `.simplicio/docs/*.md` from the JSON
  inventory for wiki/review workflows.
- `simplicio-mapper export-docs <path> --target <dir>` copies rendered Markdown
  to an explicit local docs target without publishing remotely.
- `--docs` support for map/index refreshes when JSON and Markdown should be
  updated in one pass.

### Changed
- Mapper artifact writes now use temp-file + atomic rename semantics to reduce
  risk of partially written JSON during live/background refreshes.
- Python builds pin Hatchling to the current Metadata-Version 2.4-compatible
  line so `twine check` and the PyPI publish workflow stay reproducible.

## [0.6.10] - 2026-05-31

### Added
- `simplicio-mapper screens <path> --json` inventories Angular route screens,
  redirects, personas, guarded routes and dynamic route parameters using the
  stable `simplicio.screen-inventory/v1` schema. This supports full-screen
  evidence runs such as EVT's web/API/PostgreSQL Playwright validation.

## [0.6.9] - 2026-05-31

### Changed
- Endpoint inventory JSON now includes `sources` on each
  `missing_from_server` item, so cross-repo alignment work can jump straight
  from a missing route to the screen or client file that requires it.

## [0.6.8] - 2026-05-31

### Changed
- `simplicio-mapper index` now accepts `--update` as a compatibility alias for
  refresh workflows, so existing Simplicio scripts can call the Python indexer
  without special branching.
- Endpoint inventory now resolves Angular service `baseUrl` constants,
  `environment.apiUrl`, and template-string path parameters. This lets
  `simplicio-mapper endpoints ./web --against ./api` inventory real Angular
  services instead of only literal URLs in tests.
- Python endpoint inventory now captures direct page/client calls such as
  `api.patch(...)` and `api._client.put(...)`, while ignoring test files and
  FastAPI route decorators so AI-Agents runtime demand is not undercounted or
  duplicated.

## [0.6.7] - 2026-05-31

### Added
- `simplicio-mapper endpoints <path> --against <server-root> --json` extracts
  normalized client calls and server HTTP routes, then reports
  `missing_from_server` using the stable
  `simplicio.endpoint-inventory/v1` schema. This turns cross-repo endpoint
  alignment checks into a reusable mapper workflow.

## [0.6.6] - 2026-05-31

### Changed
- Git status collection now uses `--untracked-files=all`, so files inside new
  directories are marked as `??` in `files[].git_status`, `changed_files`, and
  `recent_changes` instead of looking clean in mapper artifacts.

## [0.6.5] - 2026-05-31

### Changed
- Python mapper now skips generated `output/` trees, including Playwright
  HTML reports and trace result folders, so live evidence artifacts do not
  pollute `.simplicio/project-map.json`.

## [0.6.4] - 2026-05-31

### Changed
- Python mapper skips generated dependency/cache directories from real
  Angular/.NET/Python projects (`.angular`, `obj`, `.pytest_cache`,
  `.mypy_cache`, `.ruff_cache`, `.gradle`, `target`) while preserving source
  `bin/` folders outside .NET project roots.
- `simplicio-mapper index` now returns exit code `0` for `already_fresh`
  indexes, preserving the structured `status=skipped` payload without making
  idempotent automation look failed.
- C# / ASP.NET symbol extraction now records controller classes and route
  attributes for endpoint-alignment work.

## [0.6.3] - 2026-05-31

### Changed
- Refresh Node, docs-site, video, VS Code extension, and Python dependency
  floors to the latest compatible releases used by the Simplicio E2E flow.
- Keep `@mermaid-js/layout-elk` on the Docusaurus-compatible `0.1.x` line while
  updating the surrounding Docusaurus and React packages.

## [0.6.2] - 2026-05-30

### Changed
- `--update` no longer appends or rewrites `.gitignore` unless
  `--append-gitignore yes` is passed explicitly.
- The recommended `.gitignore` block now keeps shared starter context visible
  in Git (`AGENTS.md`, `.agents/`, `.skills/`, `.specs/`,
  `.starter-meta.json`) and only ignores local state, caches, build output,
  env files, logs, and test artifacts.

### Added
- `simplicio-mapper index <path>` idempotent orchestration command for
  SendSprint. It writes the standard `.simplicio/project-map.json` and
  `precedent-index.json`, short-circuits fresh indexes with exit code `2`, and
  exposes a stable `--json` payload with artifact paths, counts, changed files
  and skipped reason.

## [0.6.0] - 2026-05-28

### Added
- Optional Rust acceleration crate `rust/simplicio_mapper_rs` exposing
  `sha256_hex` and `parse_imports` via PyO3, plus `simplicio_mapper._native`
  shim that routes mapper hot paths to it when installed and falls back to the
  pure-Python implementation otherwise (closes #83). ADR-002 documents the
  evaluation.
- Standalone Python distribution `simplicio-mapper` on PyPI: lightweight
  `simplicio_mapper.mapper` port of the Node mapper plus a `map` / `update` CLI
  exposed as the `simplicio-mapper` and `llm-project-mapper` console scripts.
  Generates the same `.simplicio/project-map.json` and `precedent-index.json`
  without requiring a Node toolchain.
- Performance optimizations for the Python mapper (closes #82): `orjson` for
  faster JSON serialization, persistent `diskcache` of per-file processing keyed
  by path/size/mtime, and `__slots__`-backed internal models (`ProjectFile`,
  `CodeEntity`, `PrecedentItem`) for lower memory on large projects. Schema and
  artifact contracts remain stable; the package now ships with two lightweight
  runtime dependencies (`orjson`, `diskcache`) instead of being dependency-free.
- `map` / `update` CLI subcommands for generating and incrementally refreshing
  `.simplicio/project-map.json` and `.simplicio/precedent-index.json`.
- Rich machine-readable mapper artifacts with file inventory, roles, imports,
  exports, entity extraction, architecture signals, dependency context, changed
  files, and precedent snippets for downstream consumers.
- `SIMPLICIO_INTEGRATION.md` documenting the JSON contract and Python consumer
  example for `simplicio-dev-cli`.
- `skillopt` command and `bin/skillopt.js` wrapper implementing the [SkillOpt](https://microsoft.github.io/SkillOpt/) loop (Rollout → Reflect → Edit → Gate): optimizes a natural-language skill document against a task suite, treating the skill as the only trainable artifact. Emits `best_skill.md`, an optional run report, and a content-addressed receipt under `.catalog/receipts/`. Engine in `scripts/skillopt/engine.js` is deterministic, dependency-free, and exposes a pluggable scorer for real LLM adapters.
- `.skills/skillopt/SKILL.md` skill manifest plus runnable `example.skill.md` / `example.suite.json` fixtures.
- Root-level `YOOL_TUPLE_HAMT.md` vendored alongside the existing `docs/` copy so the canonical pattern spec is reachable directly from the repository root and ships with the npm package.
- `build-hamt-catalog` wrapper plus stdlib-only `scripts/build_hamt.py`, enabling `npx @wesleysimplicio/llm-project-mapper build-hamt-catalog` to emit `.catalog/agents.json`.
- Runtime scaffold defaults for `.catalog/.gitkeep`, `.catalog/agents.json`, `.receipts/.gitkeep`, and optional `mcp/server.{ts,py}` edge adapters via `--mcp-edge`.
- Dedicated docs-site coverage for YOOL / tuple / HAMT, including the public `/yool-tuple-hamt` route and regression tests for the new page.

### Changed
- Bootstrap now writes the structured mapper artifacts automatically and records
  the `simplicio` integration block in `.starter-meta.json`.
- INIT prompts now require validation of `.simplicio/project-map.json` and
  `.simplicio/precedent-index.json` during agent inspection.
- `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` now point to the root spec, document the receipts schema, and align the generated catalog output on `.catalog/agents.json`.
- The Node bootstrap path now mirrors the shell/PowerShell runtime scaffold so fresh `npx` installs create the catalog, receipts, and optional MCP edge templates consistently.

## [0.4.2] - 2026-05-19

### Added
- `.skills/rtk-cli/SKILL.md` skill manifest (force-added past the `.skills/`
  gitignore exclusion to match the other tracked starter skills). Documents
  RTK CLI usage with trigger, steps, do-not list, and DoD. Already shipped
  via npm tarball; now tracked in git so consumers can discover it on
  GitHub.

### Notes
- Closes #71. RTK guidance was already present in AGENTS.md, CLAUDE.md and
  `.github/copilot-instructions.md` — the missing piece was the skill folder
  visibility on GitHub.

## [0.4.1] - 2026-05-19

### Added
- Vendored YOOL/tuple/HAMT spec at `docs/YOOL_TUPLE_HAMT.md` (v0.2 from
  https://github.com/wesleysimplicio/yool-tuple-hamt) plus `AGENTS.md` /
  `CLAUDE.md` blocks defining the agent capability declaration template
  (`yool_id`, `authority`, `lane`, `agent_terms` with **mandatory**
  `cpu_quota_pct`, `disk_quota_mb`, `timeout_s`).
- `bootstrap.sh` now scaffolds `.catalog/` (receipts/, artifacts/, README) so
  the HAMT catalog has a predictable home in every starter-generated project.
- Guardrail rationale anchored to Victor Genaro's review: *"precisa de
  guardrail pra não fritar o processador. Você precisa de garbage collector
  também pra não encher 100% do disco."*

## [0.4.0] - 2026-05-19

### Added
- Added a local `rtk-cli` skill that teaches agents when and how to use RTK's compact shell output for repository exploration, `git`, `grep/find`, and verbose validation commands.

### Changed
- Updated `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and session-start hooks to prefer RTK for shell-heavy workflows when it is installed, while explicitly keeping `curl`, `playwright`, and interactive or streaming commands on raw output.
- Allowed `Bash(rtk *)` in `.claude/settings.json` so Claude Code sessions can invoke RTK without extra local permission friction.
- Extended regression coverage to assert the shipped RTK skill, hook reminders, and contributor docs stay aligned.

## [0.3.2] - 2026-05-18

### Changed
- Documented a project-specific default release policy: release-relevant work in `llm-project-mapper` must finish with npm, Git tag, GitHub Release, `main`, and validation all synchronized in the same cycle.

## [0.3.1] - 2026-05-18

### Changed
- Replaced the remaining historical legacy-name references in repository documentation so the package and project naming stay fully aligned as `llm-project-mapper`.

## [0.3.0] - 2026-05-18

### Added
- Automatic local project mapping immediately after bootstrap. `bin/auto-map.js` now inspects the host project, infers stack/domain/team/integrations, generates `.specs/journal/inspection-YYYY-MM-DD.md`, and pre-fills the starter-managed docs without waiting for a manual `INIT.md` handoff.
- Regression coverage for the automatic mapping flow in both `tests/unit/cli-install.test.js` and `tests/e2e/cli.spec.ts`, including placeholder-clean assertions on the generated starter-managed files.
- `vscode-extension/` scaffold for `wesleysimplicio.llm-project-mapper-vscode`. Ships a TreeView for `.specs/sprints/`, plus commands `lpm.openCurrentTask`, `lpm.createAdr`, `lpm.runInit`, `lpm.refresh` and a live status-bar indicator. Pure filesystem walker (`src/scan.ts`) covered by `node --test` unit tests.
- `--telemetry on|off` flag on `bin/cli.js` (default off). Honored via `LLM_PROJECT_MAPPER_TELEMETRY` env var. Persists user choice to `~/.config/llm-project-mapper/telemetry.json`. Hard-disabled under `CI`, `--dry-run`, or when no `LLM_PROJECT_MAPPER_TELEMETRY_URL` is set.
- `PRIVACY.md` documenting telemetry payload shape, opt-in mechanics, and kill switches.
- `.github/workflows-templates/telemetry-worker.js` — reference Cloudflare Worker template (PII-sanitized aggregator).
- README sections (EN + PT-BR) under "Companion tooling" linking the new extension and PRIVACY.md.
- `tests/unit/cli-telemetry.test.js` — 5 new tests covering opt-in/out persistence and help-text presence.

### Changed
- Bootstrap messaging now explains that the mapping pass starts automatically and that `INIT.md` is an optional second-pass refinement step.
- Package version bumped to `0.3.0` to ship the automatic mapping workflow and updated regression coverage.

## [0.2.2] - 2026-05-18

### Added
- Local PT-BR + EN narration pipeline for `video/assets/why-llm-project-mapper{,-en}.mp4`, generated from `video/src/why/narration.json` via `say` + `ffmpeg`.
- Burned-in captions for the Why video via `@remotion/captions`, driven by the same narration source file.
- Versioned `video/public/captions/why-{pt,en}.srt` exports from the narration pipeline for timing review.
- `video/TTS-EVALUATION.md` comparing ElevenLabs, OpenAI `tts-1-hd`, and Azure Neural for future upgrades.

### Changed
- `video/public/sfx/rock-bg.mp3` is now mixed under narration at `volume=0.15`.
- Root lint now checks `video/scripts/*.mjs`.

## [0.2.1] - 2026-05-18

### Added
- `docs-site/` Docusaurus hub with GitHub Pages deployment workflow, local search, and versioned docs generated from repository markdown sources.
- Animated overlay-install screencast at `assets/overlay-install.svg`, embedded in the README and install guides.
- `LICENSE` (MIT) at repository root and shipped in npm tarball.
- `CHANGELOG.md` (this file) covering history v0.1.0 → v0.2.0.
- `npm run lint` script — wraps ESLint-equivalent checks for `bin/`, `tests/`, `scripts/`, shell scripts and Markdown.
- `npm test` script — `node --test tests/unit` runner (no extra dependency).
- Unit tests for `bin/cli.js`: `parseArgs`, `detectStack`, `detectProjectMode`, `mergeGitignore`, `.starter-meta.json` shape.
- Concrete `tests/e2e/smoke.spec.ts` exercising the real `npx` install flow (dry-run, fresh install, update, stack detection, monorepo detection).
- `INIT.en.md` + `INSTALL.en.md` — English translations of the install guide.
- `docs/placeholders.md` — catalog of every `<PLACEHOLDER>` token used by the starter.
- `docs/api-examples/{rest,graphql,webhook,cli}.md` — fill-in templates for documenting APIs.
- `SHOWCASE.md` — community list of consumer projects.
- PSScriptAnalyzer job in `scaffold-self-check.yml` covering `bootstrap.ps1` and `*.ps1` scripts.
- Cross-platform matrix (ubuntu/macos/windows) in `scaffold-self-check.yml`.
- `--preset <stack>` flag in `bin/cli.js` (nextjs, dotnet, fastapi, go, rails, flutter) — preset list at `--preset list`.
- `--no-update-check` flag and embedded semver notifier in `bin/cli.js`.
- `.github/workflows-templates/llm-project-mapper-init.yml` — GitHub Action wrapper template.
- `docs/sessionstart-hook.md` — operational doc for `.claude/hooks/session-start-skills.sh`.

### Changed
- `package.json` now lists `LICENSE`, `CHANGELOG.md`, `INIT.en.md`, `INSTALL.en.md` in `files[]` so they ship with the npm package.
- `ci.yml` and `dod.yml` no longer skip the `llm-project-mapper` repo itself (eat-your-own-dog-food).
- `presentation/slides.md` regenerated after rename — PDF + PPTX rebuilt.

### Fixed
- Residual legacy naming mentions removed from `_BOOTSTRAP.md` and inline examples (legacy detection in `bin/cli.js` preserved for back-compat overlays).

## [0.2.0] - 2026-05-16

### Changed
- **BREAKING** Renamed the npm package to `@wesleysimplicio/llm-project-mapper`. ([#15](https://github.com/wesleysimplicio/llm-project-mapper/pull/15))
- **BREAKING** Renamed the CLI command to `npx @wesleysimplicio/llm-project-mapper`.
- **BREAKING** Source override env var renamed to `LLM_PROJECT_MAPPER_SOURCE`.
- Video compositions renamed to `WhyLlmProjectMapper{PT,EN}`.
- Assets renamed to `assets/llm-project-mapper-*.png`.

### Deprecated
- The previous package name is marked deprecated and redirects users to `@wesleysimplicio/llm-project-mapper`.

## [0.1.6] - 2026-05-15

### Added
- Rock backing track on the Why explainer video (kick/snare/hi-hat/power chord drone synthesized with ffmpeg). ([#14](https://github.com/wesleysimplicio/llm-project-mapper/pull/14))
- Static cover linked from `README.md` and `README.pt-BR.md`.

### Changed
- Why video re-paced: 80s → 53s, 17.7 MB → 14.1 MB. Animation delays reduced from `frame - 50..280` to `frame - 4..170`.

## [0.1.5] - 2026-05-15

### Added
- WhyLlmProjectMapper explainer video in PT-BR and EN (9 scenes, 80s, 1080p). ([#12](https://github.com/wesleysimplicio/llm-project-mapper/pull/12))
- `video/src/why/` isolated directory with own i18n provider (`WhyLangProvider`, `STRINGS_WHY`).
- npm scripts `build:why`, `build:why:en`, `build:why:all`, `still:why`, `still:why:en`.

### Fixed
- Hook execution repair + starter hero image.

## [0.1.4] - 2026-05-14

### Added
- `workflow_dispatch:` trigger on the `Publish to npm` workflow. ([#10](https://github.com/wesleysimplicio/llm-project-mapper/pull/10))
- `Verify npm auth (whoami)` early-failure step on the publish workflow.

## [0.1.3] - 2026-05-14

### Added
- Safe starter update command (`npx ... --update`).
- `scripts/update-starter.sh` / `scripts/update-starter.ps1`.

## [0.1.2] - 2026-05-13

### Added
- `.github/workflows/publish-npm.yml` — auto-publishes to npm on every push to `main` when `package.json` version differs from registry, with `--provenance --access public` and automatic `vX.Y.Z` tag. ([#7](https://github.com/wesleysimplicio/llm-project-mapper/pull/7))

## [0.1.1] - 2026-05-13

### Added
- `INSTALL.md` — step-by-step overlay install guide for existing host projects. ([#4](https://github.com/wesleysimplicio/llm-project-mapper/pull/4))
- Always-on skills: `ralph-loop`, `caveman`, `everything-claude-code`. ([#3](https://github.com/wesleysimplicio/llm-project-mapper/pull/3))
- `.claude/hooks/session-start-skills.sh` SessionStart hook.
- `# Agentic starter tracked files` block to `.gitignore`. ([#5](https://github.com/wesleysimplicio/llm-project-mapper/issues/5), [#6](https://github.com/wesleysimplicio/llm-project-mapper/pull/6))

### Changed
- Replaced `projects/` convention with workspace-signal mode detection (`pnpm-workspace.yaml`, `lerna.json`, `nx.json`, `turbo.json`, `rush.json`, `package.json` workspaces, or ≥2 manifests under `apps/`/`packages/`/`services/`). ([#4](https://github.com/wesleysimplicio/llm-project-mapper/pull/4))
- Unified `.starter-meta.json` schema across `bootstrap.sh`, `bootstrap.ps1`, `bin/cli.js`.

## [0.1.0] - 2026-05-09

### Added
- Initial release.
- Master instruction file `AGENTS.md` + mirrors `CLAUDE.md` and `.github/copilot-instructions.md`.
- `.specs/` skeleton (product, architecture, workflow, sprints).
- `.skills/` catalog (playwright-e2e, conventional-commits, _template).
- `.agents/` catalog (ralph-loop, tdd, reviewer, architect).
- `.claude/` hooks (post-edit, pre-commit).
- `.codex/config.toml`.
- CI workflows (`ci.yml`, `dod.yml`, `scaffold-self-check.yml`).
- PR + Issue templates.
- Bootstrap installers: `bootstrap.sh`, `bootstrap.ps1`, `bin/cli.js` (`npx @wesleysimplicio/llm-project-mapper`).
- Marp presentation (`presentation/slides.md` → PDF + PPTX).
- Remotion skills tutorial video in PT-BR. ([#1](https://github.com/wesleysimplicio/llm-project-mapper/pull/1))
- i18n layer + English skills tutorial video. ([#2](https://github.com/wesleysimplicio/llm-project-mapper/pull/2))

[Unreleased]: https://github.com/wesleysimplicio/simplicio-mapper/compare/v0.19.0...HEAD
[0.19.0]: https://github.com/wesleysimplicio/simplicio-mapper/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/wesleysimplicio/simplicio-mapper/compare/v0.17.0...v0.18.0
[0.6.3]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.6.1...v0.6.2
[0.4.0]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/wesleysimplicio/llm-project-mapper/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.2.0
[0.1.6]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.6
[0.1.5]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.5
[0.1.4]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.4
[0.1.3]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.3
[0.1.2]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.2
[0.1.1]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.1
[0.1.0]: https://github.com/wesleysimplicio/llm-project-mapper/releases/tag/v0.1.0

## Unreleased / In Progress (EVT Alignment Work)

### Improvements to mapper for real enterprise monorepos
- Enhanced C# symbol extraction to detect ASP.NET controllers (`*Controller` classes) and HTTP attributes (`[HttpGet]`, `[HttpPost]`, `[Route]`, etc.).
- This was driven by the need to map endpoints across `beyondlabs-maturity_matrix-api` (.NET), `-web` (Angular), and `-ai-agents`.
- Better support for mixed-stack monorepos (Angular + .NET + Python agents).

These changes make `simplicio-mapper` significantly more useful for reverse-engineering and contract alignment tasks on existing large codebases.
## 0.26.7 — 2026-08-01

- Mapper Fastest Path follow-up: bounded async queue diagnostics, native batch
  parser fallback, canonical native-capability identity, memory budgeting, and
  the local fastest-path release quality command.
