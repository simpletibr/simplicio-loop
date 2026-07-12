# ContextSnapshot / ContextGraph contract — `v1`

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
(everything except `snapshot_id`, `generated_at`, `producer`, `schema_version`):
`sha256(json.dumps(body, sort_keys=True, separators=(",",":"), ensure_ascii=False))`.
Same inputs → same id; one changed byte → different id. `needs_broader_context`
is derived from the `omissions` list and never enters the hash.

## Multi-scale graph

Three node scales, each derivable from existing mapper artifacts:

- **micro** — `symbol-index` symbols (entrypoint of attention).
- **meso** — `call-graph` invocations + `symbol-index` (call-chain fabric).
- **macro** — `architecture-inventory` modules/layers (structural skeleton).

Every node and edge carries:

- `content_hash` — SHA-256 of its canonical serialization.
- a reversible `source` / `source_handle` pointing back to the originating
  artifact file (+ `line` / `span` when known).

## Fixtures

- `fixtures/latest/` — generated from the real `python-minimal` mapper run
  (4 files, 4 symbols, 5 call edges → 15 graph nodes, 9 edges).
- `fixtures/minimum/` — hand-authored tiny valid example (4 nodes, 2 edges)
  for easy Rust consumption in the Simplicio Runtime (parent issue #3134).

Regenerate with:

```bash
python3 scripts/regen_context_snapshot_fixtures.py update
```

## CLI

```bash
simplicio-mapper snapshot build  --root <repo> [--out .simplicio]
simplicio-mapper snapshot validate <path> [<path> ...]
simplicio-mapper snapshot summary --root <repo> [--out .simplicio]
```
