# Ecosystem contract — `v1` (issue #164)

Extends `contracts/mapper-artifacts/v1/` (issue #157, mapper-only artifacts)
with cross-repository payloads that flow through the Simplicio ecosystem
outside `simplicio-mapper` itself:

| Payload | Produced by | Schema id | Schema file |
|---|---|---|---|
| Autonomous loop execution / run-journal / task-anchor record | `simplicio-loop` (`scripts/loop_journal.py`, `scripts/task_anchor.py`) | `simplicio.loop-execution/v1` | `schemas/loop-execution.schema.json` |
| 6-layer execute/deterministic_edit contract record | `simplicio-dev-cli` | `simplicio.executor-contract/v1` | `schemas/executor-contract.schema.json` |
| Renderer-neutral multi-repository graph with pinned revisions, typed edges, evidence and boundaries | Mapper/integration producers; consumed by Canvas and other graph tools | `simplicio.ecosystem-graph/v1` | `schemas/ecosystem-graph.schema.json` |

## Ownership and honesty

`loop-execution` and `executor-contract` remain vendored copies of shapes owned
by separate repositories. The owning producer is the source of truth. Breaking
changes require a new `contracts/ecosystem/v2/` directory rather than editing
`v1` in place.

The ecosystem graph is intentionally a generic transport contract rather than a
hard-coded application model. Its producers own the truth of each repository,
edge and evidence record. Consumers must preserve access, revision, status,
evidence kind and boundary metadata instead of promoting every visible node to
live runtime truth.

The committed Asolaria fixture is public metadata and public evidence links only.
It is not a live import of private repositories, private corpora, keys, model
bodies or device state. Its separate `canvas-flow.json` is a compatibility
projection for the current Canvas importer; the richer `ecosystem-graph.json`
remains the authoritative fixture.

## Cross-repository sync convention

1. The repository that owns a payload is its source of truth.
2. When an owner changes a payload shape, update the matching ecosystem schema
   in the same session. Breaking changes create `v2`.
3. `scripts/validate_ecosystem_contracts.py` is dependency-free and vendorable.
4. `scripts/cross_repo_conformance.py` remains the live check for producer and
   consumer compatibility where those repositories are available.
5. A consumer that cannot see a private repository records its access state;
   lack of visibility is not a refutation and is not a license to invent data.

## Layout

```text
contracts/ecosystem/v1/
  README.md
  schemas/
    loop-execution.schema.json
    executor-contract.schema.json
    ecosystem-graph.schema.json
  fixtures/
    python-task/
      execution.json
      executor.json
    node-task/
      execution.json
      executor.json
    mixed-task/
      execution.json
      executor.json
    asolaria-ecosystem/
      ecosystem-graph.json    # authoritative versioned public metadata graph
      canvas-flow.json        # compatibility projection for Canvas 2.13
      README.md
```

The task fixtures are illustrative shape fixtures for external producer payloads.
The Asolaria ecosystem fixture pins public repository revisions and evidence URLs,
but it does not redistribute repository source.

## Schema format

Same deliberately small JSON-Schema subset as
`contracts/mapper-artifacts/v1/`: `type` (including `["string", "null"]`
unions), `required`, `properties`, `items`, `enum`, `minItems`.
`additionalProperties` is always implicitly allowed. See
`simplicio_mapper/contract.py` for the validator engine reused here, and
`scripts/validate_ecosystem_contracts.py` for the standalone/vendorable copy.

## Validating fixtures

From within this repo:

```bash
# via the mapper CLI (wraps mapper-artifacts/v1 and ecosystem/v1)
python -m simplicio_mapper.cli doctor --contracts

# standalone, dependency-free validator
python3 scripts/validate_ecosystem_contracts.py
python3 scripts/validate_ecosystem_contracts.py \
  contracts/ecosystem/v1/fixtures/asolaria-ecosystem/ecosystem-graph.json
```

Both exit `0` when every recognized fixture validates against its own `schema`
field, non-zero with an actionable field path otherwise. Files without a schema
field, including the Canvas compatibility projection, are skipped rather than
misrepresented as validated contract payloads.

## How downstream repositories should consume this

1. Vendor the schema(s) the consumer needs and the standalone validator, or
   consume them from a pinned mapper revision.
2. Keep evidence links commit-pinned when they prove exact bytes; use default-
   branch links only for living navigation.
3. Preserve repository access and status when a repo is unavailable.
4. Preserve typed edge semantics rather than flattening every relationship into
   a generic dependency.
5. Keep static, runtime, CI, third-seat, operator, paper and documentation
   evidence distinct.
6. Render explicit boundaries. A paper may motivate or calibrate a system
   without proving that the downstream integration is physically deployed.
7. When the contract bumps to `v2`, retain `v1` schemas and fixtures so consumers
   migrate on their own schedule.

## Current Canvas integration

The current Canvas parser can safely open `canvas-flow.json`. Native
`ecosystem-graph/v1` support should retain repository URLs, immutable revisions,
access states, typed cross-repository relationships, evidence provenance and
boundaries directly instead of rebuilding the graph only from synthetic paths.
