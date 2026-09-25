# Fast versus baseline benchmark

- Workload: 50 files × 20 functions
- Repetitions: 10
- Build wall time: 74.419 ms
- Baseline scan total wall time: 70.482 ms
- Baseline AST-reparse total wall time: 194.555 ms
- Fast Python total wall time: 246.300 ms
- Speedup versus scan: 0.286x
- Speedup versus AST reparse: 0.790x
- Estimated input tokens without Fast: 11000
- Estimated input tokens with Fast: 2500
- Estimated tokens saved: 8500 (77.27%)
- Baseline alteration total wall time: 148.317 ms
- Fast hot alteration total wall time: 128.196 ms
- Fast alteration + refresh total wall time: 663.794 ms
- Alteration speedup (hot): 1.157x
- Alteration speedup (with refresh): 0.223x
- Alteration estimated tokens without Fast: 11000
- Alteration estimated tokens with Fast: 50
- Rust standalone status: blocked
- Rust standalone total wall time: n/a ms
- Rust standalone speedup versus Python Fast: n/ax
- Full standalone status: blocked (cross_repo_runtime_integration_missing)
- Loop standalone status: blocked (cross_repo_runtime_integration_missing)

Token values use `whitespace-v1-estimate`; they are not provider billing telemetry.
Rust standalone is a real subprocess/IPC read over a Python-built snapshot; it is not an end-to-end Rust build measurement.
Full/Loop cells are blocked with an explicit integration reason, not inferred as measured.
Alteration is a deterministic local fixture (locate + edit + py_compile), not an LLM/provider delivery run.
