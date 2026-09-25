# Native backend ownership and compatibility

Runtime owns native execution. Fast owns Python semantics, snapshots, context
selection, and the adapter contract used to ask Runtime for a verified native
operation. Fast does not install or invoke a local Rust toolchain. See
ADR-0003. Runtime's public
Fast ABI is `simplicio.runtime.fast/v1`. Python remains complete and portable.
Runtime artifacts are selected only when signature policy, ABI, version,
platform, SHA-256, doctor, capability and conformance bindings pass.

The Rust reader is released as the precompiled `simplicio-fast-rs` core under
`simplicio.fast-core/v1`. The release archive contains its hashable executable
and `engine-manifest.json`; after extracting the platform archive, set
`SIMPLICIO_FAST_RUST` to that executable. Fast verifies its versioned engine
handshake before selecting it. The archive is produced only in CI; consumers
never need Cargo or rustc.

The older `simplicio.fast-native/v1` resolver from PR #212 remains a
time-bounded compatibility surface. It is not a second permanent Rust engine
and new Loop consumers must use `RuntimeFastBackend`.

The legacy compatibility ABI is `simplicio.fast-native/v1`. It remains available
only for controlled migration and rollback. CI may publish precompiled
compatibility artifacts, but consumers select them only after ABI, package
version, platform, size, source commit, and SHA-256 bindings all match.

| Target | Python | Precompiled compatibility artifact |
|---|---:|---:|
| Linux x86_64 | supported | CI-published and manifest-verified |
| Linux aarch64 | supported | CI-published and manifest-verified |
| macOS aarch64 | supported | CI-published and manifest-verified |
| Windows x86_64 | supported | CI-published and manifest-verified |
| Other targets | supported | rejected as `PLATFORM_UNSUPPORTED` |

`scripts/verify_native_bundle.py` verifies an extracted release asset without
Cargo or rustc. A missing, corrupt, incompatible, timed-out, or crashed binary
never produces a native success receipt. Missing Runtime
selects Python only in `auto`, with `RUNTIME_MISSING`; explicit `rust` fails
closed. Corrupt, incompatible, timed-out, cancelled or crashed Runtime
processes never become successful receipts. Inputs are immutable values and
the adapter exposes no write operation.

The installed canonical policy is
`simplicio_fast/release_policy.json`; `pyproject.toml` is the sole source of
package version and dependency metadata.
