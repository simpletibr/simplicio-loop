# Issue #240 task-recall corpus

`fixtures/delivery/v1/issue240-task-recall.json` is a versioned frozen source
task fixture covering four current Fast delivery paths. The benchmark runs the
real `DeliveryEngine` in standalone bootstrap mode, deduplicates selected
spans by file, and records cold/warm wall time, p95 and recall/precision for
the expected files.

The receipt intentionally reports `status=partial`: `downstream_success` is
measured only for the bounded `bounded-source-reader/v1` consumer that reads
selected files and checks required-file inclusion in this frozen fixture. This
is not a historical task oracle and does not claim installed consumer parity;
historical recall and installed cross-platform results remain unverified.

`benchmarks/bench_delivery_240_100k.py` separately measures the required
100k-symbol warm-preparation gate with 10 repetitions and records the raw
samples, p95 and the <=25 ms decision. Its fixture is synthetic and the
receipt remains partial until the measured gate, historical corpus and
installed consumer evidence all pass.
