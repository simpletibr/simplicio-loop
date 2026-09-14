# Changelog

## Unreleased

- Integrated ingest accepts public `simplicio.map-handoff/v1` from
  `simplicio-mapper handoff` as well as `simplicio.mapper-fast-handoff/v1`.
- Default `--mapper-mode` is `integrated` for ingest/build/refresh/understand/plan.
  Missing `--mapper-handoff` fails closed; bootstrap remains an explicit choice.
- CLI `--write` on apply/delivery/changeset materialize requires
  `SIMPLICIO_FAST_ALLOW_WRITE=1`. Mutation owner is simplicio-dev-cli.

## 2.0.32 - 2026-09-10
- Report the delivered source range and incomplete fidelity when bounded context cuts occur.
- Preserve requested ranges, byte offsets, omitted ranges, and separate delivered-content identity.

## 2.0.30 - 2026-08-23

- Add the versioned Fast–Local contract surface, deterministic policy
  conformance checks, and offline policy replay/simulation receipts.
- Integrate pressure-aware speculation policy, profiler guardrails,
  generation-bound decision caching, context/ranking batching, and Pareto
  representation selection without taking Local execution ownership.
- Add portable capability-ranking hot-path caching with deterministic benchmark
  evidence and preserve fail-closed behavior for unavailable telemetry.

## 2.0.29 - 2026-08-14

- Reconcile the Python package, Rust core, README badge, and release-integrity
  contract for the current main release train.

## [2.0.28] - 2026-08-14

- Require Mapper 0.26.20 for the integrated Fast path.
- Add QLT-001 operational coverage for Mapper handoff, Fast context and impact,
  idempotent ingest, and the missing-snapshot fail-closed path.

## [2.0.27] - 2026-08-10

- Synchronize the Fast release with the aggregate Loop stack.


## [2.0.26] - 2026-08-10

- Add the shared `simplicio.io/v1` envelope and document Fast retrieval-only responsibility.


## 2.0.25 - 2026-08-08

- Enforce centralized Mapper/Fast artifact generations, source digests, and
  evidence receipts across worker handoffs.
- Route the Fast CLI through the governed Runtime backend and harden
  artifact and resident-session integrity.
- Improve task-anchor context ranking and publish the project skills and
  capability inventory used by integrated agents.
- Preserve the published Mapper 0.26.x and Dev CLI 0.18.6+ floors for the optional integrated profile.

## 2.0.24 - 2026-08-03

- Accept Mapper type and method symbol kinds without crashing snapshot builds.

## 2.0.23 - 2026-08-02

- Publish the complete LLM-facing Fast command and feature index, including
  every snapshot, context, changeset, workspace, rollout, and conformance
  action with its `--help` discovery contract.
- Align the optional integrated dependency floors with Mapper `0.26.11` and
  Dev CLI `0.18.6` for the coordinated release train.


## 2.0.22 - 2026-08-02

- Synchronize the Fast release train with Mapper 0.26.10, Dev CLI 0.18.5,
  and Loop 3.38.29 after the merged semantic-compute delivery and release
  evidence slices.

## 2.0.21 - 2026-08-02

- Publish the latest semantic-compute delivery line with Python/Rust parity
  receipts, bounded SDK transport evidence, parser parity coverage, and
  resource/rollout verification artifacts.

## 2.0.20 - 2026-07-30

- Publish the executable Rust snapshot core alongside the legacy compatibility
  artifact for every supported platform, with a versioned engine-handshake
  receipt verified in CI before release assets are uploaded.

## 2.0.19 - 2026-07-30

- Align the verified Rust snapshot engine version with the Python package so
  installation health checks can select the native engine without degrading.
- Add a release-integrity gate that rejects Python/Rust version drift.

## 2.0.18 - 2026-07-30

- Align the integrated Python dependency floor with Mapper 0.26.1 and Dev CLI
  0.18.1 while preserving the Rust-free Python engine.

## 2.0.16 - 2026-07-28

- Harden Runtime-first bridges after the PRISM deep implementation: fail-closed admission, forged-manifest rejection, and Windows-safe spawn/stdio handling.
- Tighten quant benchmark contracts so unavailable sizes stay BLOCKED (never false MEASURED) and integrity/release gates stay aligned with package metadata.
- Close the V3 epic path on master: PrismArena, content-addressed context views, native precompiled bundle path, semantic/LiteRT scoring, and integrity sync.

## 2.0.15 - 2026-07-28

- Add the PRISM resident mmap arena, isolated task overlays, authority-bound
  context views, Runtime-first backend selection, and deterministic Python
  fallback.
- Keep the Python core dependency-free and move Mapper/Dev CLI integration to
  the explicit `integrated` extra.
- Add fail-closed native artifact verification and reproducible semantic and
  quantization benchmark receipts.

