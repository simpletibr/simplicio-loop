# Prompt envelopes

`simplicio.prompt-envelope/v1` records the prompt layers used by a task without
persisting raw prompt text. It includes per-layer estimates, soft/hard/effective
budgets, stable immutable-prefix and context-pack hashes, provider/model
identity, and a typed retry delta receipt.

Budgets are selected by prompt task class (`SIMPLICIO_PROMPT_TASK_CLASS`) and
scaled by the model context window (`SIMPLICIO_MODEL_CONTEXT_WINDOW`, falling
back to `SIMPLICIO_LOCAL_CTX`). Per-layer overrides remain available via
`SIMPLICIO_PROMPT_BUDGET_<LAYER>`.

The receipt is included in task results under `prompt_envelope`. An overflow is
visible as `needs_broader_context`; it is never silently truncated. Attempts 2+
keep the base prompt byte-stable and send a compact `Retry delta:` payload with
affected files, failure classification, and diagnostic hashes instead of
repeating the rendered base prompt inside the retry payload.
