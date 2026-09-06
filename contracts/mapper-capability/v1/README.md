# Mapper language/capability contract — `v1`

Issue #617 tracks parity independently for every supported language and every
advertised capability.  The catalog is intentionally broader than the native
Rust core: native support is selected per `(language, capability)` and every
other route remains the canonical Python reference implementation.

- `matrix.json` is the fail-closed promotion matrix.
- `fixture-matrix.json` contains one deterministic source fixture for every
  priority-stack/language/capability case.
- `differential-report.json` records the current proof or explicit shadow/
  missing state for each case.

Runtime artifacts carry a bounded `capability_coverage` receipt on
`project-map.json`; its per-language groups preserve each capability's status,
backend, route status and evidence without duplicating a large matrix into
every artifact. Fast handoffs copy that receipt into their capability section.

`native_promotion.<language>.native_default` may be `true` only when every
required capability for that language is `NATIVE_PARITY`.  A missing or
mismatched row blocks promotion; discovery facts are never dropped because a
native kernel is incomplete.

## Semantic resolution

C#/Razor call and symbol resolution may use a Roslyn-compatible deterministic
service configured with `SIMPLICIO_MAPPER_SEMANTIC_COMMAND`.  Its protocol is
`simplicio.mapper-semantic-{request,result}/v1`, documented in
`simplicio_mapper/semantic_resolution.py`.  Without the service, regex/name
lookup is retained only as `heuristic`/`inferred` evidence.

SQL objects are discovered as symbols (`table`, `view`, `function`, and
`procedure`).  SQL is deliberately excluded from the call-graph language set;
the Mapper does not invent SQL call sites.