## 2.0.14 - 2026-07-27

- Publish the current master line with accelerated incremental refresh and the
  Loop-validated integrated-ready contract.

## 2.0.9 - 2026-07-27

- Publish the canonical .simplicio/fast snapshot defaults and V3 integration updates.

## 2.0.8 - 2026-07-27

### Fixed

- Publishes auditable Fast engine-selection receipts with measured Rust probing and fail-closed conformance routing.
- Restores Windows Python 3.14 close-on-exec handling for Git and Mapper subprocess probes.

## 2.0.6 - 2026-07-26

### Fixed

- Raises the validated snapshot capacity to 512 MiB for supported large Windows repositories.
- Emits SnapshotTooLarge before allocation/publication when the hard bound is exceeded.


## 2.0.5 - 2026-07-26

### Fixed

- Fails closed before parsing oversized source files on Windows with a structured error receipt.
- Propagates timeout and source-size bounds through the ingest path used by Loop.

## 2.0.4 - 2026-07-26

### Fixed

- Stabilizes Fast git, Mapper and workspace subprocess receipts on Windows Python 3.14 with explicit handle inheritance control.
- Keeps the structured dry-run native-output hash-mismatch rollback contract covered by regression tests.


### Fixed

- Recovers truncated or corrupt derived snapshots from authoritative source files.
- Validates rebuilt snapshots before atomic publication and preserves the prior generation on failure or timeout.
- Adds structured recovery and timeout receipts for Windows execution.
- Makes concurrent overlay JSON publication resilient to transient Windows locks.
- Uses physical-byte hashes for guarded apply while preserving CRLF and adapter validation.
- Adds regression coverage for recovery, timeout, concurrency and consecutive changesets.

## 2.0.2 - 2026-07-26

Safe native-hash fallback for guarded `apply` on Windows.

### Fixed

- Native Dev CLI refusals now produce a machine-readable
  `simplicio.fast.apply-receipt/v2` instead of an unversioned error.
- `apply` proves no-write or rolls back partial native mutations before using
  the explicit internal atomic fallback.
- Apply receipts include raw before/after SHA-256 values, outcome, reason code,
  write status and rollback evidence.
- Stale source hashes remain fail-closed, including immediately before each
  fallback replacement.

## 2.0.1 - 2026-07-26

Documentation and visual refresh for the Fast 2.x contract.

### Changed

- Clarified Fast's role for agents and LLMs: semantic project memory plus guarded change
  coordination, not an LLM, scheduler or policy authority.
- Expanded top-level CLI help and command inventory for tool discovery.
- Rewrote `AGENTS.md` around Mapper, Dev CLI, Loop and Runtime boundaries, receipts and safe
  generation handling.
- Added new hero, shared-memory and verified-flow illustrations under `assets/`.

## 2.0.0 - 2026-07-26

Simplicio Fast becomes a standalone project processor instead of requiring Mapper or Dev CLI.

### Added

- Cross-platform benchmark peak-RSS collection with deterministic partial receipts when the
  operating system cannot expose the metric.
- `ingest`: absorb a repository into the incremental binary snapshot.
- `understand`: resolve bounded, hash-verified context directly from a natural-language task.
- `plan`: compile understanding into `simplicio.fast.plandag/v2`.
- `apply`: validate and optionally write `simplicio.fast.changeset/v2` operations.
- Dry-run by default and SHA-256 guards for every edited source file.
- Deterministic validation command discovery for Python, Node and Rust projects.

### Architecture

- Mapper and Dev CLI are optional compatibility adapters.
- Fast owns project ingestion, semantic context, plan compilation and structured source edits.
- Runtime remains the authority for policy, execution and receipts.
- Loop remains responsible for slots, retries, convergence and delivery.

## 1.0.0 - 2026-07-26

First stable proof-of-concept release.

### Included

- Dependency-free Python user CRUD with HTTP endpoints.
- Versioned `.sfast` binary semantic snapshot.
- Read-only memory mapping with Python `mmap`.
- Python AST extraction for classes, functions and async functions.
- SHA-256 incremental reuse for unchanged source files.
- Atomic snapshot replacement.
- CLI commands `build`, `query` and `serve`, all with `--help`.
- Unit tests for CRUD, conflicts, snapshot queries and incremental rebuilds.
- Reproducible synthetic benchmark for wall time, CPU, RSS and incremental behavior.

### Compatibility contract

- Python 3.11 or newer.
- Source files remain the only source of truth.
- Snapshot format magic: `SFAST001`.
- Snapshot schema version: `1`.
- Snapshots are derived caches and may be rebuilt safely.

### Known limitations

- Python-only source analysis.
- Symbol lookup currently scans fixed binary records.
- No import, reference or call graph yet.
- No direct LLM, Mapper, Runtime or Loop adapter yet.
