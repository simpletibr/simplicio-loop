# Issue #517 optional-model evaluation

Status: not promoted. Fast remains model-free by default.

The reproducible experiment is [`benchmarks/bench_optional_model_517.py`](../benchmarks/bench_optional_model_517.py) over the curated, versioned dataset [`fixtures/optional-model/v1/issue517-task-corpus.json`](../fixtures/optional-model/v1/issue517-task-corpus.json). The dataset separates four training examples, three development examples and twelve held-out evaluation queries. Its source list names the repository files used to curate the examples and its handles/generation are explicitly labelled Mapper-shaped fixture evidence, not a production Mapper handoff.

Run it with:

```bash
PYTHONPATH=src:. python3 benchmarks/bench_optional_model_517.py \
  --dataset fixtures/optional-model/v1/issue517-task-corpus.json \
  --json-out bench/results/optional_model_517.json \
  --repetitions 10
```

The assisted lane uses `RuntimeEmbeddingProvider` and a deterministic topic
fixture so the experiment is hermetic. It is not a learned model, does not
download a model, and is not a production quality or LiteRT performance claim.
It exists to exercise the optional-provider protocol and promotion gates.

## Baseline scope

The baseline is the current deterministic retrieval/ranking path, with the
following boundaries recorded rather than inferred:

| Area | Current deterministic evidence | Measurement boundary |
| --- | --- | --- |
| Explicit symbol/path matches | Fast exact/name/path/kind indexes | Included in exact-symbol/path held-out cases |
| Task intent | Task terms plus lexical/structural score | Included in every scored candidate |
| Graph proximity | Query-plan causal prefetch | Auxiliary prefetch, not a semantic ranking score |
| Precedent ranking | `KnowledgeProjection` lexical fallback | Existing #344 quality receipt; not silently replaced |
| Context budget | Candidate, byte and selected-token budgets | Checked for every benchmark row |
| BM25 | Not implemented in this revision | No BM25 result is claimed |

The benchmark reports Recall@1/3, Precision@3, MRR, nDCG@3, candidate-coverage
completion quality, wall/CPU latency, local inference latency, peak RSS, cache
hits, budget compliance and canonical evidence checks. Remote tokens and total
cost remain `null` because local inference supplies neither telemetry.

The adjacent deterministic receipts also pass locally: the #344 precedent
corpus reports Recall/Precision/nDCG `1.0`; the #345 multi-domain context
corpus reports precision/recall `1.0`, no duplicate or untrusted selection; and
the #240 source-task fixture reports recall `1.0` with downstream consumption
success. The latter remains `partial` for real historical and installed
cross-platform recall, so those claims are not promoted here.

## Local receipt

The ten-repetition receipt in `bench/results/optional_model_517.json` was run
on the checkout revision used for this evaluation. It measured:

| Lane | Recall@1 | Recall@3 | MRR | nDCG@3 | Wall p95 | CPU p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Deterministic baseline | 0.9091 | 1.0000 | 0.9545 | 0.9664 | 0.328 ms | 0.329 ms |
| Optional contract fixture | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 2.525 ms | 1.766 ms |

The fixture delta is Recall@1 `+0.0909`, MRR `+0.0455` and nDCG@3 `+0.0336`.
Exact-symbol/path cases had no regression; every ranked row retained its
fixture generation and candidate-text hash, with source path/symbol and source
file hashes recorded in the evidence bindings; and all rows stayed within the
declared candidate, byte and token budgets. The observed fixture RSS delta was
316 KiB.

## Decision

The quality/resource checks pass for the hermetic fixture, but the production
model gate fails intentionally: the fixture is neither learned nor an
authorized immutable model artifact. No embedding, reranker or mini-model is
therefore promoted into Fast, and no model dependency is added. The receipt
records Fast `2.0.30`, the checkout revision, the fixture Mapper generation,
and explicit null reasons for unavailable central binary and integrated Mapper
artifact digests. A future
promotion requires a Runtime-supplied model manifest with version, quantization,
dimensions, digest, license and CPU/RAM requirements, plus a real held-out
evaluation and provider telemetry.

The explicit deterministic CLI lane is:

```bash
simplicio-fast semantic-score "cache invalidation" \
  --generation <snapshot-generation> \
  --candidates candidates.json \
  --no-model
```

`--no-model` performs no inference and the output remains bound to canonical
candidate IDs, generation and source SHA-256 values. The local environment did
not provide the `simplicio` runtime-map/memory CLI or integrated Mapper,
Dev CLI, Runtime and Loop artifacts; those cross-repository claims remain
unverified and are not substituted with local fixture evidence.
