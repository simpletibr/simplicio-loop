# Behavioral scorecard

Reproducible benchmark for issues #199 and #208 using a reviewer-labeled corpus under `tests/fixtures/evaluation_corpus`.

Replay commands:

```bash
python scripts/evaluation_scorecard.py --json
python scripts/evaluation_scorecard.py --write
python -m pytest tests/python/test_evaluation_benchmark.py tests/python/test_evaluation_corpus.py
```

## Aggregate measurements

| Metric | Value | Status |
|---|---:|---|
| target_recall_at_k | 1.0 | MEASURED |
| test_recall_at_k | 1.0 | MEASURED |
| required_span_recall | 1.0 | MEASURED |
| mean_precision_at_k | 1.0 | MEASURED |
| sufficiency | 1.0 | MEASURED |
| task_success | 1.0 | MEASURED |
| determinism | 1.0 | MEASURED |
| abstention_accuracy | 1.0 | MEASURED |
| mean_latency_ms | 2344.511 | MEASURED |
| max_latency_ms | 4498.971 | MEASURED |
| mean_source_input_bytes | 1064.333 | MEASURED |
| mean_artifact_output_bytes | 50282.667 | MEASURED |
| mean_context_pack_bytes | 2235.667 | MEASURED |
| estimated_tokens_mean | 559.333 | ESTIMATED |

## Per-case measurements

| Case | latency_ms | context_pack_bytes | estimated_tokens | precision@k | required-span recall | sufficiency | task-success | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| planes-ordering-ptbr | 1027.133 | 2539 | 635 | 1.0 | 1.0 | 1.0 | 1.0 | pass |
| frontend-ordering-en | 4498.971 | 3041 | 761 | 1.0 | 1.0 | 1.0 | 1.0 | pass |
| no-match-abstention | 1507.428 | 1127 | 282 | n/a | n/a | 1.0 | 1.0 | pass |

Notes:

- `estimated_tokens` uses `utf8-bytes-div-4`, so it is labeled `ESTIMATED` rather than `MEASURED`.
- `required_span_recall` is line-aware and comes from `orient` candidate evidence against reviewer-owned spans.
- `target_recall_at_k` and `test_recall_at_k` use the combined retrieval surface from `handoff` targets plus `orient` candidates.
- `task_success` is the benchmark verdict for each labeled case; it is not a claim about end-to-end downstream code generation outside this harness.

