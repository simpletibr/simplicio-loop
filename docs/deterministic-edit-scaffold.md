# Deterministic edit and scaffold boundary

Issue #691 makes the Dev CLI the semantic owner of deterministic source
transforms. Mapper supplies observation provenance; Dev CLI plans and evaluates
the transform; Runtime authorizes and governs the filesystem effect.

## Edit kernel

`simplicio.mechanical_edit` exposes the pure `TextEdit` primitive and
`apply_text_edits(files, edits)`. A `TextEdit` has one portable relative path,
one non-empty anchor, one replacement, and an optional SHA-256 precondition.
The kernel:

- normalizes `/` and `\\` paths and rejects absolute paths, drives, traversal,
  empty segments, and control characters;
- requires exactly one anchor occurrence;
- verifies expected hashes before changing a staged copy;
- never mutates the input mapping and never partially returns a batch;
- emits a byte-stable `simplicio.dev-cli.edit-receipt/v1` batch receipt.

`build_edit_plan()` is planning-only. It requires a canonical
`simplicio.mapper-binding/v1` containing the repository id, Mapper generation,
source tree id, and exact UTF-8 source-byte hashes. Every operation is copied
with its expected source hash, so a plan cannot be created for an unbound
target; newline normalization is not allowed to hide Mapper/source drift.

The public `simplicio edit` command recognizes
`simplicio.dev-cli.edit-plan/v1` as the canonical Dev CLI plan. It does not
send that plan to the legacy native Mapper edit vocabulary. Runtime adapters
can reuse the same kernel at their effect boundary instead of implementing a
second anchor engine.

The versioned edit receipt includes the binding and per-file before/after
hashes. Its `mapper_refresh` member is `not_required` for a no-op and
`required` whenever effective source bytes change. Dev CLI does not invent a
new Mapper generation; the coordinator remaps and supplies the next canonical
generation after an applied effect.

## Scaffold planner

`plan_scaffold()` is pure and owns the
`simplicio.dev-cli.scaffold-plan/v1` schema. It currently supports:

- `rust-crate`;
- `rust-binary`;
- `python-package`;
- `node-package`.

The output is deterministic, includes a plan digest, carries the same Mapper
binding, and marks `runtime_authorization_required`. Unsupported kinds and
unsafe names return typed blocked outcomes rather than writing anything.
`scaffold_receipt()` serializes the corresponding
`simplicio.dev-cli.scaffold-receipt/v1` result without performing an effect.

The JSON schemas live under `contracts/` and are Dev CLI-owned. Runtime may
authorize and apply their `create_file` operations through its effect and
rollback policy; Mapper remains an observation provider only.

## Conflict vocabulary

Canonical edit/scaffold boundaries use typed outcomes:

`missing_target`, `missing_anchor`, `ambiguous_anchor`, `hash_drift`,
`invalid_path`, and `unsupported_scaffold`.

No conflict is converted into a best-effort edit. A conflict is returned
before filesystem mutation, and callers must re-map/re-plan when the Mapper
generation or source hashes no longer describe the workspace.
