# Goal Result

## Issue #262 scanner hardening (2026-07-23)

Status: locally verifiable scanner and package lanes strengthened; issue remains
blocked. Exact-policy corruption, renamed/oversized artifact, Python/Node
parity, HBP integrity, wheel install and archive scans are proven. The strict
source gate correctly fails with 1448 unclassified findings. Runtime HBI
conformance, HBP migration lineage, atomic legacy migration, released
cross-repository compatibility and macOS/Windows execution are unavailable and
are recorded as `null`, not success.

## Goal

Terminar issues abertas do `simplicio-dev-cli`.

## Result

Implemented three bounded backlog slices in this worktree: the earlier #129 patch extraction/apply recovery, the #120/#121 evidence-gate watcher hardening slice, and the #119 deterministic multi-task intake/DAG/resume/status slice.

## Completed

- Added deterministic full-file artifact extraction when a model response does not include a valid unified diff but a single bound target exists.
- Added recovery from stale/corrupt unified diffs by rebuilding a diff from a full-file artifact against the current transactional candidate.
- Persisted the selected patch parser strategy in `.simplicio/last_patch_strategy.txt` for diagnostics.
- Added task JSON model metadata for requested/effective model, effort, tier and provider.
- Added regression tests for full-file artifact diff synthesis and stale patch recovery.
- Added watcher-side receipt revalidation in `simplicio.evidence_ledger.EvidenceLedger.matrix()`.
- Measured claims are now demoted back to `UNVERIFIED` when a stored artifact disappears or no longer matches its original SHA-256.
- Added focused regression tests for wrong-scenario artifact replacement and missing-artifact demotion.
- Updated `docs/evidence-ledger.md` with the watcher/revalidation contract.
- Added deterministic `task_batch` preview generation from multi-card `TaskSpec` input, including stable batch/source hashes and DAG validation.
- Added dependency resolution for multi-task intake using explicit task IDs or unique task labels, with fail-closed errors for ambiguous and unknown references.
- `simplicio-py intake --plan-only` and `--contract` now emit a `task_batch` preview alongside contracts/blocked plan data.
- `simplicio-py status --json` now reports `.simplicio/task_batch.json` as a first-class resumable state surface when no sprint state is present.
- Added focused regression tests for batch preview dependency inference/validation and standalone batch status reporting.

## Validation

- `pytest tests/python/test_mapping_retry_flow.py -q` passed.
- `pytest tests/python/test_evidence_ledger.py tests/python/test_delivery_corpus.py -q` passed.
- `pytest -q tests/python/test_multi_task.py tests/python/test_run_cli.py -k "task_batch or multi_task or status_json_reports_task_batch"` passed.
- Manual `simplicio.commands.intake.run(... plan_only=True, json=True)` checks passed for single-card and two-card dependency previews.
- `ruff check .` passed.
- `ruff format --check .` passed after formatting existing drift.
- `mypy simplicio` passed.
- Focused `ruff check` on the #119 touched files passed.
- `tests/python/test_task_spec.py` could not be re-run end-to-end because collection still fails on the pre-existing `ModuleNotFoundError: No module named 'simplicio.pipeline_stages'` import drift in `simplicio.pipeline`.
- Full `pytest -q` was run earlier in the worktree and exposed existing broader-suite failures unrelated to these bounded slices, including help snapshots, symlink/path behavior, impact gate assumptions, benchmark fixtures and live-gate fixture drift.
# Issue #262 result (2026-07-22)

Status: partial implementation, release blocked. The strict local scanner and
package gate are implemented with focused unit/integration/system regression
coverage and measured performance evidence. Runtime HBI conformance, HBP
lineage, atomic legacy migration, installed cross-repository version windows,
and the supported-OS matrix are not proven. See
`docs/evidence/issue-262-quality-gate.md` for commands, results, and blockers.

# Issue #256 result (2026-07-22)

