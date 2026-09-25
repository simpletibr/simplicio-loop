# Optional precompiled Fast native artifacts

Expected layout:

```text
artifacts/<platform>/simplicio.fast-native_v1/
  manifest.json
  <filename from manifest>
```

The manifest must contain `abi`, `platform`, `filename`, and `sha256`. Supported
platform tags are `linux-x86_64`, `linux-aarch64`, `macos-aarch64`, and
`windows-x86_64`.

This source tree currently contains **no precompiled native binary**. Therefore
`resolve_packaged_backend()` returns the standalone Python backend with
`RUST_ARTIFACT_MISSING`. A release pipeline may place a binary in this layout;
the runtime selects it only after ABI, platform, filename and SHA-256 validation
and executes it directly, without invoking Cargo or `rustc`.
