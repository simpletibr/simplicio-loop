# ADR 0009: Loop complete inside Runtime; mapper / dev-cli work alone

- **Status:** Accepted
- **Date:** 2026-08-04
- **Mirrors:** `simplicio-runtime` ADR-2026-08-04 + ADR-2026-08-04b

## Context

Product law: the full loop (convergence, journals, activation, completion) lives
**inside Runtime**, and Runtime decides when to use it. Simultaneously, the
operators must remain usable without Runtime or the loop becomes a single
point of failure for ordinary survey/edit work.

## Decision

1. **Loop product path** is Runtime-owned. Prefer `runtime-backed`. Activation
   via `simplicio loop decide` (or Runtime spine). Hosts do not bypass Runtime
   when it is available.
2. **Operators are standalone-capable:**
   - `simplicio-mapper` — map / inspect / handoff without Runtime
   - `simplicio-dev-cli` — plan + deterministic edits without Runtime
3. When Runtime is missing: operators continue; report
   `UNVERIFIED|runtime_unavailable`; do not claim full runtime-backed loop
   completion.
4. This package remains the protocol + host-hook implementation under Runtime
   authority — not a peer control plane.

## Consequences

Host rules MUST #0 (Runtime owns loop) and MUST operator survey/mutate paths
remain valid without Runtime. See also ADR 0010 (execution metrics standard).

## Amendment 2026-08-05

The standalone operator rule is package-level and does not create four peer Runtime
hops. Runtime selects Mapper and Loop separately; Dev CLI is nested only as
`loop.dev_cli` after Loop activation. Direct file edits default to
`simplicio edit`. See the mirrored Runtime decision in
[ADR 0011](./0011-runtime-operator-routing.md).

## Amendment 2026-09-26

Issue #1343 removed `simplicio-fast` from the stack. The standalone operators are
`simplicio-mapper` (survey) and `simplicio-dev-cli` (mutate); there is no optional
third operator.
