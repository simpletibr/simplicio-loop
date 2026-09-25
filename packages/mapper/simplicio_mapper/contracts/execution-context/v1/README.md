# Execution Context v1

`simplicio.execution-context/v1` is the canonical, deterministic envelope for
one task. Consumers should pass its extractive source spans to an LLM as
evidence and use `expansion_handle` values to request omitted content. They
must not treat relevance or precedent confidence as proof of correctness.

The v1 shape is closed: producers emit only properties declared by the
published schema. Any shape change must update the contract deliberately; a
breaking change requires a new schema id. Consumers should reject unknown
major schema ids and fall back to the unchanged
`simplicio.map-handoff/v1` context pack.

Secret-shaped paths, binary files, paths outside the authorized repository and
credential-shaped values are excluded or redacted at the envelope boundary.
Every exclusion appears in `redactions`; every budget removal appears in
`omissions`. `abstention`, `needs_broader_context` and `next_queries` are
authoritative—consumers must not silently promote an insufficient envelope.

Rollback is operationally simple: omit `handoff --execution-context`. The
legacy handoff shape remains unchanged when the flag is absent.
