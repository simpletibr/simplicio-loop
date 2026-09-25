# ADR-018: Reusable Rust Mapper core and differential shadow gate

Parent epic: #613. Implements the Mapper-side slice of #616.

## Status

Accepted for Mapper #616. Runtime cutover is sequenced in a separate
cross-repository change.

## Context

The Mapper repository had a PyO3 crate with deterministic parsing helpers while
the Runtime repository had an independent `simplicio-native-mapper` crate.
Those implementations could drift even when they observed the same source.
The Runtime crate also contains lifecycle, effect, fallback, and scaffolding
responsibilities that do not belong in a semantic kernel.

## Decision

Extract the deterministic PyO3 kernels into `rust/mapper-core`, a pure Rust
library. The Python adapter in `rust/src/lib.rs` and the Runtime-shaped adapter
in `rust/runtime-adapter` both call that library. The core has no filesystem,
auth, effect, fallback, provider, Loop, Sprint, or source-mutation dependency.

Add a fail-closed differential harness that sends one sorted, versioned source
generation to the Python reference path and the Rust adapter. It compares
semantic artifacts and coverage after removing adapter-only metadata. Results
are `match`, `mismatch`, or `unsupported`; mismatches and unavailable Rust
execution cannot be promoted to native defaults.

Publish a machine-readable matrix keyed by language, capability, and contract
version. `NATIVE_PARITY` and `native_default=true` are allowed only for rows
covered by a green committed differential report. The matrix carries the
Mapper version and a behavior-source fingerprint, so it becomes stale when
Mapper behavior changes.

## Consequences

- Python and Runtime have one Rust semantic implementation to consume.
- The current Python fallback remains orchestration outside the core and is
  not used as a silent differential substitute.
- Runtime cutover is explicit and measurable rather than being implied by a
  local extraction in a different repository.
- The first certified native-default capabilities are intentionally bounded to
  `files`, `imports`, and `batch` for the six language rows in the fixture set.
  Other capabilities remain `MISSING` or `SHADOW` in the matrix.

## Alternatives rejected

- Keep the two Rust implementations: rejected because semantic drift remains.
- Move Runtime lifecycle into the core: rejected because it violates the
  effect-free ownership boundary.
- Mark every native capability by one global `native=true` flag: rejected
  because promotion is capability-level and evidence-bound.
