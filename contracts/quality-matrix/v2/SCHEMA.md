<!-- simplicio-contract:begin -->
contract: quality-matrix/v2
schema: simplicio.contract-doc/v1
purpose: `schema.json` is the single canonical, packaged terminal contract.
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# Quality matrix v2

`schema.json` is the single canonical, packaged terminal contract. The broad provider report
remains provider-owned; providers deterministically project it into these fifteen fixed lanes.
The core does not vendor provider schemas, and providers consume this schema from the
`simplicio-loop` wheel (`quality_matrix_v2.schema_text`) rather than copying it.

Every lane terminates as `PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE`. Skip, xfail, and flaky
outcomes cannot be projected to `PASS`. `NOT_APPLICABLE` requires a scoped, justified,
independently approved, policy-bound, unexpired waiver. Evidence is content-addressed and bound
to run, attempt, and commit; its author and auditor must differ. Metrics distinguish a measured
zero from unavailable (`value: null` plus a reason) and absent (invalid).

V1 remains readable. `migrate_v1` is deterministic and deliberately maps a v1 pass to `BLOCKED`
because v1 lacks v2 content hashes and independent audit. New writers emit only v2. External
providers run `python scripts/quality_matrix_v2.py validate receipt.json` as the conformance gate.
