# ContextGraph public contract — `simplicio.context-graph/v1`

Mapper owns the public ContextGraph vocabulary. Consumers use the contract
projection, not parser or storage details.

## Required public identity

`schema` and integer `version` identify the contract. `repository_id` identifies
the repository, `generation` identifies the mapped revision, and `digest` is the
SHA-256 of the canonical contract body without `digest`. `stable_ids.nodes` and
`stable_ids.edges` are sorted logical IDs; relations are exposed as sorted
`{id, kind, source, target}` records.

`canonical_api` and `fast-handoff` are the preferred seams. File parsing,
artifact layout, cache paths, mmap offsets, and Rust/Python implementation
choices are not public behavior.

## Parity fixture

`fixtures/parity.json` covers empty scans, inspect projections, ask projections,
stable IDs, relations, and generation changes. The local contract suite runs
Python and Node against this fixture and reports Rust as `skipped` when the
optional accelerator is not installed. A divergence includes channel and
version provenance.

Run locally:

```bash
python -m unittest tests.python.test_context_graph_contract
node bin/context-graph-contract.js contracts/context-graph/v1/fixtures/parity.json
```