Status: implemented. The integrated Dev CLI now creates a `RuntimeEffectSink`
from `SIMPLICIO_RUNTIME_URL` when no sink is injected, negotiates the Runtime
HTTP boundary, and does not execute the effect locally. Focused evidence from
the PR: 36 tests passed with 94.86% branch coverage; benchmark median 0.7126
ms, p95 1.0968 ms, and 1311.19 transactions/s. The private Runtime deployment
was not available in Cloud, so transport and fault-injection evidence cover the
boundary rather than a live Runtime deployment.

# Issue #258 result (2026-07-22)

Implemented a coordinator-owned, single-dispatch integrated execution boundary.
The production path preserves causal identity, prevents nested attempts and
batched effects, checks cancellation/lease/fencing immediately before effect
submission, and returns a typed observation without retry, replan, scheduler,
provider, subprocess, worktree, queue, or terminal-status ownership. PR evidence
records 17 focused tests, 96% touched branch coverage, and a 5,000-attempt
benchmark with one effect call per attempt.

## Issue #256 causal receipt hardening (2026-07-22)

Status: tested patch, cross-repository completion blocked. Runtime receipts now
must reproduce the complete submitted causal identity; forged coordinator,
session, turn, attempt, subworkflow, plan, and goal values fail closed even
when the attacker recomputes a valid receipt digest. Focused tests, branch
coverage, clean-wheel system probing, and performance evidence are recorded in
`docs/evidence/issue-256-runtime-effect-sink.md`. A live public Runtime and
Agent/non-Agent coordinator receipts were unavailable in Codex Cloud, so the
issue remains open and no end-to-end Runtime mutation claim is made.

## Issue #256 durable ambiguous outcomes (2026-07-23)

Status: local boundary hardened; cross-repository completion remains blocked.
Receipt validation failures after admission now persist a redacted
`effect_unknown` outcome and never persist untrusted receipt content.
Capability transport failures before admission persist `not_started`, which
the atomic executor exposes as retryable failure instead of effect submission.
The focused suite passed 63 tests at 93.01% branch coverage, and the
500-transaction benchmark measured median 0.2176 ms and p95 0.3307 ms. A live
Runtime trace, Agent/non-Agent parity, public transport parity, stale-source
pre-mutation proof remain unavailable. The exact patch wheel passed an isolated
`--target` install probe; its SHA-256 is
`53afe69f2c63f7ec6e803112fad4e057c5e87b3eabcd8a8cc92b5b6ba11db99d`.

## Issue #262 quality gate

## Issue #262 CI follow-up (2026-07-22)

Status: tested patch ready; full issue remains blocked. Strict source and release
archive scans now form a blocking Linux/macOS/Windows CI job. The artifact
directory interface fails closed when builds are absent and rejects internal
JSON in any wheel or sdist. Focused validation passed 16 tests at 89% scanner
branch coverage; a real wheel/sdist build produced zero findings. Runtime HBI
conformance, HBP lineage, atomic legacy migration, and released cross-repository
compatibility remain unproven external dependencies, so issue #262 must stay
open.

## Goal

Terminar issues abertas do `simplicio-dev-cli`.

## Result

Implemented three bounded backlog slices in this worktree: the earlier #129 patch extraction/apply recovery, the #120/#121 evidence-gate watcher hardening slice, and the #119 deterministic multi-task intake/DAG/resume/status slice.

## Completed

- Added deterministic full-file artifact extraction when a model response does not include a valid unified diff but a single bound target exists.
- Added recovery from stale/corrupt unified diffs by rebuilding a diff from a full-file artifact against the current transactional candidate.
- Persisted the selected patch parser strategy in `.simplicio/last_patch_strategy.txt` for diagnostics.
- Added task JSON model metadata for requested/effective model, effort, tier and provider.
- Added regression tests for full-file artifact diff synthesis and stale patch recovery.
- Added watcher-side receipt revalidation in `simplicio.evidence_ledger.EvidenceLedger.matrix()`.
- Measured claims are now demoted back to `UNVERIFIED` when a stored artifact disappears or no longer matches its original SHA-256.
- Added focused regression tests for wrong-scenario artifact replacement and missing-artifact demotion.
- Updated `docs/evidence-ledger.md` with the watcher/revalidation contract.
- Added deterministic `task_batch` preview generation from multi-card `TaskSpec` input, including stable batch/source hashes and DAG validation.
- Added dependency resolution for multi-task intake using explicit task IDs or unique task labels, with fail-closed errors for ambiguous and unknown references.
- `simplicio-py intake --plan-only` and `--contract` now emit a `task_batch` preview alongside contracts/blocked plan data.
- `simplicio-py status --json` now reports `.simplicio/task_batch.json` as a first-class resumable state surface when no sprint state is present.
- Added focused regression tests for batch preview dependency inference/validation and standalone batch status reporting.

