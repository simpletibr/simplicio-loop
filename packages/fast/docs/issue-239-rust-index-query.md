# Rust indexed query evidence

The Rust reader validates the persisted `exact`, `names`, `paths` and `kinds`
indexes when a snapshot is opened, then reuses the validated representation for
resident queries. Indexed queries do not call `SnapshotReader::symbols()`.

The benchmark `benchmarks/bench_rust_query_239.py` runs 30 warm repetitions at
10k, 100k and 1M symbols. The committed Windows receipt records the selected
index, candidates visited, records decoded, raw wall samples and process RSS.
The RSS gate is measured relative to the resident process after the warmup
query; mmap/index-open RSS is reported separately as the baseline.

The companion `benchmarks/bench_rust_relations_239.py` receipt exercises the
resident `relations` operation against a high-cardinality synthetic corpus.
The Windows 2026-08-02 receipt runs 30 repetitions at 10k symbols/30k
relations and 100k symbols/300k relations, requesting ten `value_0` call
edges. It records raw wall samples, p95/p99, resident RSS and the bounded
decoded-result count.

Legacy snapshots or unindexed predicates retain a labeled scan fallback in the
planner receipt. A corrupt snapshot or out-of-bounds persisted index fails
closed during open/query validation.
