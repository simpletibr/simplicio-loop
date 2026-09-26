# ADR 0008: Bound delivery work and separate integration from release

- **Status:** Accepted
- **Date:** 2026-08-01
- **Issue:** [#960](https://github.com/wesleysimplicio/simplicio-loop/issues/960)

## Context

Delivery can drift when a worker claims several issues, review findings silently expand scope,
review/fix cycles have no stopping rule, or merge and release are treated as one operation. Those
behaviours obscure ownership and make a green result difficult to reproduce.

## Decision

The canonical policy lives in
`.claude/skills/simplicio-loop/references/full-flow.md#bounded-delivery-policy` (linked from the
`SKILL.md` hot path); host files link to it rather than copying it. It establishes one implementation issue and one delivery PR per worker/session,
re-queries the canonical live source immediately before freezing, records the source revision and
provenance in the anchor, freezes that exact goal and ACs before mutation, and classifies findings
as `AC_BLOCKER`, `REGRESSION_BLOCKER`, or `FOLLOW_UP`.

One implementation review and one final independent verification are allowed, with at most two
AC-scoped repair rounds. Remaining blockers stop with evidence instead of extending the loop.
Only the active owner mutates the delivery branch; a reviewer needs an explicit handoff to edit.
Before the first mutation, the owner acquires and confirms the cross-session claim, lease, and
fence against the live source. A handoff updates that authority record and the receiver confirms
the replacement authority before continuing. The owner rebases once onto the canonical base
immediately before final verification and reruns affected gates. Merge, issue closure, packaging,
and release remain separate states, and release requires explicit scope or release-owner
authorization.

Repositories may impose stricter limits. A looser exception requires a recorded human decision.

An explicit human instruction to continue the same frozen issue and ACs after the default review budget stops is the recorded human decision for one new bounded continuation epoch. The continuation appends its authorization and prior attempt/review lineage, preserves the original anchor and counters, and sets a fresh finite cap (at most two AC-scoped repair rounds); it never resets history or creates an unbounded loop. A changed scope or AC requires a new human decision; a routine base refresh/rebase or explicitly authorized owner handoff requires re-query, re-anchoring, and re-validation under the existing decision. A changed delivery authority without that handoff requires a new decision. This exception does not relax resource admission, safety, authorization/authentication, integrity/signatures, lease/fence, evidence, required human approvals, host hard limits, or branch protection. Unknown model telemetry remains unknown; its absence is not a blanket blocker.

## Alternatives considered

1. Unbounded parallel WIP: increases throughput only superficially and obscures leases and finish
   state.
2. Fix every review suggestion in the current PR: converts review into uncontrolled scope growth.
3. Rebase continuously: creates repeated invalidation without improving the final integration gate.
4. Release automatically after merge: exceeds ordinary issue/PR authority and conflates evidence
   states.

## Consequences

- Delivery has a finite review and repair budget.
- Frozen ACs remain the completion contract; follow-ups are tracked separately.
- The anchor records which live source revision and provenance supplied the frozen ACs.
- Branch mutation has one accountable, live-authorized owner at a time; handoff rotates authority.
- Final ancestry and tests are checked against the actual integration base.
- A merged PR does not implicitly close its issue or authorize a release.

## Validation and rollout

Edit the canonical skill, regenerate plugin and package mirrors with the existing sync scripts,
and run their `--check` modes plus focused documentation/link tests. The next release containing
the merge publishes the policy; publication itself remains a separately authorized action.
