# Fast versus baseline benchmark

- Workload: 50 files × 20 functions
- Repetitions: 10
- Build wall time: 333.639 ms
- Baseline scan total wall time: 335.481 ms
- Baseline AST-reparse total wall time: 1235.711 ms
- Fast Python total wall time: 950.698 ms
- Speedup versus scan: 0.353x
- Speedup versus AST reparse: 1.300x
- Estimated input tokens without Fast: 11000
- Estimated input tokens with Fast: 2500
- Estimated tokens saved: 8500 (77.27%)
- Baseline alteration total wall time: 487.930 ms
- Fast hot alteration total wall time: 183.382 ms
- Fast alteration + refresh total wall time: 1086.091 ms
- Alteration speedup (hot): 2.661x
- Alteration speedup (with refresh): 0.449x
- Alteration estimated tokens without Fast: 11000
- Alteration estimated tokens with Fast: 50
- Rust standalone status: complete
- Rust standalone total wall time: 1491.2827 ms
- Rust standalone speedup versus Python Fast: 0.6375036738507058x
- Full standalone status: blocked (cross_repo_runtime_integration_missing)
- Loop standalone status: blocked (cross_repo_runtime_integration_missing)

Token values use `whitespace-v1-estimate`; they are not provider billing telemetry.
Rust standalone is a real subprocess/IPC read over a Python-built snapshot; it is not an end-to-end Rust build measurement.
Full/Loop cells are blocked with an explicit integration reason, not inferred as measured.
Alteration is a deterministic local fixture (locate + edit + py_compile), not an LLM/provider delivery run.
