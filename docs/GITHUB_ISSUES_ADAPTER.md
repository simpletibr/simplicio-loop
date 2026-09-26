# GitHub issue lifecycle — the #285 `SourceAdapter` (GitHub binding)

Issue #285 asks for a full, typed `SourceAdapter` for GitHub — `list_ready` / `get_details` /
`claim` / `update_status` / `attach_evidence` / `close` / `requery` / `reconcile`, an outbox,
lease/fencing-gated ownership, duplicate-comment recovery, a real concurrency proof, and a
COMPLETE-gate integration. This document describes what is now **implemented and tested**, and
calls out what remains, honestly, at the bottom.

## Modules

| Module | Role |
|---|---|
| `scripts/pr_evidence.py::publish_comment`/`find_existing_comment` | #295's fail-closed, idempotent, marker-based create-or-update primitive for one GitHub comment. Everything below builds on this rather than duplicating it. |
| `simplicio_loop/github_lifecycle.py` | The state machine, renderer, publish/close/read-side verbs, outbox, and lifecycle-receipt persistence. |
| `simplicio_loop/source_adapter.py` | The unified `SourceAdapter` `Protocol` + `GitHubSourceAdapter`, the formal contract a future non-GitHub source would implement. |
| `simplicio_loop/oracle.py` | `evaluate_completion`'s `source_lifecycle` gate — blocks COMPLETE while `CLOSE_PENDING_RECONCILIATION` is open. |
| `scripts/github_lifecycle.py` | CLI shell over all of the above. |

## 1. The lifecycle state machine

`LIFECYCLE_STATES`: `DISCOVERED → CLAIMED → PLANNED → IN_PROGRESS → VERIFYING → PR_OPEN →
MERGE_READY → MERGED → CLOSING → CLOSED → RELEASED`, plus the side states `BLOCKED` /
`PAUSED_NETWORK` / `AWAITING_DECISION` / `CLOSE_PENDING_RECONCILIATION`.
`validate_transition(from, to, reason_code=...)` rejects any hop that is not a valid forward
transition unless an authorized regression `reason_code` is given (`SOURCE_CHANGED`,
`CHECKS_REGRESSED`, `REVIEW_REOPENED`, `LEASE_REASSIGNED`, `DELIVERY_REGRESSED`). A duplicate
event (same state twice) is always a no-op.

## 2. The renderer and publish/re-query confirmation

