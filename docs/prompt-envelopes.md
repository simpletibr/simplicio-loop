# Prompt envelopes

`simplicio.prompt-envelope/v1` records the prompt layers used by a task without
persisting raw prompt text. It includes per-layer estimates and effective
budgets, a stable immutable-prefix hash, context-pack hash, and a typed retry
delta. An overflow is visible as `needs_broader_context`; it is never silently
truncated.

The receipt is included in task results under `prompt_envelope`. Budgets can be
adjusted per layer with `SIMPLICIO_PROMPT_BUDGET_<LAYER>`. The current release
keeps the legacy rendered prompt byte-compatible while making retry/cache
identity inspectable for the runtime and loop.
