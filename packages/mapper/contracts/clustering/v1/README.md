# Clustering metrics contract v1 (issue #192)

`simplicio.clustering-metrics/v1` is a deterministic, renderer-neutral
projection of mapper files and call/import edges. It is embedded in the
visualization bundle as `clustering` and emitted by `visualize` as
`.simplicio/clustering-metrics.json`.

Clusters are strategy-scoped (`workspace`, `directory`, `package`,
`namespace`, `domain`, `layer`, `flow`, and `graph-community`) and can
overlap. Density is internal edges over possible file-to-file edges; cohesion
is internal over incident edges; coupling is external over incident edges.
Layout hints contain only lane/order, importance, and collapse recommendations;
consumers choose coordinates. Thresholds and hint settings are copied into
`config` and `provenance.config` for reproducibility.
