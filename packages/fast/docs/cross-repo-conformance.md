# Cross-repository conformance gate

`src/simplicio_fast/cross_repo.py` is a dependency-free, read-only consumer of
`simplicio.stack-lock/v1`. It does not create a second source of truth. The
stack lock remains owned by the coordinating Loop/Mapper integration and must
contain immutable commits, versions, contract digests and explicit routes.

Validate a lock before preparing a task:

```bash
simplicio-fast-cross-repo validate \
  --file .simplicio/stack-lock.json \
  --profile loop-standalone
```

The command emits `simplicio.fast.cross-repo-receipt/v1`. The receipt is
deterministic for the canonicalized lock and can be attached to a Loop attempt
or a Runtime-backed handoff. It is evidence of compatibility, not evidence that
an effect, source mutation or completion happened.

## Profiles

| Profile | Required members | Fast's role | Runtime |
| --- | --- | --- | --- |
| `loop-standalone` | Mapper, Fast, Dev CLI, Loop | derived projection, bounded context and read-only compute | absent |
| `runtime-backed` | Mapper, Fast, Dev CLI, Loop, Runtime | same derived/read-only role | owns physical effects and policy |

Every member is pinned to a 40-character lowercase commit SHA. A branch name,
tag, `latest`, mutable version or missing artifact digest is not a valid pin.
Contract entries are pinned separately so a healthy package combination cannot
silently consume a different ABI.

## Ownership boundary

| Flow | Producer | Consumer | Authority that remains outside Fast |
| --- | --- | --- | --- |
| canonical context/facts | Mapper | Fast | Mapper owns stable IDs and source facts |
| derived projection/query | Fast | Loop, Agent, Code | source/store remains canonical |
| guarded changeset | Fast | Dev CLI | Dev CLI owns source mutation |
| attempt/slot/lease/completion receipt | Loop | Fast read-only projection | Loop owns progression and completion |
| physical effect/reconciliation | Runtime in full profile | Loop/Fast as consumers | Runtime owns policy/effect |

The validator rejects a route that gives Fast `source-mutation`, `queue`,
`lease`, `completion`, `effect` or `policy` authority. Runtime is forbidden from
the standalone profile rather than being silently treated as available.

## Cross-repo release gate

The receipt should be attached before claiming the following Fast work is
integrated:

- Projection ABI and type registry (#340);
- pinned federation and bounded joins (#341);
- Universal Context Compiler (#345);
- Operations projection (#347);
- embeddable SDK/session surfaces (#348);
- final cross-domain proof and rollout (#349).

The receipt does not close those issues by itself. Installed Python/Rust
conformance, real Mapper handoffs, Dev CLI materialization, Loop standalone
delivery and Runtime-backed effect/reconciliation still require their own
consumer receipts. A missing consumer receipt must be reported as
`UNVERIFIED`, never synthesized by Fast.

## Failure handling

Consumers must stop before context preparation or effect when validation returns
`blocked`. The stable reason codes identify the first boundary failure, including
unpinned commits, duplicate members, missing required contracts, profile mismatch,
unknown repository, or forbidden Fast authority. A new lock is required after a
package, commit, contract, route or profile change.

The JSON schemas in `contracts/` are descriptive machine-readable boundaries;
the Python validator is the executable conformance gate and preserves unknown
future fields only outside the canonical fields it verifies.
