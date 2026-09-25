# ADR-0003: Runtime owns the Rust Fast engine

- Status: Accepted
- Date: 2026-07-28
- Fast issue: https://github.com/wesleysimplicio/simplicio-fast/issues/215
- Runtime parent: https://github.com/wesleysimplicio/simplicio-runtime/issues/3657
- Supersedes: the Rust ownership and direct executable sections of ADR-0001

## Decision

Fast keeps the complete Python reference implementation. The complete Rust engine is owned,
built and released by `simplicio-runtime`. Fast integrates it only through
`RuntimeFastBackend`, a read-only HBP stdio adapter.

The public modes remain `auto|rust|python|off`:

- `auto` admits Runtime only after artifact and handshake conformance; otherwise it selects
  Python and records a stable reason code.
- `rust` requires the verified Runtime backend and fails closed.
- `python` selects the reference path without probing Runtime.
- `off` disables acceleration and does not silently select Python.

Fast and Loop do not invoke a local Rust compiler. Release assets are built by Runtime's
release workflow and supplied with an expected SHA-256, target, version and ABI. A release
policy can additionally require a detached signature and pass its verifier to the adapter.

## Artifact admission

The adapter verifies, before process creation:

1. the file exists;
2. the host target is one of Linux x86_64/aarch64, macOS arm64 or Windows x86_64;
3. manifest and host targets match;
4. the ABI is exactly `simplicio.runtime.fast/v1`;
5. the artifact SHA-256 matches in constant time;
6. the manifest version is present;
7. a required release signature is present and validates.

It then sends a `doctor` request through `simplicio.hbp/v1`. Runtime must return its identity,
exact version, target, ABI, capabilities and a passing conformance digest. Missing capabilities,
failed conformance or unhealthy doctor results reject admission.

`SIMPLICIO_RUNTIME_BIN` and `SIMPLICIO_RUNTIME_MANIFEST` are the opt-in discovery pair. A bare
binary found on `PATH` is not executed because it has no pinned release manifest.

## Invocation and failure semantics

The stdio command is:

```text
simplicio fast-backend --stdio
```

Requests and responses bind schema, ABI and a content-addressed request ID. The adapter accepts
only read-only operations. Payloads are canonicalized into immutable values before process
creation. Runtime output is size-bounded and schema-checked before use.

Stable reason codes are:

```text
RUNTIME_MISSING ABI_MISMATCH VERSION_MISMATCH PLATFORM_UNSUPPORTED
HASH_MISMATCH SIGNATURE_MISMATCH RUNTIME_UNHEALTHY PROTOCOL_ERROR
TIMEOUT CANCELLED DISABLED
```

Timeout and cancellation terminate the child process. Crash, timeout, cancellation and protocol
failure do not retry in `rust` mode and cannot mutate source or snapshots because the bridge has
no write operation. `auto` may select Python only before an operation starts and always records
the reason.

## Loading and shadow rules

Runtime admission and Runtime execution do not import
`simplicio_fast.native_backend` or another Python hot-path module. The Python backend is imported
only when an already-selected Python path executes.

Shadow execution is permitted only in read-only benchmark/conformance tools. It is not available
on mutation surfaces and never authorizes an effect.

## PR #212 transition

PR #212's `native/fast-native` artifact and `simplicio.fast-native/v1` resolver are a compatibility
bridge for existing consumers, not a second permanent engine owner.

Migration policy:

1. Runtime issue #3657 publishes the HBP capability and cross-platform assets.
2. The same golden HBP fixtures are exercised by Python and Runtime.
3. Loop consumes `RuntimeFastBackend` receipts and stops discovering Fast-native assets.
4. The compatibility resolver remains for one documented minor-release window.
5. It is removed only after Runtime parity receipts exist on Linux, macOS and Windows.

Until steps 1–3 are measured, `auto` on a current Runtime without `fast-backend` correctly selects
Python with `RUNTIME_UNHEALTHY`; no compatibility artifact is reported as Runtime parity.

## Verification matrix

| Surface | Local evidence | Cross-platform release evidence |
| --- | --- | --- |
| Python reference | full HBP golden operation tests | package CI |
| Runtime-compatible fixture | handshake, dispatch, crash, timeout, cancel | Runtime CI |
| Official Runtime 3.5.5 | artifact hash passes; capability is not yet admitted | not claimed |
| Linux/macOS/Windows clean host | source tests model platform gates | required from Runtime release CI |

Fast-only tests do not claim the Runtime implementation or cross-platform release complete.
