# Runtime-first semantic scoring (issue #186)

Status: Python reference contract complete. LiteRT is optional and Runtime-owned.

## Ownership and invariants

The `.sfast` snapshot, Mapper canonical IDs, source SHA-256 values and snapshot
generation remain authoritative. Embeddings and reranker output are disposable
auxiliary scores. They never prove a call, import, test or ownership relation.

Fast imports no LiteRT package, downloads no model and starts no model process.
Production inference enters through `simplicio.inference-backend/v1`. The
`LocalLiteRTAdapter` accepts only an already-created injected session and refuses
construction unless `isolated_test=True`; it exists for hermetic adapter tests,
not production.

If Runtime inference is absent, incompatible, timed out, cancelled, malformed or
over budget, Fast stays fully functional using deterministic lexical/structural
ranking and emits a stable fallback reason.

## Contracts

`simplicio.fast.semantic-score/v1` is one candidate row:

- `canonical_id`: Mapper-owned handle;
- `score` and `confidence`: normalized auxiliary values;
- `reason`: `NONE` or the fallback reason code;
- `method`: Runtime semantic auxiliary or deterministic fallback;
- `provenance`: generation, source SHA-256, model SHA-256, preprocessing hash
  and the explicit `derived_auxiliary` authority label;
- `components`: lexical, structural, semantic and optional reranker scores.

The ranking receipt is
`simplicio.fast.semantic-ranking-receipt/v1`. It contains the versioned formula,
all candidate rows, bounded selection, abstention, cache receipt, budgets and
observed metrics. Unknown/empty coverage produces abstention instead of a forced
context result.

The Runtime SPI is deliberately small:

```text
InferenceBackend.capabilities()
  -> {"schema":"simplicio.inference-backend/v1",
      "operations":["embeddings", ...]}

InferenceBackend.infer(simplicio.inference-request/v1,
                       deadline=<monotonic absolute>,
                       cancel_event=<optional>)
  -> simplicio.inference-result/v1
```

The response must bind the exact model SHA-256 and return the declared vector
dimension. Count, schema, model, dimension and finite-number drift fail closed.

`EmbeddingProvider` and `Reranker` are Python protocols. This keeps provider and
reranker implementations replaceable without adding a hard inference
dependency to Fast.

## Model profile

Fast does not bundle or silently choose a production model. Runtime must supply a
`ModelIdentity` containing:

| Field | Requirement |
| --- | --- |
| model/version | non-empty immutable identity |
| sha256 | exact lowercase artifact digest |
| preprocessing | versioned normalization/tokenization name |
| dimension | positive fixed output dimension |
| max_tokens | positive input bound |
| license | non-empty audited license identifier |

The issue #186 benchmark uses only `frozen-quality-fixture`, a repository test
fixture with six dimensions and `repository-test-fixture` licensing. It is not
a downloadable or production model and is not represented as LiteRT
performance. A production release must select and license a model in Runtime,
publish its immutable manifest and then pass this identity to Fast. Swapping
model SHA or preprocessing changes only the derived cache key.

## Derived artifact and incremental refresh

`DerivedVectorStore` keys manifests by:

```text
SHA-256(
  simplicio.fast.semantic-vector-artifact/v1,
  snapshot generation,
  model SHA-256,
  preprocessing SHA-256
)
```

The manifest records every canonical ID and source SHA-256. Refresh embeds only
new/changed sources, reuses unchanged vectors and prunes removed sources.
Different generations, models or preprocessing never share a manifest.
Vector objects are canonical JSON named by their content SHA-256 and published
with fsync plus atomic replace. Truncation/hash/dimension drift discards the
artifact and rebuilds it; source/snapshot state is never changed.

## Bounded execution

`SemanticBudgets` bounds:

- candidates and selected results;
- request, index and memory bytes;
- batch size and queued requests;
- latency/deadline;
- selected token count.

Every batch checks cancellation and the absolute deadline. Queue saturation
fails with `INFERENCE_BACKPRESSURE`. The default formula is
`lexical-structural-semantic/v1`:

```text
Runtime lane: 0.45 lexical + 0.15 structural + 0.40 semantic/reranker
Offline lane: 0.80 lexical + 0.20 structural
```

Ties are resolved by canonical ID, so the offline result is stable across input
order. Reranker output is auxiliary and must contain only known IDs with values
in `[0, 1]`.

## CLI and diagnostics

Run offline without a model:

```bash
simplicio-fast semantic-score "cache invalidation" \
  --generation <snapshot-generation> \
  --candidates candidates.json \
  --no-model
```

`candidates.json` is a list of `canonical_id`, `text`, optional
`source_sha256`, and optional normalized `structural_score`. If a SHA is
provided it must match text exactly. The CLI currently exposes the complete
offline lane; `--no-model` makes that choice explicit. Runtime injects the
production provider through the Python contract. It never accepts a model URL
and cannot download one. Issue #517's held-out optional-model experiment is
documented in [`docs/issue-517-optional-model-evaluation.md`](issue-517-optional-model-evaluation.md).

`simplicio-fast capabilities` includes
`simplicio.fast.semantic-capabilities/v1`, which reports Runtime-first status,
whether a provider is available, absence of implicit downloads, the fallback,
and explicit Rust parity status. Rust semantic parity is currently
`not_exposed` with `RUST_SEMANTIC_SURFACE_UNAVAILABLE`; no parity is fabricated.

## Reason codes

Important codes include:

- `INFERENCE_BACKEND_UNAVAILABLE`, `INFERENCE_BACKEND_ABI_MISMATCH`,
  `INFERENCE_BACKEND_CAPABILITY_MISSING`;
- `INFERENCE_DEADLINE_EXCEEDED`, `INFERENCE_CANCELLED`,
  `INFERENCE_BACKPRESSURE`, `INFERENCE_BACKEND_FAILURE`;
- `INFERENCE_RESPONSE_SCHEMA_MISMATCH`, `INFERENCE_MODEL_MISMATCH`,
  `INFERENCE_DIMENSION_MISMATCH`, `INFERENCE_VECTOR_NONFINITE`;
- `VECTOR_ARTIFACT_MISSING`, `VECTOR_ARTIFACT_CORRUPT`,
  `VECTOR_ARTIFACT_SCOPE_MISMATCH`;
- `CANDIDATE_BUDGET_EXCEEDED`, `REQUEST_BYTES_BUDGET_EXCEEDED`,
  `INDEX_BYTES_BUDGET_EXCEEDED`, `MEMORY_BUDGET_EXCEEDED`.

## Quality-first evidence

Run:

```bash
PYTHONPATH=src python benchmarks/bench_semantic_scoring_186.py
```

The frozen corpus compares the deterministic baseline with a deterministic fake
`InferenceBackend/v1` over at least ten repetitions. It records every query/run,
Recall@3, MRR, nDCG@3, token-budget coverage, wall time, CPU and process RSS in
`bench/results/semantic_scoring_186.json`.

This proves contract behavior and quality impact on the frozen fixture only. It
does not measure or claim real LiteRT device acceleration, provider tokens,
cost, Rust parity or a production model. Those require a Runtime-owned model
artifact and a real device benchmark.
