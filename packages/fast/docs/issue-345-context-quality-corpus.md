# Issue #345 context quality corpus

`fixtures/delivery/v1/issue345-context-quality-corpus.json` is a versioned
two-task corpus spanning Code, Knowledge and Operations. The benchmark builds
the real in-memory producer projections, sends their typed query results
through `compile_context_sources()`, and records required-fact precision,
recall, duplicate handles, source bytes/tokens, truncation and packet digest.

Each scenario runs with an injected exact fixture tokenizer and with an
unavailable provider tokenizer. The latter is explicitly labeled
`estimated/provider_tokenizer_unavailable`; it is never reported as exact.
Retrieved untrusted text remains rejected by the declared `advisory` trust
floor and the packet keeps `authority=facts_only` and `instructions=false`.

Generate the Windows raw receipt with:

```text
python benchmarks/bench_context_quality_345.py `
  --corpus fixtures/delivery/v1/issue345-context-quality-corpus.json `
  --json-out benchmarks/results/issue345-context-quality-windows-20260802.json
```
