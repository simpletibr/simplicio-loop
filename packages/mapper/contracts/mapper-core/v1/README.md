# Mapper core contract — `v1`

This directory defines the bounded, deterministic source-generation boundary
for the reusable Rust Mapper core introduced for Mapper #616 under parent epic
#613.

## Boundary

`rust/mapper-core` owns pure semantic kernels only:

- UTF-8 SHA-256 hashing;
- import extraction for the negotiated language set;
- bounded batch parsing;
- deterministic symbol-index and graph-edge canonicalization;
- canonical JSON and contract diagnostics already exposed by the Rust path.

The core does not read or write files, persist state, authenticate callers,
execute effects, select fallbacks, mutate source, or know about providers,
Loop, Sprint, or Runtime orchestration.

`rust/src/lib.rs` is the Python/PyO3 adapter. `rust/runtime-adapter` is the
effect-free Runtime adapter boundary used by the local differential harness.
The Runtime repository migration remains a sequenced follow-up because its
current native mapper crate is a separate repository-owned workspace member;
see [`docs/evidence/mapper-616-runtime-migration-plan.md`](../../../docs/evidence/mapper-616-runtime-migration-plan.md).

## Request/result boundary

The adapter accepts `simplicio.mapper-core-request/v1`:

```json
{
  "schema": "simplicio.mapper-core-request/v1",
  "contract_version": "v1",
  "capability": "imports",
  "language": "python",
  "source_generation": [{"path": "src/main.py", "content": "import os\n"}]
}
```

It returns `simplicio.mapper-core-result/v1`. The differential harness compares
only the semantic fields (`contract_version`, `capability`, `language`,
`coverage`, and `artifact`); adapter/core identity fields are implementation
metadata and are normalized away.

## Differential gate

Run the same sorted source generation through the Python reference functions
and the Rust Runtime adapter:

```bash
python3 scripts/mapper_differential.py --repo . --json
python3 scripts/mapper_differential.py --repo . --output artifacts --json
python3 scripts/mapper_capability_matrix.py --repo .
```

Each `(language, capability, contract_version)` result is `match`, `mismatch`,
or `unsupported`. A Rust build/transport failure is `unsupported`, never a
Python fallback and never a parity pass. A mismatch includes JSON-path diffs
and keeps `native_default=false`.

The capability matrix is tied to the current Mapper release and a fingerprint
of the behavior sources. Any behavior-source edit or Mapper version change
makes the committed matrix stale until the differential fixture report is
regenerated and reviewed.
