# ContextGraph public contract — `simplicio.context-graph/v1`

Mapper owns the public ContextGraph vocabulary. Consumers use the contract
projection, not parser or storage details.

## Required public identity

`schema` and integer `version` identify the contract. `repository_id` identifies
the repository, `generation` identifies the mapped revision, and `digest` is the
SHA-256 of the canonical contract body without `digest`. `stable_ids.nodes` and
`stable_ids.edges` are sorted logical IDs; relations are exposed as sorted
`{id, kind, source, target}` records. Mapper call/import relations additionally
carry `relation_id`, `evidence_class`, `resolution_status`, provenance and
candidate targets when present. `relation_coverage` is carried when the graph
has bounded, ambiguous or unknown call-graph evidence.

`canonical_api` is the preferred seam. File parsing,
artifact layout, cache paths, mmap offsets, and Rust/Python implementation
choices are not public behavior.

## Compatibility and fail-closed validation

The supported schema family is `simplicio.context-graph-contract/v1`: the
unqualified v1 ID and additive minor IDs such as `/v1.1` are readable when all
v1 required fields and invariants remain valid. Unknown majors are rejected
before nodes or relations are exposed. `validate_public_contract` returns
`valid`, stable `reason` and `path` fields, and an actionable `message`; major
mismatches also identify the received and supported schema families.

`fixtures/compatibility.json` is the versioned golden matrix for supported v1,
additive same-major input, unknown majors, version, repository identity,
generation, stable IDs and digest failures. Python, Node and the optional Rust
accelerator evaluate the same expected `valid`/`reason`/`path` projection.

## Parity fixture

`fixtures/parity.json` covers empty scans, inspect projections, ask projections,
stable IDs, relations, and generation changes. The local contract suite runs
Python and Node against this fixture and reports Rust as `skipped` when the
optional accelerator is not installed. A divergence includes channel and
version provenance.

Run locally:

```bash
python -m unittest tests.python.test_context_graph_contract
node bin/context-graph-contract.js contracts/context-graph/v1/fixtures/parity.json contracts/context-graph/v1/fixtures/compatibility.json
cargo test --manifest-path rust/Cargo.toml context_graph_contract_fixture_matches_public_diagnostics
```
