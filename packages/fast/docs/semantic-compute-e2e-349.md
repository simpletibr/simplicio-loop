# Synthetic Semantic Compute E2E

`tests/test_semantic_compute_e2e_349.py` composes the current typed Code,
Knowledge and Operations projections with the pinned federation, deterministic
semantic diff and universal context compiler. It verifies handle-only context,
scope isolation, stable federation generation, update detection and absence of
mmap layout fields.

This is a local synthetic fixture and is intentionally not a rollout claim. A
real #349 receipt still requires Mapper/Runtime/Loop/Dev CLI sources, installed
Rust paths, cross-repository contract breakage, security/adversarial cases and
cold/warm/resource measurements. Rollout state is fail-closed: invalid modes,
generations, rollback requests without a reason, and forged/corrupt state files
are rejected with typed reason codes.
