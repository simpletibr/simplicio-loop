# Issue #244 parser-adapter benchmark

`benchmarks/bench_parser_244.py` measures the Python parser adapter at the
10k and 100k symbol scales. Each category records 10 raw repetitions and
reports wall time, CPU time, RSS, payload bytes, parsed/reused files and
parsed/reused source bytes. The receipt also includes p95 and p99 wall-time
percentiles.

The three measured categories are:

- `cold`: parse every source file;
- `one_file`: parse one changed file and reuse the complete previous payload;
- `unchanged`: parse no files and reuse the complete previous payload.

The Windows receipt is committed at
`benchmarks/results/issue244-windows-20260802-parser-10k-100k.json`.
It was produced with:

```text
python benchmarks/bench_parser_244.py --symbols 10000 100000 --repetitions 10 --json-out benchmarks/results/issue244-windows-20260802-parser-10k-100k.json
```

Linux parity remains an external runner gate for issue #244.
