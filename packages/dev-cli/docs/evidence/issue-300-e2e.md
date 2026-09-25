# Issue #300 — E2E evidence

## Local contract harness

The test `tests/contracts/test_issue_300_e2e.py` drives the public integrated
pipeline through the real local `OfflineRuntimeTransport`. The Loop and Mapper
legs are represented by their versioned public JSON contracts; no LLM request,
network endpoint, or recording sink is used for the successful path.

```text
PYTHONPATH=/tmp/simplicio-issue-300-stub:. \
  python -m pytest -q tests/contracts/test_issue_300_e2e.py
PASS: 14 passed, 1 skipped
```

The successful path asserts the following causal chain:

```text
Loop Goal + bounded ContextPack
  -> Dev CLI PlanDAG
  -> EffectPlan / AttemptContext
  -> EffectTransaction
  -> verified Runtime receipt
```

| Scenario | Evidence | Result |
| --- | --- | --- |
| Loop → Mapper projection → Dev CLI → receipt | public pipeline + `OfflineRuntimeTransport` | PASS |
| Context handle causal propagation | plan, effect, observation, transaction, receipt | PASS |
| Digest cache across processes | child Python process reads metadata-only cache | PASS |
| Explicit refresh | `context_refresh=True`, prior digest invalidation | PASS |
| Tamper/truncation/provenance/root/path | pre-effect typed rejection | PASS |
| Source drift and attempt mismatch | sink receives zero effects | PASS |
| Secrets, insufficient fidelity, token budget | fail-closed ContextPack intake | PASS |
| N−1 / older compatibility | digest-bound downgrade refusal | PASS |
| Lost response and recovery | durable receipt, explicit reconciliation, no duplicate apply | PASS |
| Validation failure and rollback | Runtime receipt `validation_failed`, restored worktree | PASS |
| Independently installed Loop/Mapper/Runtime | requires external release stack and endpoint | UNVERIFIED |

The local harness is intentionally not reported as proof of independent
cross-repository package interoperability.

## Public API change exercised by the E2E

The integrated `run_task` bridge now forwards the coordinator-owned causal
fields needed to issue and verify one Runtime authorization: coordinator kind,
session, turn, attempt number, subworkflow, deadline, policy revision, and base
hash. This keeps authorization binding in the coordinator while allowing the
Dev CLI to preserve it through the EffectTransaction.

## External gate

The installed-stack test remains skipped with an explicit `UNVERIFIED` reason
until all of the following are available in one environment:

- independently installed `simplicio-loop`, `simplicio-mapper`, and
  `simplicio-dev-cli` entrypoints;
- a compatible `simplicio-runtime` endpoint exposing EffectTransaction/v1;
- a real Loop invocation that emits the ContextPack provenance, sends the
  bounded LLM projection, invokes Dev CLI, and reconciles the receipt.

No issue closure or release claim should use the local harness as a substitute
for that external gate.
