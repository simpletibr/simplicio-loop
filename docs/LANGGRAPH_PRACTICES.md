# LangGraph practices vs Simplicio loop (audit)

**Finding (MEASURED):** the Simplicio product stack does **not** depend on the
`langgraph` Python package. Orchestration is **Python-first** in
`simplicio-loop` / `simplicio-dev-cli` / `simplicio-mapper`,
with **mutation authority and gates** owned by **Runtime (Rust)**.

This document maps [LangGraph durable-agent practices](https://langchain-ai.github.io/langgraph/)
to Simplicio primitives so we stay aligned without importing LangGraph into the
core path (which would conflict with Runtime ownership of MCP/gates/effects).

## Practice matrix

| LangGraph practice | Simplicio equivalent | Status |
|--------------------|----------------------|--------|
| Typed graph state | JSON schemas + dataclasses (`checkpoint_lifecycle`, contracts) | Aligned |
| Reducer / single-writer state | Leases, promotion fence, overlay isolation | Aligned |
| `thread_id` for resume | `task_id/attempt_id` exposed as `thread_id` on checkpoints | Aligned (explicit) |
| Checkpointer per superstep | `CheckpointLifecycle.checkpoint()` + digest lineage | Aligned |
| Idempotent side effects | Receipt digests; **APPLIED requires non-empty receipts** | Aligned (enforced) |
| `interrupt` / HITL | Action Gate + states HELD / CANCELLED / promotion fence | Aligned |
| No concurrent `thread_id` writers | Overlay exclusivity + fence | Aligned |
| Separate resume call (no nest) | Loop drain / self-paced tick re-reads scratchpad + checkpoint | Aligned |
| Durable storage | File JSON under `.simplicio-loop/loop-runs/…` (atomic write + fsync) | Aligned (local) |
| Postgres/SQLite checkpointer package | Not used; MapperStore owns **global memory**, not loop attempt state | Intentional split |
| Embed LangGraph runtime | **Out of scope** for core — Runtime is Rust | Do not adopt |

## What we deliberately do **not** do

1. **Do not add `langgraph` as a core dependency** of loop/mapper/dev-cli.
   Graph scheduling for code mutation is owned by Loop + Runtime receipts.
2. **Do not store loop attempt checkpoints in `memory.sqlite`.**  
   Global neural/MapperStore memory is a different SoT (facts/skills/recall).
3. **Do not re-run effectful nodes on resume without receipts** — that is the
   LangGraph “replay risk” class of bugs.

## Operator map (if you know LangGraph)

```text
LangGraph node          →  Simplicio
──────────────────────     ────────────────────────────
orient / plan           →  mapper status/handoff context
tool / edit node        →  dev-cli / Runtime edit (gated)
interrupt(HITL)         →  Action Gate (ask/safe/auto)
checkpointer            →  CheckpointLifecycle + journal
thread_id               →  task_id/attempt_id
Command(resume=…)       →  next loop tick / drain claim
```

## OSS note

A full upstream LangGraph tree may exist under `simplicio-loop-oss/work/` for
**contribution** work. That is not the product runtime path.

## Change log

- 2026-08-03: audit documented; `thread_id` + APPLIED-receipt enforcement on
  `CheckpointLifecycle.checkpoint()`.
