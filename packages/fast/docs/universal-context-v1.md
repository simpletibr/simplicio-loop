# Universal Context Compiler v1

`compile_context()` consumes typed projection envelopes from Code, Knowledge and
Operations and emits the provider/tool-neutral
`simplicio.fast.universal-context/v1` packet. Inputs are ordered by projection
type and stable handle, scoped by repository, and bounded by item, byte and
estimated-token budgets. Truncation reasons are explicit.

The packet contains derived facts with producer provenance and marks
`authority=facts_only` and `instructions=false`. It does not execute an LLM,
convert retrieved content into trusted instructions, authorize tools, or
replace the existing Code context hot path. Its receipt separately lists the
selected `source_generations` and `projection_generations`, so a consumer can
pin both producer inputs and the derived projection generation. Trust/authority
policy, Runtime admission and external adapters remain outside Fast.

## Source adapters

`simplicio.fast.context-source-adapters/v1` is the read-only boundary for
composing the typed outputs of Code, Knowledge and Operations. `adapt_code`
accepts only Code projection envelopes; `adapt_knowledge_result` accepts a
bounded `simplicio.fast.precedent-result/v1`; and `adapt_operations_result`
accepts an Operations query or snapshot. Every adapter requires the target
repository, preserves source and projection generations, and rejects foreign
scopes, malformed schemas, untyped items and private mmap fields before
`compile_context` is called. `compile_context_sources` then applies the same
budgets, trust floor and tokenizer contract as direct envelope compilation.
