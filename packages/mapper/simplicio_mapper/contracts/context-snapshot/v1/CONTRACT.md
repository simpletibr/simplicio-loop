# Mapper Context contract governance — v1

`wesleysimplicio/simplicio-mapper` is the sole producer owner of
`simplicio.context-snapshot/v1` and `simplicio.context-graph/v1`. A consumer
may validate, store, and reference these payloads; it must not mint either ID
with a divergent shape. The pinned `contract-manifest.json` is the portable
conformance kit: it identifies owner, schemas, fixtures, limits, and their
SHA-256 digests.

## Canonical identity

Addressable bytes are UTF-8 JSON encoded with `ensure_ascii=false`, sorted
object keys, and separators `,` and `:`. The snapshot digest is SHA-256 of the
addressable body after excluding only `snapshot_id` and `generated_at`.
`producer`, `schema_version`, and `needs_broader_context` therefore
participate in the digest. Paths use `/`, are
repository-relative, and never resolve `..` or an absolute path. A source
handle (`file` plus line or span where known) is reversible: it identifies the
mapper artifact/source to re-open, never a copied source blob.

## Compatibility and migration

v1 accepts v1 only. A future schema/version is rejected fail-closed, rather
than guessed. This repository currently publishes only v1 fixtures: N/N-1 is
the rollout policy for a future v2, not a claim that a v0 fixture exists.
During a v2 rollout the published kit carries v1 as N-1 until the migration
window and consumer evidence are complete. Additive changes are
allowed only when every v1 producer/consumer agrees through the pinned golden
manifest; a changed required field, canonical byte rule, semantic invariant,
or limit requires v2. Deprecation publishes both kits, migration examples, and
an explicit removal date; it never silently rewrites a v1 payload.

## Consumer migration

Consumers (including Dev CLI) must remove copied snapshot models, pin this
manifest, verify schema/fixture digests, validate a received schema ID and
version before use, and fail closed for an incompatible shape. The
`invalid/dev-cli-incompatible` fixture is the regression proof for the former
non-canonical shape. Run `python3 scripts/check_context_contract_assets.py`
in CI; compare `--print` output with the committed manifest to review any
intentional golden diff.

Stable consumer APIs are `validate_context_payload`,
`validate_context_graph`, and `validate_context_file`. They return the
`simplicio.context-conformance-report/v1` envelope with `valid` and structured
`reason_codes`; CLI validation exits 0 for valid input and 1 otherwise.
`source_root` optionally proves a handle is reversible under a local root.
Inputs are bounded at 16 MiB, depth 64, 100,000 nodes, 200,000 edges, and
4,096 source paths. No external endpoint is contacted by validation; the wheel
uses only the packaged contract and Python stdlib for this path.

Migration tracking: [Dev CLI #255](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/255)
and [Agent #498](https://github.com/wesleysimplicio/simplicio-agent/issues/498).
