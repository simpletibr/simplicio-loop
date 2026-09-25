# Fast versus baseline benchmark

- Workload: 50 files × 20 functions
- Repetitions: 10
- Build wall time: 116.283 ms
- Baseline scan total wall time: 1335.363 ms
- Baseline AST-reparse total wall time: 382.544 ms
- Fast Python total wall time: 532.045 ms
- Speedup versus scan: 2.510x
- Speedup versus AST reparse: 0.719x
- Estimated input tokens without Fast: 11000
- Estimated input tokens with Fast: 2500
- Estimated tokens saved: 8500 (77.27%)
- Baseline alteration total wall time: 295.348 ms
- Fast hot alteration total wall time: 208.013 ms
- Fast alteration + refresh total wall time: 1023.406 ms
- Alteration speedup (hot): 1.420x
- Alteration speedup (with refresh): 0.289x
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
