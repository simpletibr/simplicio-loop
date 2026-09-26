# ContextSnapshot / ContextGraph contract — `v1`

The Mapper is the exclusive producer owner. Contract governance, byte-level
canonicalization, reversible source handles, N/N-1 policy, v2 bump rules,
future-version fail-closed behavior, and consumer migration are in
[CONTRACT.md](CONTRACT.md). The deterministic, pinned conformance-kit index is
`contract-manifest.json`; check it with
`python3 scripts/check_context_contract_assets.py`.

Local CI-equivalent commands (no Actions required):

```bash
python3 scripts/check_context_contract_assets.py
python3 -m unittest tests.python.test_context_contract_assets
python3 scripts/check_context_contract_assets.py --print
git diff -- contracts/context-snapshot/v1/contract-manifest.json
```

Issue #208 foundation slice ("Schema e identidade"). Defines the canonical
observer output of the Mapper: a content-addressed, versioned,
fidelity-proven `ContextSnapshot` wrapping a multi-scale `ContextGraph`.

## Schemas

| Schema id | File | Purpose |
|---|---|---|
| `simplicio.context-snapshot/v1` | `schemas/context-snapshot.schema.json` | Top-level snapshot envelope |
| `simplicio.context-graph/v1` | `schemas/context-graph.schema.json` | Multi-scale graph (embedded in the snapshot) |

## Deviation from the mapper-artifacts convention

The `mapper-artifacts/v1` README states its schemas are **not** packaged in the
wheel. This family intentionally **overrides** that: issue #208 AC requires
"Wheel e sdist incluem schemas; clean install consegue validá-los". Therefore:

- `pyproject.toml` force-includes `contracts/context-snapshot` into
  `simplicio_mapper/contracts/context-snapshot` (both wheel and sdist).
- `simplicio_mapper.context_snapshot.from_package()` and
  `simplicio_mapper.contract.load_schema()` resolve these schemas from the
  installed-package dir, falling back to the repo source dir when running from
  a checkout.

## Identity (content addressing)

`snapshot_id` is a SHA-256 of the canonical serialization of the snapshot body
(everything except `snapshot_id` and `generated_at`):
`sha256(json.dumps(body, sort_keys=True, separators=(",",":"), ensure_ascii=False))`.
Same inputs → same id; one changed byte → different id. `producer`,
`schema_version`, and `needs_broader_context` are deliberately addressable.

## Multi-scale graph

Three node scales, each derivable from existing mapper artifacts:

- **micro** — `symbol-index` symbols (entrypoint of attention).
- **meso** — `call-graph` invocations + `symbol-index` (call-chain fabric).
- **macro** — `architecture-inventory` modules/layers (structural skeleton).

Every node and edge carries:

- `content_hash` — SHA-256 of its canonical serialization.
- a reversible `source` / `source_handle` pointing back to the originating
  artifact file (+ `line` / `span` when known).

In v1 an edge endpoint may refer to an external or not-yet-indexed logical ID.
Its edge ID, source handle, and content hash remain validated; consumers must
not infer that every endpoint has a local node record.

## Fixtures

- `fixtures/minimum/` mirrors `valid/minimal`: a partial receipt with 1 node
  and 0 edges.
- `fixtures/latest/` mirrors `valid/full`: 7 graph nodes and 4 edges.
- `valid/graph-multi-scale/` has 5 nodes and 3 edges; `valid/delta-revision/`
  has 7 nodes and 4 edges.

The checked fixtures are golden assets. Do not use the old regeneration command
as evidence of conformance; review a deterministic golden change with:

```bash
python3 scripts/check_context_contract_assets.py --print
git diff -- contracts/context-snapshot/v1/contract-manifest.json
```

## CLI

```bash
simplicio-mapper snapshot build  --root <repo> [--out .simplicio-loop]
simplicio-mapper snapshot validate <path> [<path> ...]
simplicio-mapper snapshot summary --root <repo> [--out .simplicio-loop]
```
