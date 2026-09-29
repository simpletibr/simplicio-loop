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
`simplicio edit`. The mirrored Runtime decision (ADR 0011) was removed with the
Runtime integration in 3.46.0; see git history.

## Amendment 2026-09-26

Issue #1343 removed `simplicio-fast` from the stack. The standalone operators are
`simplicio-mapper` (survey) and `simplicio-dev-cli` (mutate); there is no optional
third operator.

## Amendment 2026-09-29

Issue #1379 (loop 3.46.0) removed the Runtime/MCP integration from this repository:
there is no `runtime-backed` route, no Runtime activation gate and no Runtime binary
discovery. Decision items 1 and 3 no longer apply; the standalone path in item 2 is the
only path, and `simplicio-loop` owns activation and convergence itself.
