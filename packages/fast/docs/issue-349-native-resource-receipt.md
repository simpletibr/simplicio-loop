# Issue #349 native/resource receipt

`benchmarks/bench_native_resource_349.py` exercises the compiled
`simplicio-fast-native --session` path directly over its stdio-lines ABI. It
checks the native handshake, repeated SHA-256 requests, bounded paging,
overlay merge, invalid page limits and unknown-operation rejection. When
`psutil` is available it records raw latency samples, p50/p95, RSS before/after
and CPU user/system time.

The same receipt drives the existing `RolloutController` through shadow,
canary and rollback, then verifies corrupted persisted state fails closed.
All output remains `derived_read_only` with `dispatch=false`; the receipt does
not claim Linux/macOS assets or registry-level upgrade evidence.

Generate the Windows receipt with:

```text
cargo build --manifest-path native/fast-native/Cargo.toml --release
python benchmarks/bench_native_resource_349.py `
  --native native/fast-native/target/release/simplicio-fast-native.exe `
  --json-out benchmarks/results/issue349-native-resource-windows-20260802.json
```
