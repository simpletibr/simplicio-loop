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
| required_language_recall | 1.0 | MEASURED |
| required_layer_recall | 1.0 | MEASURED |
| budget_fit_rate | 1.0 | ESTIMATED |
| mean_precision_at_k | 1.0 | MEASURED |
| sufficiency | 1.0 | MEASURED |
| task_success | 1.0 | MEASURED |
| determinism | 1.0 | MEASURED |
| abstention_accuracy | 1.0 | MEASURED |
| mean_latency_ms | 3202.372 | MEASURED |
| max_latency_ms | 8369.345 | MEASURED |
| mean_source_input_bytes | 1373.25 | MEASURED |
| mean_artifact_output_bytes | 65102.0 | MEASURED |
| mean_context_pack_bytes | 7890.5 | MEASURED |
| estimated_tokens_mean | 1973.0 | ESTIMATED |

## Per-case measurements

| Case | latency_ms | context_pack_bytes | estimated_tokens | precision@k | required-span recall | sufficiency | task-success | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| planes-ordering-ptbr | 8369.345 | 6826 | 1707 | 1.0 | 1.0 | 1.0 | 1.0 | pass |
| frontend-ordering-en | 1783.88 | 8235 | 2059 | 1.0 | 1.0 | 1.0 | 1.0 | pass |
| polyglot-cross-layer-en | 1468.447 | 13475 | 3369 | 1.0 | 1.0 | 1.0 | 1.0 | pass |
| no-match-abstention | 1187.818 | 3026 | 757 | n/a | n/a | 1.0 | 1.0 | pass |

Notes:

- `estimated_tokens` uses `utf8-bytes-div-4`, so it is labeled `ESTIMATED` rather than `MEASURED`.
- `budget_within_limit` and `budget_fit_rate` depend on that declared tokenizer policy, so they are also labeled `ESTIMATED` even though the serialized bytes themselves are `MEASURED`.
- `required_span_recall` is line-aware and comes from `orient` candidate evidence against reviewer-owned spans.
- `required_language_recall` / `required_layer_recall` prove the selected retrieval surface kept the requested polyglot/cross-layer diversity for labeled cases.
- `target_recall_at_k` and `test_recall_at_k` use the combined retrieval surface from `handoff` targets plus `orient` candidates.
- `task_success` is the benchmark verdict for each labeled case; it is not a claim about end-to-end downstream code generation outside this harness.

