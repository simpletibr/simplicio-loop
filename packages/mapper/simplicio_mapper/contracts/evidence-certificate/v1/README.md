# EvidenceCertificate contract — `v1`

Minimal, versioned certificate proving that a `ContextSnapshot` can be carried
through a Runtime-shaped evidence envelope without losing:

- `revision`
- `snapshot_id`
- `fidelity`
- reversible source `handles`

This contract is intentionally small. It does **not** claim that Simplicio
Runtime executed the payload. External Runtime execution must be marked
`UNVERIFIED` unless proven by an out-of-process receipt.

## Scope

The `v1` envelope models three things:

1. certificate identity (`certificate_id`, schema, producer);
2. the observed mapper context copied from a `ContextSnapshot`;
3. a Runtime-shaped execution section whose external execution status is
   explicitly `UNVERIFIED`.

## Fixture

- `fixtures/runtime-shaped/evidence-certificate.json`

The fixture is a representative example, not a proof of live Runtime
execution.