## Validation

- `pytest tests/python/test_mapping_retry_flow.py -q` passed.
- `pytest tests/python/test_evidence_ledger.py tests/python/test_delivery_corpus.py -q` passed.
- `pytest -q tests/python/test_multi_task.py tests/python/test_run_cli.py -k "task_batch or multi_task or status_json_reports_task_batch"` passed.
- Manual `simplicio.commands.intake.run(... plan_only=True, json=True)` checks passed for single-card and two-card dependency previews.
- `ruff check .` passed.
- `ruff format --check .` passed after formatting existing drift.
- `mypy simplicio` passed.
- Focused `ruff check` on the #119 touched files passed.
- `tests/python/test_task_spec.py` could not be re-run end-to-end because collection still fails on the pre-existing `ModuleNotFoundError: No module named 'simplicio.pipeline_stages'` import drift in `simplicio.pipeline`.
- Full `pytest -q` was run earlier in the worktree and exposed existing broader-suite failures unrelated to these bounded slices, including help snapshots, symlink/path behavior, impact gate assumptions, benchmark fixtures and live-gate fixture drift.
# Issue #262 result (2026-07-22)

Status: partial implementation, release blocked. The strict local scanner and
package gate are implemented with focused unit/integration/system regression
coverage and measured performance evidence. Runtime HBI conformance, HBP
lineage, atomic legacy migration, installed cross-repository version windows,
and the supported-OS matrix are not proven. See
`docs/evidence/issue-262-quality-gate.md` for commands, results, and blockers.

# Issue #256 result (2026-07-22)

Status: implemented. The integrated Dev CLI now creates a `RuntimeEffectSink`
from `SIMPLICIO_RUNTIME_URL` when no sink is injected, negotiates the Runtime
HTTP boundary, and does not execute the effect locally. Focused evidence from
the PR: 36 tests passed with 94.86% branch coverage; benchmark median 0.7126
ms, p95 1.0968 ms, and 1311.19 transactions/s. The private Runtime deployment
was not available in Cloud, so transport and fault-injection evidence cover the
boundary rather than a live Runtime deployment.

# Issue #258 result (2026-07-22)

Implemented a coordinator-owned, single-dispatch integrated execution boundary.
The production path preserves causal identity, prevents nested attempts and
batched effects, checks cancellation/lease/fencing immediately before effect
submission, and returns a typed observation without retry, replan, scheduler,
provider, subprocess, worktree, queue, or terminal-status ownership. PR evidence
records 17 focused tests, 96% touched branch coverage, and a 5,000-attempt
benchmark with one effect call per attempt.

## Issue #257 integrated-mode validation

## Issue #257 follow-up (2026-07-22)

Corrected a contract mismatch that made the exposed integrated mode incompatible with real Mapper snapshots.
Both mode negotiation and effect dispatch now require Mapper adapter validation rather than trusting a schema
string. Focused validation is green and concrete evidence is recorded in `docs/evidence/issue-257.md`;
repository-wide pre-existing quality-gate failures remain explicit rather than being reported as success.

## Goal

Terminar issues abertas do `simplicio-dev-cli`.

## Result

Implemented three bounded backlog slices in this worktree: the earlier #129 patch extraction/apply recovery, the #120/#121 evidence-gate watcher hardening slice, and the #119 deterministic multi-task intake/DAG/resume/status slice.

## Completed

