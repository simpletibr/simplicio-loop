# Issue #349 security review slice

This slice defines `simplicio.fast.context-security/v1` and the consumer-side
`validate_context_packet()` gate. It validates the generated packet's schema,
facts-only authority, instruction boundary, item provenance, truncation shape,
JSON encoding and absence of mmap/private layout fields. Retrieved text stays
opaque data; the validator never grants tool or model authority.

Local adversarial coverage includes forged authority/instruction metadata,
trusted-for-instruction escalation, private layout injection, future packet
schema and missing provenance. The result is a derived read-only receipt.

This is not a final #349 closure claim. Installed consumer E2E, crash/recovery,
resource benchmark, Python/Rust parity and rollout/rollback receipts remain
external or broader gates.
