# Simplicio cross-repository contract registry

This registry is the versioned public boundary between `simplicio-mapper`,
`simplicio-dev-cli`, `simplicio-loop` and the optional
`simplicio-runtime` executor.  It does not replace legacy contracts; it gives
new integrations one canonical ID, owner and compatibility rule.

## Contract identity

Every envelope contains `schema`, `schema_version`, `contract_id`,
`generation`, `attempt`, `fence`, `idempotency_key`, `content_hash`,
`producer`, `created_at` and `payload`.  `content_hash` is
`sha256:` followed by SHA-256 of canonical JSON (`sort_keys=true`, compact
separators, UTF-8).  The validator rejects a stale generation/fence or a hash
that does not match the payload with stable reason codes.

## Compatibility

The registry uses semantic versions with same-major additive compatibility.
Minor and patch releases may add optional fields.  Removing or renaming a
required field, changing a type or hash rule, exposing an implementation detail,
or transferring ownership requires a new major schema version and a new
registry entry. Consumers must ignore unknown additive fields and must fail
closed on a major-version mismatch.

## Ownership matrix

| Contract | Owner | Producers | Consumers |
| --- | --- | --- | --- |
| `simplicio.context-snapshot/v1` | mapper | mapper | dev-cli, loop |
| `simplicio.context-delta/v1` | mapper | mapper | dev-cli, loop |
| `simplicio.capability-request/v1` | loop | loop, dev-cli | runtime, loop |
| `simplicio.change-set/v1` | dev-cli | dev-cli | loop, runtime |
| `simplicio.verification-plan/v1` | loop | loop, dev-cli | loop, runtime |
| `simplicio.effect-receipt/v1` | runtime | runtime, dev-cli | loop, dev-cli |
| `simplicio.stage-receipt/v1` | loop | loop | runtime, dev-cli |
| `simplicio.run-journal/v1` | loop | loop | runtime, dev-cli, mapper |

The owner is the only component allowed to change the semantic meaning of a
contract. A producer may populate a contract but cannot create a competing
schema ID. Storage offsets, posting-list positions and index storage
handles are deliberately not public fields.

## Validation

```python
from simplicio_loop.contract_registry import load_registry

registry = load_registry()
envelope = registry.make_envelope(
    "simplicio.context-snapshot/v1",
    {"snapshot_id": "snap-1", "source": "git", "files": ["README.md"]},
    generation=3, attempt=1, fence="lease-3", idempotency_key="snap-1:3",
    producer="simplicio-mapper",
)
registry.validate(envelope, expected_generation=3, expected_fence="lease-3")
```

For cross-repository conformance, copy `registry.json`, the ten schemas and
the golden fixtures into the consumer repository and run the same validator.
The fixture set intentionally includes invalid hash/fence/internal-field
examples so a consumer cannot silently downgrade a rejected receipt.
