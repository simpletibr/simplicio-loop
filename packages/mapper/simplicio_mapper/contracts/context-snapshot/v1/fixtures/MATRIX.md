# Fixture matrix

The files under `valid/` are canonical v1 examples: `minimal` is partial (1
node, 0 edges), `graph-multi-scale` has 5 nodes/3 edges, and `full`/`latest`
have 7 nodes/4 edges. `delta-revision` is a distinct r2 receipt with 7 nodes/4
edges. The
files under `invalid/` are negative fixtures. `oversized-representable.json`
is intentionally declarative: the asset checker materializes the 4,097th
element without committing a denial-of-service-sized fixture.

Invalid fixtures are evaluated by `scripts/check_context_contract_assets.py`.
They are not accepted as normal contract payloads.

Run the same local conformance gate used by the example consumer with:

```bash
python3 scripts/check_context_contract_assets.py
python3 -m unittest tests.python.test_context_contract_assets
python3 scripts/check_context_contract_assets.py --print
git diff -- contracts/context-snapshot/v1/contract-manifest.json
```

The contract has only v1 fixtures today. N/N-1 describes the future v2
migration window, when v1 remains published as N-1; it does not imply an
unpublished v0 compatibility fixture.
