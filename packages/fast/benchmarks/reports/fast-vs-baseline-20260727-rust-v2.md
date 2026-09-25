# Fast versus baseline benchmark

- Workload: 50 files × 20 functions
- Repetitions: 10
- Build wall time: 88.472 ms
- Baseline scan total wall time: 104.245 ms
- Baseline AST-reparse total wall time: 277.639 ms
- Fast Python total wall time: 285.954 ms
- Speedup versus scan: 0.365x
- Speedup versus AST reparse: 0.971x
- Estimated input tokens without Fast: 11000
- Estimated input tokens with Fast: 2500
- Estimated tokens saved: 8500 (77.27%)
- Baseline alteration total wall time: 182.037 ms
- Fast hot alteration total wall time: 121.487 ms
- Fast alteration + refresh total wall time: 683.416 ms
- Alteration speedup (hot): 1.498x
- Alteration speedup (with refresh): 0.266x
- Alteration estimated tokens without Fast: 11000
- Alteration estimated tokens with Fast: 50
- Rust standalone status: complete
- Rust standalone total wall time: 681.7462 ms
- Rust standalone speedup versus Python Fast: 0.4194431886822398x
- Full standalone status: blocked (runtime_authorization_required)
- Full delivery wall time: 6.2541 ms
- Loop standalone status: applied (none)
- Loop delivery wall time: 590.024 ms

Token values use `whitespace-v1-estimate`; they are not provider billing telemetry.
Rust standalone is a real subprocess/IPC read over a Python-built snapshot; it is not an end-to-end Rust build measurement.
Full delivery is measured fail-closed without Runtime authorization; Loop standalone is a real local delivery through the Dev CLI adapter.
Alteration is a deterministic local fixture (locate + edit + py_compile), not an LLM/provider delivery run.
