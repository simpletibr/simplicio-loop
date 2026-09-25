# Issue #300 — digest-bound context evidence

## Locally closed slice

The integrated Dev CLI now derives one `sha256:<digest>` handle from canonical
Mapper `ContextSnapshot` bytes and one `ContextPack` projection. The binding
includes:

- `snapshot_id`, `revision`, canonical snapshot `source_digest`;
- Mapper `pack_hash` and a canonical full-projection digest;
- Mapper producer version and the snapshot root identity.

The handle is propagated through `PlanDAG`, `EffectPlan`, coordinator
`AttemptContext`, Runtime `EffectTransaction.causal`, atomic observation, and
the verified Runtime receipt. The integrated path blocks before the effect
sink on a missing pack, provenance mismatch, stale revision, root mismatch,
pack/attempt digest mismatch, insufficient fidelity, token-budget overflow,
sensitive field, unsafe path, missing source, or changed source bytes.

Diagnostics return hashes and versions in `context_binding`; snapshot and pack
content are not echoed. The integrated path now also records a digest-scoped
`simplicio.context-binding-cache/v1` receipt. The cache is cross-process,
stores identity metadata only, and keys/checks the complete handle identity
so roots, revisions, Mapper versions, and projections cannot be mixed.
`context_refresh=True` invalidates previous entries for the same snapshot id
before recording the new revision, and the invalidation count is included in
the receipt.

## Reproducible validation

```text
Focused contract/runtime suite: 106 passed
Plan compiler/compatibility suite: 122 passed
Branch-aware touched-module coverage: 92% total
  mapper_context.py: 87%
  pipeline_integrated.py: 92%
  compile_task_spec.py: 100%
  models.py: 96%
  runtime_effect_sink.py: 93%
Wheel build: passed (`simplicio_cli-0.16.2-py3-none-any.whl`)
Repository suite: 1,920 passed, 20 skipped, 41 failed (pre-existing baseline)
```

The focused matrix covers deterministic binding, projection tampering, wrong
snapshot/revision/root provenance, invalid pack hash, secrets, exceeded
budget, insufficient fidelity, unsafe paths, source drift, handle mismatch,
N-1 mixed-version refusal, transaction propagation, and receipt correlation.

The repository-wide failures are outside this slice and match the known
checkout/environment baseline: stale CLI/dependency snapshots, absent
`.github` workflow files, SOCKS/test tooling and console entrypoints, networked
TypeScript codegen, provider-contract drift, and unrelated quality-gate debt.
Repository-wide `ruff check .` likewise reports 34 pre-existing findings, and
`mypy simplicio` reports five pre-existing errors in four modules. All 14
changed Python/test files pass targeted Ruff format and lint; targeted mypy
passes for the new binding/intake path.

## Honest cross-repository blockers

This repository cannot close the full Loop → Mapper → LLM → Runtime E2E alone.
As installed for this change, `simplicio-mapper 0.24.1` does not emit the
additive `ContextPack.source_snapshot` provenance consumed by the fail-closed
boundary. Its current pack root hash is also derived from the absolute root,
while canonical ContextSnapshot root identity is derived from repository,
revision, and source set. No adapter in Dev CLI fabricates that provenance.

The following issue steps therefore remain external or follow-up work:

- Mapper emission and conformance validation of snapshot provenance,
  selectors, truncation, redaction metadata, and token budget;
- Loop use of the derived handle in its Goal and LLM request;
- real Loop invocation of the public refresh option after structural change;
- secret scanning/redaction of snippet *values* (this slice rejects sensitive
  keys but does not mutate Mapper-owned projection bytes);
- real Runtime/Loop installed-package, mixed-version, recovery, and rollback
  E2E evidence.

The Dev CLI-side cache/refresh contract is now covered by unit tests that use
two cache instances to model separate processes, verify exact-digest hits,
reject changed projections, and prove revision refresh invalidation. The
integrated pipeline test also records the cache receipt alongside the
Loop-facing context handle and Runtime-facing observation.

Until Mapper emits the provenance, integrated execution fails closed with
`INCOMPATIBLE_CONTEXT`; standalone behavior is unchanged.

## E2E harness — 2026-07-23

`tests/contracts/test_issue_300_e2e.py` now exercises the public integrated
`run_task` path with the real local `OfflineRuntimeTransport`: Loop-shaped Goal
and bounded ContextPack input, canonical Mapper binding, PlanDAG/EffectPlan,
EffectTransaction, verified receipt, cache subprocess visibility, tamper/drift
rejection, N−1 refusal, recovery, and rollback. Result: **14 passed, 1
skipped** in the focused E2E file. Full details and the exact command are in
[`docs/evidence/issue-300-e2e.md`](issue-300-e2e.md).

The run also closed a Dev CLI API gap: coordinator-owned session/turn/policy/
base fields are now forwarded into the Runtime dispatch context so a real
Loop-issued authorization can be verified end to end. This local transport
evidence is still a harness, not installed cross-repository proof.

## Latest Mapper main compatibility slice — 2026-07-23

Mapper `origin/main` was rechecked at `461d0245fc924aaca4ea868ef1053f1df1dec330`.
Its published `simplicio.context-snapshot/v1` kit remains compatible, and its
`simplicio.execution-context/v1` envelope carries `repository.snapshot_id`,
`repository.root_hash`, and `repository.context_pack_hash`. Dev CLI now accepts
that envelope through `--execution-context`, environment, or project config;
the installed Mapper validator is called and all three identities are checked
against the supplied snapshot and pack. The older `source_snapshot` path is
unchanged.

This is a compatibility slice, not closure evidence: the current Mapper
`context-pack/v1` payload still does not embed `source_snapshot`, and no
installed Loop → LLM → Dev CLI → Runtime receipt, cache/refresh, mixed-version,
or rollback E2E was available. The issue therefore remains open.
