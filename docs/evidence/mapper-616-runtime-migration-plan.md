# Mapper #616 Runtime migration plan

Status: **sequenced; not claimed as complete by this repository PR**.

The Runtime repository is a separate workspace and is not mutated by this
Mapper PR. The reusable core is extracted here first so the cross-repository
change has a stable, tested dependency and a measured handoff.

## Measured baseline

At the Mapper #616 implementation revision, the Runtime repository contains:

| Path | Measured lines | Current responsibility |
|---|---:|---|
| `crates/simplicio-native-mapper/src/lib.rs` | 2,178 | semantic mapper kernels plus unrelated scaffold/effect/fallback contracts |
| `src/native_mapper_adapter.rs` | 351 | Runtime-owned filesystem lifecycle and receipt boundary |

Measurement command:

```bash
wc -l \
  ../simplicio-runtime/crates/simplicio-native-mapper/src/lib.rs \
  ../simplicio-runtime/src/native_mapper_adapter.rs
```

The target of the migration is to remove only the duplicated semantic kernel
logic from the first file. Filesystem traversal, receipt construction, auth,
effects, fallback policy, and Runtime lifecycle stay in Runtime.

## Sequenced change

1. Publish or consume the versioned `simplicio-mapper-core` crate from the
   Runtime workspace, pinned to the Mapper release and core version.
2. Add a Runtime-owned thin adapter that converts its source-generation records
   to `simplicio.mapper-core-request/v1` and calls `simplicio_mapper_core`.
3. Run the Mapper differential fixture set from
   `artifacts/mapper-differential.json` in Runtime CI before deleting the
   duplicated parser/hash/canonicalization functions.
4. Delete the duplicated semantic functions and keep the existing Runtime
   lifecycle/effect modules outside the core dependency.
5. Record the Runtime commit, core version, fixture digest, and before/after
   measured line counts in the Runtime migration PR.

The local `rust/runtime-adapter` is an executable seam and proof that a
Runtime-shaped adapter calls the same core. It does not claim that the
separate Runtime product has already cut over.
