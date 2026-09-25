# Issue #346 capability-ranking quality dataset

`benchmarks/bench_capability_quality_346.py` contains a versioned, labeled
advisory corpus for two capability-selection scenarios. It measures
precision@k, recall@k and nDCG@k from the ranked handles while preserving
`estimated`, `measured`, `simulated` and `unknown` metric classes.

The corpus includes hard-incompatible, foreign-scope and unknown-policy
candidates. The receipt asserts that hard-incompatible candidates never become
eligible and that the output remains `authority=advisory_only`; the benchmark
does not authorize a worker, tool or model.

Generate the deterministic receipt with:

```text
python benchmarks/bench_capability_quality_346.py --json-out benchmarks/results/issue346-capability-quality-windows-20260802.json
```
