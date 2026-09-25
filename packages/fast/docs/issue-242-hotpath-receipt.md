# Issue #242 current checkout hot-path receipt

`benchmarks/bench_issue242_hotpath.py` binds its receipt to the checkout
`source_commit` and runs 30 repetitions of unchanged and one-file scoped
handoffs at 1k, 10k, 100k and 1M symbols. It reports median, p95, p99, CPU,
parsed/reused files, parity and stage coverage. A cold rebuild is measured once
per scale because a 1M cold rebuild is intentionally expensive; it is not
presented as a 30-repetition cold gate in this receipt.

The unchanged path is measured with a persisted content-addressed delta and
the current source identity cache. The one-file path rewrites and parses only
`module_000.py`; every handoff still verifies the bounded source/parity
contract. JSON is an evidence boundary; the production path remains the
Python/Rust-independent `WorkspaceStore` implementation.

Run from the checkout root:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python benchmarks/bench_issue242_hotpath.py --json-out benchmarks/results/issue242-windows-hotpath-20260802.json
```

Linux receipts, RSS/page-fault collection, CI regression enforcement, final
coverage, and the physical 20-reader/10-worktree matrix remain explicit
residuals for #242.
