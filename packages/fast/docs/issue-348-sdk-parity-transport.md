# Issue #348 SDK/session/transport evidence

`benchmarks/bench_sdk_parity_348.py` exercises the Python `ProjectionSDK`, the
checkout CLI capabilities command and a compiled Rust `--session` child. The
receipt compares the common read-only surface (`query` and `context`) while
preserving explicit Python-only and Rust-only operations; it does not claim
full write-surface equivalence.

The same receipt runs a resident transport probe with `max_inflight=1` and
`queue_capacity=1`. It records deadline expiry, queue backpressure, active
request cancellation and `READY -> CRASHED -> READY -> STOPPED` lifecycle
transitions. Every result remains `derived_read_only` and `dispatch=false`.

Generate the Windows receipt after building the Rust session binary:

```text
cargo build --manifest-path rust/Cargo.toml -p simplicio-fast-core --bin simplicio-fast-rs
python benchmarks/bench_sdk_parity_348.py `
  --root . `
  --rust rust/target/debug/simplicio-fast-rs.exe `
  --json-out benchmarks/results/issue348-sdk-parity-windows-20260802.json
```

Cross-platform installed artifacts, upgrade/rollback receipts and complete
Python/Rust surface equivalence remain separate #348 gates.
