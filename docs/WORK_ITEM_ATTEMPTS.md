# Bounded WorkItem attempts

`simplicio_loop.work_item_claims.AttemptCoordinator` is the local bridge between the
state-machine runner and the Runtime queue lease:

1. `claim()` atomically obtains one fenced lease and builds an allow-listed context pack.
2. `record_event()` and `accept_receipt()` first call `assert_active()`, so a stale worker
   cannot append accepted tool/evidence output after expiry or reassignment.
3. `retry()` releases the current lease and claims a new fencing token/attempt.
4. `complete()` persists the queue completion only after the current lease is checked.

SQLite and the HTTP queue facade implement the same read-only `assert-active` operation. A
queue outage raises `QueueUnavailable`; callers must hand off rather than mutate. This is a
measured local contract, not proof that an external board or multi-device service is deployed.

```python
from simplicio_loop.remote_queue import SQLiteRemoteQueue
from simplicio_loop.work_item_claims import AttemptCoordinator

attempt = AttemptCoordinator(queue, run_id="run-1").claim(
    work_item_id="WI-1", identity=identity, goal="...", acs=["AC-1"],
    allowed_paths=["src/feature.py"],
)
coordinator.accept_receipt(attempt, {"status": "passed"})
coordinator.complete(attempt, receipt_ref="receipts/WI-1.json")
```

Focused proof lives in `tests/test_work_item_claims.py` and the HTTP assertion is covered by
`tests/test_remote_queue.py`.

## Planning receipt + mutation authority (#284)

`execute_operator()` already refuses to run without fresh mapper/plan/operator preflight
receipts, a passing `plan_contract.validate_plan()`, an unchanged repo state since planning, and
an operator target confined to the plan's `candidate_targets`. Issue #284 asked for those checks
to be tied together into one explicit, hash-bound artifact plus a derived **mutation authority**
token, so a caller can never invoke the mutation boundary while silently skipping part of the
intake — `simplicio_loop/planning_gate.py` (CLI: `scripts/planning_gate.py`) is that artifact:

```python
from simplicio_loop.plan_contract import validate_plan
from simplicio_loop.planning_gate import build_planning_receipt

plan_validation = validate_plan(plan, tasks, repo, contract_hash=contract["collection_hash"])
receipt = build_planning_receipt(
    run_id=run_id, attempt=attempt, contract=contract, plan=plan,
    plan_validation=plan_validation, lease_id=lease_id, fencing_token=fencing_token,
)
# receipt["mutation_authority"] is "" unless plan_validation["valid"] is True — a bad
# plan can never mint a mutation authority.
```

`evaluate_mutation_authority(run_dir, run_id=..., attempt=..., task_contract_hash=...,
plan_hash=..., lease_id=..., fencing_token=...)` re-derives the expected token from the
identity tuple **being executed right now** and fails closed
(`planning_receipt_missing`/`planning_receipt_schema_invalid`/`planning_not_ready`/
`mutation_authority_invalid`) on any mismatch — a stale plan hash (repo/plan drifted after
planning), a rotated lease/fencing token (lease lost/reassigned), or a missing/corrupt receipt
all invalidate the authority rather than being silently accepted.

`execute_operator()` and `execute_operator_batch()` require a valid mutation authority
**by default** — `simplicio_loop.planning_gate.mutation_authority_required()` returns `True`
unless the caller explicitly opts out via
`SIMPLICIO_REQUIRE_MUTATION_AUTHORITY=0|false|no|off|legacy`. A run with no
`planning-receipt.json` (or a stale/tampered one) now blocks fail-closed unconditionally, not
only when a flag happened to be set — no run can reach the mutation boundary while silently
skipping the intake gate.

GitHub source-revision capture is wired in for real via `simplicio_loop/source_snapshot.py`
(`capture_github_issue_snapshot()`): its `snapshot_hash`, when supplied, is folded into the
mutation-authority identity tuple, so an issue edited between planning and execution
invalidates the authority (`source_drift`) exactly like a stale plan hash does.

`simplicio_loop.planning_gate.publish_planning_receipt(receipt, publish_comment_fn=...)` wires
the receipt's verdict into the sibling #285 adapter (`github_lifecycle.publish_lifecycle_state()`):
a `ready_for_mutation=True` receipt is projected onto the SAME canonical status comment as
`PLANNED` (with the plan-validation errors as blockers when not ready — `BLOCKED` instead); a
receipt without a GitHub `source` block is a documented no-op (`None`), never a fake publish.
`scripts/planning_gate.py build --publish` drives this from the CLI.

**The receipt itself is now also mandatory-by-default.** `simplicio_loop/runner.py
::_maybe_auto_build_planning_receipt()`, wired into the real `arm_run()` dispatch path, self-builds
`planning-receipt.json` after every plan is materialized and validated —
`simplicio_loop.planning_gate.auto_planning_receipt_enabled()` returns `True` unless the caller
explicitly opts out via `SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT=0|false|no|off|legacy`, mirroring
`mutation_authority_required()`'s polarity exactly. Before this flip, the mutation-authority check
was mandatory but nothing forced the dispatch path to ever produce a receipt for it to check — a
caller unaware of the separate `scripts/planning_gate.py build` CLI could run `arm_run()` to
completion with no receipt and hit the gate as an opaque failure. Now both halves are on by
default: check `docs/adr/0004-planning-gate-rollout.md` for the rollout/migration strategy
(what breaks, the backward-compat shims, how to opt out temporarily).

Still not yet implemented: the full `simplicio.task-intake/v1` envelope (scope in/out,
dependencies, risks, rollback, impact map), the `impact-map.json` artifact, the AC↔step↔test↔
evidence matrix artifact, plan v2's DAG/parallelizable-step metadata, and a genuine
replanning/diff-on-drift flow (today source/repo drift blocks; it does not yet auto-replan).

Tests: `tests/test_planning_gate_unit.py` (token determinism, receipt building, fail-closed
re-verification, `mutation_authority_required()` default/opt-out matrix),
`tests/test_planning_gate_execute_operator_integration.py` (mandatory-by-default blocks without
a receipt, an explicit opt-out restores the old zero-gate behavior, a valid receipt allows
execution, a drifted plan/source blocks again), `tests/test_planning_gate_github_publish.py` (the
receipt-to-comment wiring, fake transport, no real `gh`/network call),
`tests/test_284_lifecycle_dag_idempotence.py` (auto-build mandatory-by-default vs. explicit
opt-out, plan v2 DAG validation, crash/resume/replan idempotence), and
`tests/test_planning_gate_live_e2e.py` (opt-in, `SIMPLICIO_LIVE_GH_E2E=1`: a REAL scratch GitHub
issue, a real source snapshot, a real CLAIMED→PLANNED canonical-comment update, and a trivial
guarded mutation through the real `execute_operator()` gate — no fake GitHub transport).


## Local-first single-task route

The `single-task-fast` command (#885) was removed: one path failed closed
waiting for an adapter, the other called an external provider, which the loop
must never do. A single bounded task is routed instead through the documented
fast-path (`.claude/skills/simplicio-loop/SKILL.md` § "Pick the fastest route
first"): `scripts/route_mode.py` selects `fast-path` for a one-task, one-file,
low-fan-in, non-sensitive change, then `simplicio-dev-cli edit --plan ...
--compile`/`--apply` performs the governed local edit and the task's own
verification command closes it out — no dedicated Loop command, no provider
call.
