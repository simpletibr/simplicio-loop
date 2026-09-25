# ADR-0001: Fast V3 ownership, engines and execution profiles

- Status: Proposed for implementation
- Date: 2026-07-26
- issue: #38 (pre-monorepo `simplicio-fast` repo, now `packages/fast/` of `simpletibr/simplicio-loop`)
- Parent: #37 (same pre-monorepo repo)

## Context

Simplicio Fast is the semantic CPU/cache engine for repository comprehension and guarded
change delivery. It must keep a project hot across orientation, impact analysis, planning,
editing, validation and retries. The source tree remains authoritative; Fast snapshots are
derived state.

Fast has one maintained implementation:

- **Python**: the reference implementation. It is the only engine; there is no probing,
  selection or fallback between implementations.

The ecosystem also contains Mapper, Dev CLI, Loop, Runtime, Agent, Code, Sprint, Prompt,
Canvas and distribution packages. Without an explicit ownership matrix, the same component
can accidentally become a second ContextGraph producer, scheduler, policy authority or
mechanical editor.

## Decision

### 1. Fast is the semantic data plane and delivery hot path

Fast owns:

- ingestion orchestration through the Mapper adapter;
- compiled binary/mmap semantic memory;
- immutable base generations and isolated worktree overlays;
- bounded query, context and impact selection;
- generation, source-hash and stale-state guards;
- an internal Understanding IR;
- coordination of the comprehension-to-change pipeline;
- cache reuse, invalidation, leases and refresh;
- provenance, capability and delivery receipts.

Fast does not own:

- cognition, provider choice or final engineering judgment;
- the public canonical ContextGraph;
- mechanical source mutation;
- task scheduling, retries, convergence or PR policy;
- effect authorization, sandbox policy or physical resource governance.

### 2. Canonical owners

| Contract or responsibility | Owner | Fast relationship |
| --- | --- | --- |
| simplicio.context-snapshot/v1 and ContextGraph | Mapper | Fast consumes handles and compiles a derived representation |
| simplicio.fast.snapshot/v* and Generation | Fast | Consumers receive handles; they never read offsets |
| Understanding IR | Fast | Internal to Fast; not a competing public ContextGraph |
| Mechanical Plan/PlanDAG/Changeset | Dev CLI | Fast supplies bounded context and provenance |
| Effect policy, sandbox and physical limits | Runtime | Fast operators run under Runtime in Full mode |
| Attempt, slots, retries and convergence | Loop | Loop pins generations and asks Fast for context |
| Goal, hypothesis and patch strategy | Agent/LLM/coordinator | Fast provides evidence; it does not decide |
| Card/PR delivery workflow | Sprint/Loop | They preserve Fast generation and receipts |
| UX, diagnostics and visual state | Code/Canvas/Desktop | They consume public status/capability contracts |
| Installation/profile composition | simplicio | It bundles Full and Loop-standalone profiles |

### 3. Two supported execution profiles

#### Full

Mapper → Fast → Dev CLI, coordinated by Loop and governed by Runtime.

- Runtime is the sole authority for effects.
- Agent, Code and other coordinators consume Loop/Runtime contracts.
- Fast always uses its Python engine.
- A shell bypass is not allowed when Runtime operators are available.

#### Loop standalone

Loop → Fast → (Mapper adapter + Dev CLI adapter).

- Runtime, Agent and Code are not required dependencies.
- The Loop remains responsible for slots, retries and convergence.
- Fast encapsulates Mapper and Dev CLI integration details.
- Writes use explicit local guards and receipts.
- The same ContextPacket, Generation and Changeset contracts are used as Full mode.

### 4. Engine selection

The public selector is python|off.

- python: the only engine; always selected, no probing or fallback wording.
- off: let the consumer use its previous path when supported.

### 5. Data and serialization boundaries

- Source files are the only authoritative mutable state.
- Internal persistence uses the versioned binary/mmap representation and the ecosystem's
  HBP/HBI rules.
- JSON is allowed at CLI/API/export boundaries only.
- Consumers use handles, ContextPackets, Changesets and Receipts; they do not parse
  .sfast offsets.
- mmap offsets are private implementation details; JSON is a boundary format only.
- Every context span carries source hashes; every attempt carries a pinned generation.

### 6. Failure and fallback semantics

A missing, incompatible, corrupt or stale component produces a typed, actionable result.

- No empty ContextGraph is accepted as a successful fallback.
- python selection always carries a stable reason code.
- A mutation is never retried after an uncertain effect without an idempotency
  key and state verification.
- A failed refresh leaves the previous complete generation untouched.

## Compatibility matrix

| Consumer | Full mode | Loop standalone | Direct mmap access |
| --- | --- | --- | --- |
| Mapper | required adapter | encapsulated adapter | forbidden |
| Dev CLI | Runtime-authorized effect | encapsulated guarded effect | forbidden |
| Loop | coordinator | coordinator | forbidden |
| Runtime | policy/effect authority | optional | forbidden |
| Agent/LLM | optional coordinator | optional | forbidden |
| Code/Canvas | optional UX | optional UX | forbidden |

## Required implementation gates

1. Contract fixtures and ownership lint pass.
2. Python conformance passes for the selected schema.
3. Engine selection emits a verifiable receipt.
4. Full and Loop-standalone clean installs pass their respective E2Es.
5. Benchmark reports observed results only; unavailable values are null with a reason.
6. Rollback to Fast off is tested before changing the default.

## Consequences

This decision makes Fast central to performance and delivery without making it a monolith.
It keeps a single Python implementation and prevents responsibility drift across the
ecosystem. The price is a shared contract/conformance gate and explicit profile packaging;
those are required for safe speed rather than optional polish.
