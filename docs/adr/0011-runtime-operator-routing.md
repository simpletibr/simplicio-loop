# ADR 0011: Runtime operator routing and deterministic editing

- **Status:** Superseded/Rejected (2026-09-26, issue #1305)
- **Date:** 2026-08-05
- **Mirrors:** `simplicio-runtime/docs/ADR-2026-08-05-RUNTIME-OPERATOR-ROUTING.md`

**Why rejected:** this ADR assumed a `simplicio-runtime` binary/MCP backend that owns
peer route decisions (Mapper/Fast/Loop) and a Runtime-selected deterministic `simplicio
edit`. That backend was decided out of this monorepo — `AGENTS.md` states there is no
Runtime/MCP backend in this stack, Loop activates directly (`/simplicio-loop`), and Dev
CLI is a required standalone operator, not a route nested only under Loop. This ADR is
kept for history; do not implement the routing it describes.

## Context

The Loop package must work both as an integrated Runtime-governed flow and as a
standalone package. Runtime also needs a clear boundary so an ordinary edit does
not appear to require Loop or a cross-component contract.

## Decision

1. Runtime exposes three peer route decisions only: Mapper, Fast, and Loop.
2. Mapper is selected for project-scoped context, including project edits that need
   repository awareness.
3. Fast is selected only from a fresh compatible Mapper artifact/handoff or for an
   explicit client-output-to-artifact transformation.
4. Loop is selected only for multi-step, iterative, parallel, retryable, review, or
   convergent work.
5. Dev CLI is not a peer Runtime route. It is nested as `loop.dev_cli` only after
   Loop activation and only when implementation, validation, tests, or diagnostics
   are needed.
6. Direct file mutations default to Runtime's deterministic `simplicio edit`.
   Dev CLI inside Loop may prepare or validate the operation and delegate the write.
7. Mapper, Fast, Dev CLI, and Loop remain independently callable without Runtime,
   a flow, or a cross-component contract. Missing optional context is reported
   degraded or `UNVERIFIED`, never fabricated.

## Route shape

```text
Runtime
├── mapper
├── fast
└── loop
    └── dev_cli (only after Loop activation)
```

## Consequences

The Runtime boundary is explicit while package-level standalone use remains
available. Fast usage is artifact-provenanced, direct edits are deterministic,
and Dev CLI cannot be accidentally selected outside the Loop boundary.
