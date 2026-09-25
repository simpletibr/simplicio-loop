# Issue #344 quality corpus

This slice adds the versioned `simplicio.fast.knowledge-quality-corpus/v1` at
`fixtures/knowledge/v1/issue344-quality-corpus.json`. It is a frozen repository
corpus whose provenance names the source documents and issue acceptance criteria;
it is not presented as a production MapperStore dump.

`benchmarks/bench_knowledge_quality_344.py` loads the corpus through
`KnowledgeProjection`, executes eight bounded precedent queries, and emits
`simplicio.fast.knowledge-quality-receipt/v1`. The receipt includes the corpus
digest, raw expected/actual handles, lexical fallback labels, recall@1,
precision@1, nDCG@1, latency and explicit gates. It never exposes fact text in
the result rows.

Run it from the checkout root:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python benchmarks/bench_knowledge_quality_344.py --json-out benchmarks/results/issue344-windows-quality-20260802.json
```

The evidence is intentionally scoped: it proves deterministic quality behavior
on this versioned corpus. Canonical external adapters, Python/Rust parity and
installed-consumer E2E remain residual acceptance criteria for #344.
