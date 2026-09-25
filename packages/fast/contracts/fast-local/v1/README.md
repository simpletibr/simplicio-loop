# Fast-Local contract surface v1

This directory is the authority for the contract between simplicio-fast policy
and simplicio-local execution. The envelope is simplicio.fast-local/v1 at
contract version 1.0; unknown fields and unsupported versions fail closed.

## Ownership and envelope

Local owns hardware topology/fingerprint, capability discovery, observed
telemetry, the ExecutionPlan digest/reason codes, and execution. Fast owns
policy decisions, decision receipts, confidence, and invalidation triggers.
Both sides share only the versioned envelope and generation binding.

Every message requires schema, contract_version, message_type, generation, and
payload. Generation binding includes generation_id, a 40-character source
revision, and hardware/model/backend/context/concurrency SHA-256 digests.

Required fields must carry a value. Optional fields may be omitted. An
unavailable field is recorded as payload.unavailable[field_path] with a stable
reason (not_collected, not_supported, not_exposed, not_applicable, or redacted).
null is not an unavailable marker. A required field cannot be unavailable, and
a field cannot be both present and unavailable.

## Telemetry levels

| Level | Required guarantees | Optional observations |
| --- | --- | --- |
| minimal | tokens/s and memory used | TTFT, acceptance, bandwidth, transfers, cache pressure, stage timings |
| standard | minimal plus TTFT, acceptance, bandwidth, transfers | cache pressure and stage timings |
| deep | standard plus cache pressure and stage timings | none |

## Invalidation and versioning

Changing model_digest, backend_digest, hardware_digest, context_digest, or
concurrency_digest yields model_drift, backend_drift, hardware_drift,
context_drift, or concurrency_drift, respectively, and invalidates the prior
decision before execution.

Only 1.0 is accepted. A major mismatch is rejected; a minor mismatch requires
an explicit migration. Breaking changes bump the major version and additive
changes bump the minor version, each with a migration note. No compatibility
layer or implicit field coercion is defined.

examples.json contains valid telemetry and decision messages. The Python
validator is src/simplicio_fast/contract_surface.py.
