<!-- simplicio-contract:begin -->
contract: loop-execution/v1
schema: simplicio.contract-doc/v1
purpose: A versioned, testable export of the converge/drain execution discipline `simplicio-loop` actually runs — so `simplicio-runtime` (or any other consumer) can **reuse this semantics instead of inventing a second, incompatible execution contract** (issue #115).
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.loop-execution/v1`

A versioned, testable export of the converge/drain execution discipline `simplicio-loop` actually
runs — so `simplicio-runtime` (or any other consumer) can **reuse this semantics instead of
inventing a second, incompatible execution contract** (issue #115).

This is not a re-description in prose. Every fixture under [`fixtures/`](fixtures/) either:

- **executes the real producer** (`hooks/loop_stop.py` as a subprocess in an isolated temp
  directory, or `scripts/loop_journal.py`'s pure `analyze()`/`fingerprint()` functions imported
  directly) and asserts on its real output, or
- for the one mode this repo does not yet implement in code (`drain`'s scheduler tick — see
  below), defines the **target reference shape** derived from the documented rule, clearly labeled
  as such.

Run `python3 scripts/check_loop_contract.py` to validate every fixture. It exits non-zero with a
specific failure message on any drift between a fixture and the real behavior it claims to capture.

## Stability

`v1` is additive-only once published: existing fixture files, `schema.json` required fields, and
`expected.json` keys will not change meaning or be removed in `v1`. A breaking change ships as
`v2` in a sibling directory. This contract does **not** change the public behavior of
`/simplicio-loop` (issue #115 explicitly scopes that out) — it only documents and tests the
behavior that already exists.

## The two modes

`simplicio-loop`'s scratchpad frontmatter carries a `mode: converge | drain` field
(`.claude/skills/simplicio-loop/SKILL.md` § "State file"). The two modes have opposite jobs and
opposite termination logic (`SKILL.md` § "Three loop modes" — `fast-path` is a third, reduced-rigor
dynamic layered on top of `converge`, tracked in the anchor's `route_mode` field, not in this
`mode` frontmatter field):

| | `converge` (single hard task) | `drain` (a queue of items) |
|---|---|---|
| Wants | depth — keep changing strategy until ONE thing passes | breadth — clear many independent items, idempotently |
| Each turn | triage since last turn → one AC-scoped change → verify → watcher-gate → journal | claim next open item → implement → deliver → re-query source |
| **Termination** | the evidence-gated `<promise>` fires, OR the stall detector says STALLED and escalates | the source re-query returns empty for **K consecutive rounds** (`dry>=2`) AND the working set is idle |
| Anti-pattern it avoids | oscillation (retrying the same dead-end) | missing late-arriving work (stopping too early) |

Both obey three universal exits regardless of mode: the evidence-gated promise, the
`max_iterations` cap, and an explicit `.simplicio-loop/orchestrator/STOP` signal (which always wins, checked
before anything else).

**Implementation status in THIS repo:** `converge` is fully implemented and is what the fixtures
below exercise directly (`hooks/loop_stop.py`, `scripts/loop_journal.py`). `drain`'s termination
RULE is documented (`SKILL.md`, `references/standing-loop-247.md` § 3 — the "dry counter"), but its
scheduler tick is host-provided (cron / a durable scheduler) and no script in this repo persists a
`drain_queue_state` shape today. The `drain-empty-after-k-rounds` fixture below is therefore this
contract's **reference definition** of that shape — the thing a runtime implementation should
produce and be checked against — not an extraction from existing code. This is called out
explicitly in that fixture's `expected.json` so nobody mistakes it for more than it is.

## State objects

Full field-level shape: [`schema.json`](schema.json). Summary:

| Object | Path | Producer | Role |
|---|---|---|---|
| Scratchpad frontmatter | `.simplicio-loop/orchestrator/loop/scratchpad.md` | the skill, on arm; iteration bumped by `loop_stop.py` | the frozen goal + cap + promise + mode |
| Journal record | `.simplicio-loop/orchestrator/loop/journal.jsonl` | `scripts/loop_journal.py record` (append-only) | attempt memory — anti-oscillation |
| Anchor | `.simplicio-loop/orchestrator/loop/anchor.json` | `scripts/task_anchor.py set/mark` | frozen acceptance criteria — anti-drift |
| Watcher challenge | `.simplicio-loop/orchestrator/loop/watcher_challenge.json` | `loop_stop.py` at end of a re-feed turn | the per-iteration nonce a watcher receipt must echo |
| Watcher state | `.simplicio-loop/orchestrator/loop/watcher_state.json` | `scripts/watcher_verify.py verify` | independent re-verification of the anchor's done/pending state |
| Done flag | `.simplicio-loop/orchestrator/loop/done.flag` (legacy `done`) | `hooks/loop_capture.py` (Cursor-style runtimes) | cross-runtime completion signal |
| STOP signal | `.simplicio-loop/orchestrator/STOP` | human / channel | hard halt, always checked first |
| Handoff | `.simplicio-loop/orchestrator/loop/HANDOFF.md` | `loop_stop.py:write_handoff` | cross-agent continuation artifact on an INCOMPLETE stop |
| Drain queue state | *(runtime-defined path)* | *(reference only — see above)* | dry-round counting for the drain termination rule |

## Evidence-gated completion, precisely

A `<promise>...</promise>` in the turn's own text is honored **only when all four** hold at once
(`hooks/loop_stop.py:main`, the promise branch):

1. The promise text matches the scratchpad's `completion_promise` EXACTLY.
2. The turn's own text carries an evidence marker (`EVIDENCE_RE`: a PR URL, a `pass|passed|
   passing|green|ok` token, a `file:line` reference, or a ✓/✅ mark) — unless
   `evidence_required: false` was explicitly set.
3. The **watcher** independently re-verified (`watcher_verify()` — challenge-bound, so a
   receipt cannot be a stale or hand-written self-attestation; see `watcher_state` above).
4. **No acceptance criterion in the task anchor is still open** (`anchor_pending()`).

Any one of these failing means the promise is silently ignored and the loop re-feeds — this is the
exact mechanism that stops "the agent just said it's done" from ending a task. See
`fixtures/evidence-gated-done/` for a same-goal, same-anchor, same-watcher-state contrast where
changing ONLY the evidence marker flips the outcome from re-feed to stop.

## Fixtures

| Fixture | What it proves | Harness |
|---|---|---|
| [`converge-success`](fixtures/converge-success/) | All four completion conditions hold → the loop stops cleanly, no re-feed, no handoff | `hooks/loop_stop.py` subprocess |
| [`converge-stall-escalation`](fixtures/converge-stall-escalation/) | K+1 consecutive same-fingerprint failures → STALLED, recommend `escalate`, dead-end action named | `scripts/loop_journal.py:analyze()` (pure) |
| [`drain-empty-after-k-rounds`](fixtures/drain-empty-after-k-rounds/) | 2 consecutive dry rounds after real prior work → DRAINED (idle, not a hard stop) | reference algorithm (see status note above) |
| [`stop-path`](fixtures/stop-path/) | `.simplicio-loop/orchestrator/STOP` wins mid-task, even with an open acceptance criterion → clean halt + handoff | `hooks/loop_stop.py` subprocess |
| [`evidence-gated-done/satisfied`](fixtures/evidence-gated-done/satisfied/) | promise + evidence + watcher + anchor all clear → done | `hooks/loop_stop.py` subprocess |
| [`evidence-gated-done/withheld`](fixtures/evidence-gated-done/withheld/) | same state, only the evidence marker is missing → re-feeds instead of stopping | `hooks/loop_stop.py` subprocess |
| [`journal-append-only-minimal`](fixtures/journal-append-only-minimal/) | the minimal legal record shape + fingerprint stability across a recurring bug (why append, never rewrite) | `scripts/loop_journal.py:fingerprint()` (pure) |

Each fixture directory contains the raw input files (an `.simplicio-loop/orchestrator/` tree to copy into a temp
cwd, or a bare JSON/text file for the pure-function fixtures) plus an `expected.json` describing
what `scripts/check_loop_contract.py` asserts and why.

## How `simplicio-runtime` (or any consumer) should reuse this

1. **Read, don't guess:** `schema.json` is the field-level contract; this file is the narrative.
   Both are versioned together under `v1`.
2. **Reproduce, don't trust prose:** for `converge`, drive your own executor with the SAME input
   files (`scratchpad.md`, `anchor.json`, `watcher_challenge.json`, `watcher_state.json`,
   `journal.jsonl`, and the turn's response text) and diff your output against each fixture's
   `expected.json`. If your executor and this reference disagree, one of you has a bug — that's the
   point of a shared, testable contract instead of two independent readings of the same prose.
3. **For `drain`:** there is no reference *code* to diff against yet (see the status note above) —
   implement the rule (`schema.json`'s `drain_queue_state` shape + the round/streak invariants) and
   validate against `fixtures/drain-empty-after-k-rounds/expected.json`. If `simplicio-runtime`
   lands a real drain executor, the honest next step is to promote that fixture from "reference
   only" to "executes the real producer" the same way the converge fixtures do today (a `v1`
   addition, not a `v2` break).
4. **Journal payloads:** `journal-append-only-minimal` plus `converge-stall-escalation` together
   give enough real record shapes (minimal core fields, a full record with lineage fields in
   `fixtures/converge-success/.simplicio-loop/orchestrator/loop/journal.jsonl`, and a 4-record stall/escalate
   sequence) for a runtime to build its own journal-shape tests without re-deriving the format from
   `scripts/loop_journal.py`'s docstring.
5. **Never invent a second promise/evidence/anchor/watcher gate.** Reuse the four-condition rule
   above verbatim; it is what `fixtures/evidence-gated-done/` exists to pin down byte-for-byte.

## Published Runtime handoff receipt

When a real run reaches `done`, `simplicio_loop.runner.verify_run` publishes the envelope described
by [`receipt.schema.json`](receipt.schema.json) at `.simplicio-loop/loop-execution.json`. The envelope is
written only after the watcher, delivery, quality-matrix, and completion-oracle gates pass.

The envelope points to a run-owned `runtime-loop-execution/` bundle containing copies of the five
state artifacts plus the final Mapper and Dev CLI receipts. Each copied artifact carries a SHA-256
digest and a bundle-relative path only; source paths are intentionally omitted so the receipt is
portable and cannot direct the consumer outside the run. The bundle is complete before the root
envelope is atomically replaced, so `simplicio-runtime` can validate one coherent snapshot without
following parent-directory paths or reading files that are still changing.

The stable Runtime chain is `simplicio-loop → simplicio-mapper → simplicio-dev-cli → simplicio-runtime`.

All public execution flows (`run`, `tick`, `batch`, `wave`, and `prism`) use
this same publisher boundary. A flow may report `BLOCKED`, `PARTIAL`, or `ERROR` as an additive
diagnostic projection, but it cannot report a verified v1 receipt unless the durable Mapper,
frozen stack, Dev CLI, watcher/evidence, delivery, quality, and completion-oracle artifacts
are present and valid. A completed dispatch result without that v1 publication is blocked.

## Out of scope (see issue #115)

- Migrating the loop to Rust.
- Changing the Runtime consumer's implementation — the Loop publishes the v1 handoff, while
  `simplicio-runtime` remains responsible for its independent read-only validation.
- A `drain` executor implementation — only its target shape/rule is published here (see status
  note above).

## Universal execution successor

The v1 receipt remains the verified-success projection described above. The
transport-neutral envelope for `run`, `tick`, `batch`, `wave`,
and `prism` is the explicit successor
[`simplicio.loop-execution/v2`](../v2/SCHEMA.md). v2 preserves v1 receipts as a
verified-success subset and adds fail-closed partial, blocked, error, and expected
governor-blocked observations without changing v1 field meaning.
