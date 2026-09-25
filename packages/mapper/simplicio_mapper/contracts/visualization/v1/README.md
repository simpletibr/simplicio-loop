# Visualization bundle v1

`visualization-bundle.json` is a renderer-neutral projection of mapper
artifacts. Consumers must use IDs and typed edges, not Mermaid or prose.

Compatibility: v1 consumers MUST ignore unknown fields. Additive fields are
backward compatible; changing/removing required fields or changing ID
semantics requires `v2` and a new schema directory. `generated_at` is
intentionally informational and should be replaced by a fixed value in golden
fixtures.