- Added deterministic full-file artifact extraction when a model response does not include a valid unified diff but a single bound target exists.
- Added recovery from stale/corrupt unified diffs by rebuilding a diff from a full-file artifact against the current transactional candidate.
- Persisted the selected patch parser strategy in `.simplicio/last_patch_strategy.txt` for diagnostics.
- Added task JSON model metadata for requested/effective model, effort, tier and provider.
- Added regression tests for full-file artifact diff synthesis and stale patch recovery.
- Added watcher-side receipt revalidation in `simplicio.evidence_ledger.EvidenceLedger.matrix()`.
- Measured claims are now demoted back to `UNVERIFIED` when a stored artifact disappears or no longer matches its original SHA-256.
- Added focused regression tests for wrong-scenario artifact replacement and missing-artifact demotion.
- Updated `docs/evidence-ledger.md` with the watcher/revalidation contract.
- Added deterministic `task_batch` preview generation from multi-card `TaskSpec` input, including stable batch/source hashes and DAG validation.
- Added dependency resolution for multi-task intake using explicit task IDs or unique task labels, with fail-closed errors for ambiguous and unknown references.
- `simplicio-py intake --plan-only` and `--contract` now emit a `task_batch` preview alongside contracts/blocked plan data.
- `simplicio-py status --json` now reports `.simplicio/task_batch.json` as a first-class resumable state surface when no sprint state is present.
- Added focused regression tests for batch preview dependency inference/validation and standalone batch status reporting.

## Validation

- `pytest tests/python/test_mapping_retry_flow.py -q` passed.
- `pytest tests/python/test_evidence_ledger.py tests/python/test_delivery_corpus.py -q` passed.
- `pytest -q tests/python/test_multi_task.py tests/python/test_run_cli.py -k "task_batch or multi_task or status_json_reports_task_batch"` passed.
- Manual `simplicio.commands.intake.run(... plan_only=True, json=True)` checks passed for single-card and two-card dependency previews.
- `ruff check .` passed.
- `ruff format --check .` passed after formatting existing drift.
- `mypy simplicio` passed.
- Focused `ruff check` on the #119 touched files passed.
- `tests/python/test_task_spec.py` could not be re-run end-to-end because collection still fails on the pre-existing `ModuleNotFoundError: No module named 'simplicio.pipeline_stages'` import drift in `simplicio.pipeline`.
- Full `pytest -q` was run earlier in the worktree and exposed existing broader-suite failures unrelated to these bounded slices, including help snapshots, symlink/path behavior, impact gate assumptions, benchmark fixtures and live-gate fixture drift.
# Issue #262 result (2026-07-22)

Status: partial implementation, release blocked. The strict local scanner and
package gate are implemented with focused unit/integration/system regression
coverage and measured performance evidence. Runtime HBI conformance, HBP
lineage, atomic legacy migration, installed cross-repository version windows,
and the supported-OS matrix are not proven. See
`docs/evidence/issue-262-quality-gate.md` for commands, results, and blockers.

# Issue #256 result (2026-07-22)

Status: implemented. The integrated Dev CLI now creates a `RuntimeEffectSink`
from `SIMPLICIO_RUNTIME_URL` when no sink is injected, negotiates the Runtime
HTTP boundary, and does not execute the effect locally. Focused evidence from
the PR: 36 tests passed with 94.86% branch coverage; benchmark median 0.7126
ms, p95 1.0968 ms, and 1311.19 transactions/s. The private Runtime deployment
was not available in Cloud, so transport and fault-injection evidence cover the
boundary rather than a live Runtime deployment.

# Issue #258 result (2026-07-22)

Implemented a coordinator-owned, single-dispatch integrated execution boundary.
The production path preserves causal identity, prevents nested attempts and
batched effects, checks cancellation/lease/fencing immediately before effect
submission, and returns a typed observation without retry, replan, scheduler,
provider, subprocess, worktree, queue, or terminal-status ownership. PR evidence
records 17 focused tests, 96% touched branch coverage, and a 5,000-attempt
benchmark with one effect call per attempt.
