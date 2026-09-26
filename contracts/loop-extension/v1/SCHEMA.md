<!-- simplicio-contract:begin -->
contract: loop-extension/v1
schema: simplicio.contract-doc/v1
purpose: In-repo foundation for the extension contract requested by issue #557 ("Formalizar contrato de extensões de domínio para loop-oss e loop-marketing").
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.loop-extension/v1` — domain extension manifest (#557)

In-repo foundation for the extension contract requested by issue #557
("Formalizar contrato de extensões de domínio para loop-oss e loop-marketing").
`loop-oss` and `loop-marketing` are separate repos this codebase has no access
to; this contract defines and enforces, from the core side, what a manifest
must look like and how its stage overlays compose — it does not migrate
either external project.

* implementation: `simplicio_loop/extension_manifest.py`
  (`validate_manifest`, `compose_stage_graph`, `load_manifest`)
* schema: [`schema.json`](./schema.json) (JSON Schema draft-07)
* tests: `tests/test_extension_manifest_unit.py`

## Manifest shape

Required: `schema` (const `simplicio.loop-extension/v1`), `extension_id`
(lower_snake identifier), `name`, `version` (semver), `domain`, and
`requires_core` (optional `min_version`/`max_version` semver bounds).
Optional: `capabilities` (`requires`/`provides` string arrays),
`source_adapters`, `context_schemas` (+ `migrations`), `stage_overlays`,
`role_bindings`, `gates`, `effect_handlers`, `resource_classes`,
`receipt_schemas`, `feature_flags`. Every object at every nesting level is
closed (`additionalProperties: false` in the schema, mirrored by
`validate_manifest`'s explicit allowed-field sets) — an unknown field at any
level is a validation error, never silently ignored.

`effect_handlers` must set `idempotent`, `requires_fence_token`, and
`requires_receipt` all to literal `true` — the issue's rule that "efeitos
externos exigem idempotency key, fence token e receipt durável" is enforced
structurally, not left to the extension author's discipline.

## Stage-graph composition (`compose_stage_graph`)

Only four declarative ops exist, matching the issue's list exactly:
`insert_before`, `insert_after` (add a new, non-mandatory stage adjacent to
an existing `hook` stage_id), `wrap` and `refine` (attach behavior/gates to
an existing `hook` stage without replacing it). There is deliberately no
`remove` op — a manifest cannot drop a core `mandatory` stage because the
schema gives it no verb to do so; `validate_manifest` rejects any `op` value
outside the four (e.g. a future/foreign `"remove"`) before composition ever
runs.

`compose_stage_graph(core_stages, extensions)`:

1. Collects every extension's `stage_overlays` ops and sorts them by
   `(order, extension_id, declaration_index)` — composition is byte-identical
   regardless of the order `extensions` is passed in (discovery order is not
   trusted).
2. Applies `insert_before`/`insert_after` by splicing a new stage next to its
   hook; `insert_after` auto-adds the hook to the new stage's `depends_on`.
3. Applies `wrap`/`refine` gate overrides only if the new severity rank
   (`off < warn < block < fail_closed`) is `>=` the hook stage's current rank
   for that `gate_id` — any attempt to lower it is rejected with "cannot
   weaken gate".
4. Runs cycle detection (DFS, white/gray/black) over the composed
   `depends_on` graph.
5. Confirms every core stage flagged `mandatory: true` is still present in
   the composed stage_order (structurally guaranteed by the op set, checked
   again defensively here).

Returns `{"ok": bool, "errors": [...], "stages": [...]}` — callers gate on
`ok` rather than an exception, so a batch of extensions can be validated
together and every conflict surfaced at once.

## Not covered by this slice

This is the schema/loader/composer only. Out of reach from this repo:
Python SDK packaging for OSS / TypeScript bridge for Marketing, the ADR,
migrating a real OSS/Marketing fixture, conformance-test installation from
published packages, cold-start/p50/p95 benchmarking, and the receipt-embedded
composed-graph hash — see the issue body's full plan for the remaining scope
(items that require the sibling `simplicio-loop-oss`/`simplicio-loop-marketing`
repos this session cannot touch).