`render_lifecycle_comment(...)` renders the ONE canonical status comment (identity/lease/fence/
branch header table, Objetivo e escopo, Critérios de aceite checklist, Plano passo a passo,
Progresso e blockers, Testes e evidências, Entrega), tagged with its own hidden marker
(`<!-- simplicio-loop:lifecycle-status:v1 -->`, distinct from #295's evidence-comment marker), and
redacts anything that looks like a token/secret before it ever reaches a public comment.

`publish_lifecycle_state(...)` publishes via the #295 primitive, then immediately re-fetches the
same comment and compares the observed body hash against the expected one, producing a
`simplicio.github-lifecycle-receipt/v1` receipt with `verified: bool`. Two extra hooks:

* `require_active`, when given (typically `AttemptCoordinator.assert_active`, #183), is called
  immediately before the remote write — a lost/stale lease raises there and the write never
  happens.
* `outbox_dir`, when given, persists a pending-operation record (`record_pending_operation`)
  *before* the remote call and clears it (`mark_operation_done`) only after the write is
  confirmed — see § 5.

## 3. The read-side verbs

* `list_ready(owner, repo, *, state, labels, assignee, milestone)` — metadata-only, paginated,
  excludes pull requests.
* `get_details(owner, repo, issue)` — full paginated issue + all comments; separates the
  adapter's own canonical comment from human comments and computes a deterministic
  `source_revision` hash over everything else (a self-drift guard: the adapter's own progress
  writes never count as a material human edit).
* `requery(owner, repo, issue, *, comment_id=None)` — re-reads the source of truth immediately
  before/after a mutation; with `comment_id`, also fetches that exact comment's current body hash.

## 4. `close`: real `gh issue close`, fail-closed

`close_source_issue(...)`: (1) `require_active()` if given; (1.5) if a `planning_snapshot` was
supplied, `detect_close_source_drift` re-fetches the CURRENT issue via `get_details` and compares
it against the snapshot — any material human edit (title/body/state/labels/milestone/assignees) or
a new HUMAN comment posted since the snapshot blocks the close with `reason_code: "SOURCE_CHANGED"`,
fail-closed, WITHOUT ever calling `gh issue close`; (2) the real `gh issue close --reason <reason>`
call (structured argv, never shell interpolation) — any non-zero exit reports `SOURCE_CLOSE_FAILED`
and stops there, no comment update, no false "closed"; (3) an immediate re-query confirms
`state == "closed"` — if not, `SOURCE_CLOSE_UNCONFIRMED`; (4) only then does the canonical comment
move to `CLOSED`. If steps 1–3 succeed but the final comment write cannot be confirmed, the outcome
is `CLOSE_PENDING_RECONCILIATION` (the source **is** closed; the operation stays in the outbox for
`reconcile()`) — never a fake clean success.

`planning_snapshot` may be any `get_details()`-shaped mapping (e.g. captured at claim/plan time via
`capture_close_precheck_snapshot`) or an already-wrapped `simplicio.source-snapshot/v1` mapping.
The comparison reuses #284's exact primitive (`source_snapshot.detect_source_drift`) rather than
reinventing hash comparison, but is built on `get_details()`'s `source_revision` — which already
excludes the adapter's own canonical lifecycle comment — on BOTH sides, so the comment's own
rewrite on every lifecycle transition (CLAIMED → PLANNED → ... → CLOSING) never counts as drift.
`planning_snapshot` defaults to `None`, so existing callers are unaffected; the CLI's
`close --planning-snapshot <path-to-json>` wires it in.

## 5. The outbox + `reconcile`

`record_pending_operation`/`mark_operation_done`/`list_pending_operations` persist pending
mutations to disk (atomic temp-file-rename writes) before every remote write in
`publish_lifecycle_state`/`close_source_issue`, keyed by a deterministic `operation_id` (the
provider/repo/issue/run/attempt/fencing-token/revision/kind tuple). `reconcile(operation_id, ...)`
re-queries the source and, if the observed comment/issue state now matches what the pending
record expected, marks the operation `done` — recovering a crash between a confirmed remote write
and the local receipt **without ever posting a second comment**.

## 6. Lease/fencing-gated ownership

`publish_lifecycle_state`/`close_source_issue` both take `require_active`, wired in practice to
`AttemptCoordinator.assert_active` (`simplicio_loop/work_item_claims.py`, #183) rather than
reinventing lease/fencing — a lost/stale lease blocks the write, fail-closed, before any `gh`
call is made.

## 7. The unified `SourceAdapter` Protocol

`simplicio_loop/source_adapter.py` defines `SourceAdapter`, a `typing.Protocol`
(`@runtime_checkable`) capturing every verb above: `list_ready`, `get_details`, `requery`,
`claim`, `update_status`, `attach_evidence`, `close`, `reconcile`, `record_pending_operation`,
`mark_operation_done`, `list_pending_operations`. `GitHubSourceAdapter` is a thin, stateful
binding — bound to one `owner/repo` (+ optional outbox dir/runner/timeout) — that formally
satisfies it by delegating every call to the already-tested free functions in
`github_lifecycle.py`; no new behavior, just a single object a future GitLab/Jira/Azure-Boards
adapter can be written against instead of duck-typing the free functions.

```python
from simplicio_loop.source_adapter import GitHubSourceAdapter, SourceAdapter
from scripts.pr_evidence import publish_comment

adapter = GitHubSourceAdapter("acme", "widgets", publish_comment_fn=publish_comment,
                              outbox_dir=".simplicio-loop/orchestrator/github-outbox")
assert isinstance(adapter, SourceAdapter)  # runtime-checkable structural check

adapter.claim("12", run_id="run-1", attempt_id="12-1")
adapter.update_status("12", "PLANNED", run_id="run-1", attempt_id="12-1")
adapter.attach_evidence("12", "12/12 tests pass", state="VERIFYING", run_id="run-1", attempt_id="12-1")
adapter.close("12", run_id="run-1", attempt_id="12-1")
```

## 8. Runner wiring

`simplicio_loop/runner.py::_record_event` calls `_sync_github_lifecycle` on every phase event,
projecting mapped phases (`intake→DISCOVERED`, `worker_claimed→CLAIMED`, `planning/mapping→
PLANNED`, `executing→IN_PROGRESS`, `validating/watching/watcher_challenge→VERIFYING`,
`blocked→BLOCKED`, `awaiting_decision→AWAITING_DECISION`, `delivering→PR_OPEN`) onto the canonical
GitHub issue comment whenever a `source_issue` is set on the run state. This coordination-comment
flow is intentionally **GitHub-only**; it does not project comments to other issue trackers.
It is enabled by default, with `SIMPLICIO_LOOP_GITHUB_LIFECYCLE_SYNC=0` as the explicit
offline/legacy opt-out. Best-effort/fail-open (like the existing `progress-comment` command); any failure is logged to
`lifecycle-sync-errors.jsonl` under the run directory and swallowed. The fail-closed `close` path
is a separate, explicit call — never automatic from this per-event hook.

## 9. Oracle / COMPLETE-gate integration for `CLOSE_PENDING_RECONCILIATION`

Every successful lifecycle publish now persists its receipt into the run directory
(`github_lifecycle.persist_lifecycle_receipt`, file `github-lifecycle-receipt.json`) —
`runner.py::_sync_github_lifecycle` does this automatically, and
`scripts/github_lifecycle.py publish/close --run-dir <dir>` does it from the CLI.
`simplicio_loop.oracle.evaluate_completion` reads it via a new gate, `source_lifecycle`
(`_source_lifecycle_gate`): if the persisted receipt reports `outcome ==
"CLOSE_PENDING_RECONCILIATION"` (or `reason_code == "CLOSE_PENDING_RECONCILIATION"`), completion
is **blocked** (`ready: False`, `reason_code: "source_close_pending_reconciliation"`) until
`reconcile()` clears it. A run with no lifecycle receipt at all (no GitHub source, or sync never
enabled) is not penalized — the gate reports `source_lifecycle_not_configured` and passes,
additive rather than a new hard requirement for sourceless runs. See
`tests/test_oracle_source_lifecycle_gate.py`.

## 10. A real two-lease/two-device concurrency E2E

`tests/test_github_lifecycle_concurrency_e2e.py` spawns two independent OS **processes** (not
threads) that race to claim the SAME work item against a shared on-disk SQLite queue
(`simplicio_loop.remote_queue.SQLiteRemoteQueue`) and a shared on-disk fake-GitHub comment store.
Only one process ever wins the lease (real `BEGIN IMMEDIATE` transactional locking); the loser
gets a clean, typed `QueueConflict` rejection and NEVER calls
`GitHubSourceAdapter.claim`/`publish_lifecycle_state`, so it can never post or corrupt a comment.
The winner's write is confirmed end-to-end, and the shared comment store ends up with exactly one
canonical comment, authored by the winner only.

## Example

```python
from scripts.pr_evidence import publish_comment
from simplicio_loop.github_lifecycle import publish_lifecycle_state

receipt = publish_lifecycle_state(
    owner="acme", repo="widgets", issue="12", state="PLANNED",
    run_id="run-1", attempt_id="issue-12-1", fencing_token="7",
    publish_comment_fn=publish_comment,
    goal="Add SSO login", acceptance_criteria=[{"id": "AC-1", "text": "renders the button"}],
)
# receipt["comment_id"] is the SAME id across CLAIMED -> PLANNED -> ... -> CLOSED
# receipt["verified"] is True only if the re-queried body hash matches what was just sent
```

CLI:

```bash
python3 scripts/github_lifecycle.py publish --owner acme --repo widgets --issue 12 \
  --state PLANNED --run-id run-1 --attempt-id issue-12-1 --run-dir .simplicio-loop/orchestrator/run/run-1
python3 scripts/github_lifecycle.py list-ready --owner acme --repo widgets
python3 scripts/github_lifecycle.py get-details --owner acme --repo widgets --issue 12
python3 scripts/github_lifecycle.py close --owner acme --repo widgets --issue 12 \
  --run-id run-1 --attempt-id issue-12-1 --outbox-dir .simplicio-loop/orchestrator/github-outbox \
  --run-dir .simplicio-loop/orchestrator/run/run-1
python3 scripts/github_lifecycle.py reconcile --owner acme --repo widgets --issue 12 \
  --operation-id <op-id> --outbox-dir .simplicio-loop/orchestrator/github-outbox
```

## Tests

* `tests/test_github_lifecycle_unit.py` (18 tests) — state machine, renderer, publish/re-query,
  fake transport only.
* `tests/test_github_lifecycle_readside.py` / `tests/test_github_lifecycle_runner_wiring.py` (40
  tests) — `list_ready`/`get_details`/`requery`/`reconcile`, outbox, runner projection, fake
  transport plus one hand-run live E2E (issue #347, closed and cleaned up).
* `tests/test_source_adapter_protocol.py` — `GitHubSourceAdapter` satisfies `SourceAdapter` at
  runtime (`isinstance`), claim→update_status reuse the same comment id, `attach_evidence`
  embeds evidence text, `close` is fail-closed and re-query-confirmed, outbox round-trip.
* `tests/test_github_lifecycle_concurrency_e2e.py` — the real two-process concurrency proof
  (§ 10).
* `tests/test_github_lifecycle_live_e2e.py` — opt-in (`SIMPLICIO_LIVE_GH_E2E=1`, real `gh` auth
  required, skipped otherwise) full-cycle live proof: CLAIMED → IN_PROGRESS → VERIFYING (with
  evidence) → CLOSED against a real, disposable scratch issue, all on the SAME canonical comment
  id, ending in a real `close_source_issue` and a final independent re-query confirming
  `state == "closed"` and exactly one lifecycle comment.
* `tests/test_oracle_source_lifecycle_gate.py` — the COMPLETE-gate wiring (§ 9): passes with no
  receipt, blocks on `CLOSE_PENDING_RECONCILIATION`, passes again once reconciled.

## Evidence-comment delegation (`pr_evidence.py comment --publish`)

`scripts/pr_evidence.py::cmd_comment --publish` used to call `publish_comment(...)` directly with
its own `PR_EVIDENCE_COMMENT_MARKER`, opening/updating a SECOND, separate comment on the issue —
distinct from the ONE canonical `LIFECYCLE_COMMENT_MARKER` comment `claim`/`PLANNED` already
maintain. That was a direct gap against #285's "Um comentário canônico: claim, planejamento,
progresso, evidência e fechamento atualizam o mesmo comment ID."

`publish_evidence_via_lifecycle(...)` (in `scripts/pr_evidence.py`) closes it: it projects the
same rendered evidence body (PR link, verification coverage, item-by-item checklist, print/video
counts) as the `tests_and_evidence` field of `github_lifecycle.publish_lifecycle_state`, using
state `PR_OPEN` when `--pr` is given, else `VERIFYING` — the exact same comment id `PLANNED`
posted to, verified end to end in
`tests/test_pr_evidence_lifecycle_delegation.py::test_publish_evidence_reuses_the_same_comment_as_the_planning_receipt`.
`cmd_comment --publish` now delegates through this helper; `--run-id`/`--attempt-id`/`--state`
let a caller override the identity/state. `publish_comment`/`PR_EVIDENCE_COMMENT_MARKER` remain
the underlying idempotent primitive (still the injected `publish_comment_fn` everywhere in this
document) — only `cmd_comment`'s own marker choice changed.

## Explicitly NOT implemented here (tracked, not claimed done)

* A CI gate that isolates `≥90%` branch **coverage** as its own enforced number scoped just to
  `github_lifecycle.py`/`source_adapter.py` — `scripts/coverage_gate.py::CRITICAL_MODULES` tracks
  a fixed `scripts/*.py` list (#277) and does not (yet) include these `simplicio_loop/` modules.
  Measured out-of-band with `pytest --cov=simplicio_loop.github_lifecycle
  --cov=simplicio_loop.source_adapter --cov-branch`: 98% branch / 99% line coverage as of the
  #285 final audit — comfortably above the issue's `≥90%` bar, just not wired into an automated
  per-module gate.

Previously listed here and since closed: duplicate-comment **election** (`elect_canonical_comment`
+ `mark_comment_superseded` + `reconcile_duplicate_comments`, § above, tests in
`test_github_lifecycle_unit.py`) and the `docs/PHASE_EVENT_CONTRACT.md` write-up of the
`_sync_github_lifecycle` projection (its own "GitHub lifecycle projection (#285)" section) are
both implemented and documented — do not re-open them without checking current code first.
