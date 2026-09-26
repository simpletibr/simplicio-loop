# ECC advisory integration

The Loop integration is intentionally selective. It does not install or execute the ECC hook,
MCP, memory, or autonomous-loop surfaces.

## Enable

Set the ECC checkout and opt in:

```bash
export SIMPLICIO_ECC_ROOT=/path/to/ECC
export SIMPLICIO_ECC_ENABLED=1
simplicio-loop ecc doctor --repo .
```

The checkout must resolve to the pinned ECC commit
`0c1d7be9a750627fb2a6534c78a998cc46d03f9c` and the canonical Simplicio manifest digest.

During a Loop run:

1. Loop records a bounded provenance-only admission at
   `.simplicio-loop/loop-runs/<run-id>/ecc-doctor.json`.
2. Mapper/Dev CLI keep ownership of the ECC pack and prompt context.
3. Dev CLI consumes the bounded advisory pack and returns only
   `simplicio.ecc-guidance-ref/v1` hashes in the operator receipt.
4. Loop keeps STOP, mutation authority, receipts, verification, and convergence.

The default is fail-open and disabled. Set `SIMPLICIO_ECC_REQUIRED=1` to fail closed when
provenance or the verified hash-only reference is unavailable.
