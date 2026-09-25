# Quant benchmark Q0/Q1/Q2

Issue #198 adds a quality-first benchmark around the existing Python vector
paths:

- Q0 scores integral vectors with `turboquant.exact_rerank`;
- Q1 uses the existing slot executor's signed 8-bit encoding;
- Q2a uses the existing TurboQuant 4-bit quantizer and approximate scorer;
- Q2b retrieves through the same 4-bit path, then uses the existing integral
  reranker.

The benchmark does not compile Rust. Rust differential parity is `null` with
`RUNTIME_FAST_QUANT_CAPABILITY_UNAVAILABLE` until an admitted Runtime artifact
publishes that capability.

`BENCH_SCHEMA` and `run_quant_benchmark(vectors, queries, top_k=...)` remain as
the compatibility API published by PR #217. The wrapper delegates to the real
Q0/Q1/Q2a implementations and preserves the compact response fields and lane
names. It is marked deprecated in favor of the evidence-rich `run_benchmark`.

## Reproduce

```bash
PYTHONPATH=src python benchmarks/quant_benchmark_198.py \
  --repetitions 10 \
  --sizes 10000,100000,1000000 \
  --max-vectors 10000 \
  --dimension 16 \
  --candidate-k 80 \
  --result-k 20 \
  --seed 198
```

The default bounded run measures 10,000 vectors and classifies 100,000 and
1,000,000 as `BLOCKED`, with `null` plus `CAPACITY_LIMIT_CONFIGURED`. Increase
`--max-vectors` only on a host provisioned for those sizes. An unavailable
size is never replaced with a projected number.

Outputs:

- `benchmarks/results/quant-benchmark-198.json`: raw samples, manifests,
  hashes, hardware, page faults, I/O, quality and promotion decision;
- `benchmarks/reports/quant-benchmark-198.md`: compact trade-off report;
- `benchmarks/reports/quant-benchmark-198.svg`: measured size, p95 latency
  and Recall@10 chart;
- `benchmarks/schema/quant-benchmark-v1.schema.json`: receipt schema.

Each lane shares the same corpus, query, relevance-judgment, embedding,
generation and configuration hashes. Each repetition builds and atomically
persists an index, verifies its digest, measures first mmap touch separately
from a warm touch, then executes all frozen queries.

## Promotion gate

Q2b is promoted only if every independent check passes:

1. Recall@10 regression is within the configured maximum.
2. nDCG@10 regression is within the configured maximum.
3. Memory reduction under the declared storage policy reaches the configured
   minimum.
4. Query p95 latency ratio is within the configured maximum.
5. Integral reranking was actually measured.
6. Both comparator results are classified `MEASURED`.

The decision is fail-closed. A memory win cannot override a quality or
latency failure.

The default policy is `dedicated-end-to-end`: Q2b includes both its quantized
index and the integral rerank store, preventing an index-only saving from
creating a false promotion. A deployment that already owns and reuses the
integral store may opt in with `--shared-integral-store`; that choice is
recorded in configuration, per-lane memory fields and the promotion receipt.

## Failure and provenance contracts

The index manifest rejects:

- `INDEX_STALE`: corpus, embedding or config binding changed;
- `INDEX_CORRUPT`: missing, truncated or digest-mismatched bytes;
- `INDEX_CROSS_GENERATION`: requested and indexed generations differ;
- `BACKEND_INCOMPATIBLE`: the admitted backend differs.

The benchmark also hashes the real repository text corpus for provenance.
The scale matrix uses the deterministic synthetic relevance fixture, and the
receipt states that distinction explicitly.

Published evidence additionally binds the source commit and Git tree. Its
`source_state.reproducible` flag is true only when generation started from a
clean tree; dirty paths are recorded and fail schema validation for published
receipts.
