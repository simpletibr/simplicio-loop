# Issue #240 tokenizer matrix

`benchmarks/bench_tokenizer_matrix_240.py` measures the exact tokenizer
providers available in the local environment. It uses four frozen task texts,
30 repetitions per task and records the text digest, exact token count and
local tokenizer wall time. Provider billing telemetry is deliberately marked
as unavailable; this receipt is not a usage or cost claim.

The 2026-08-02 Windows receipt covers `tiktoken:cl100k_base`,
`tiktoken:o200k_base` and `tiktoken:model:gpt-4o`. All three resolved exactly
and all matrix gates passed.
