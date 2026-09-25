# Asolaria → Simplicio Mapper → Simplicio Canvas

This integration uses Simplicio's existing local-first and evidence-first
contracts to visualize a real multi-repository Asolaria system without
redistributing private source or flattening every claim into “live”.

## Flow

```text
public repository map + pinned revisions + public receipts
  -> simplicio.ecosystem-graph/v1
  -> optional simplicio-mapper-flow compatibility projection
  -> Simplicio Canvas ecosystem view
  -> static/runtime/evidence overlays remain separate
```

The authoritative fixture is:

```text
contracts/ecosystem/v1/fixtures/asolaria-ecosystem/ecosystem-graph.json
```

The current Canvas-compatible projection is:

```text
contracts/ecosystem/v1/fixtures/asolaria-ecosystem/canvas-flow.json
```

## Why this fits Canvas

Canvas already has:

- a versioned renderer-neutral graph;
- multi-repository manifests with revision, branch, dirty and access state;
- typed cross-repository edges;
- explicit unavailable repositories;
- distinct static, runtime and AI evidence;
- local-only telemetry;
- policy-as-code and SARIF;
- checksummed recovery and graph-diff/time-travel contracts.

The ecosystem graph adds the missing public transport shape for:

- canonical repository URLs;
- immutable revisions;
- richer relationship types;
- evidence kind and status;
- external research references;
- explicit claim boundaries.

## Asolaria systems represented

The fixture covers the public path from the pre-Asolaria healthcare GNNs
through the byte-identical sidecar, later trained graph planes, BigPickle,
emitter, dispatcher, Hermes fleet, post-trigger stage, white rooms, cube mint,
Path 1, Path 2, DBBH→DBWH, Q-PRISM watcher harness, formula ownership, and
N-Nest inverse verification.

It also includes the Simplicio Canvas, Mapper, Loop and private Runtime nodes
with their actual access states.

## Research connections

### Encrypted cloning

The encrypted-cloning paper is attached as evidence for a *structural quantum
sibling* of Path 2: locally insufficient branches, globally preserved
information, selected recovery and a consumed quantum key. The graph boundary
states that the current CRT/BEHCS implementation is classical.

### Nanoparticle matter-wave experiment

The Nature experiment is attached as an external calibration reference for the
Q-PRISM Talbot–Lau simulator. It is not presented as evidence that the recovery
fabric controls a physical wavefunction.

### LLM global workspace

The global-workspace study motivates a capacity-limited evidence-focus layer in
Canvas: a small selected set can be visually broadcast across repository,
formula, runtime and proof views. It is not a consciousness claim.

## Native Canvas follow-up

The compatibility projection works with the current importer, but it necessarily
loses rich fields. Native `simplicio.ecosystem-graph/v1` support should:

1. render repository nodes directly rather than converting them to synthetic
   file paths;
2. preserve URL, revision, branch, access, role and status;
3. preserve typed edge kinds and labels;
4. show evidence cards with source/runtime/CI/third-seat/paper distinctions;
5. show boundaries in the inspector;
6. leave unavailable/private repositories visible but non-openable;
7. use collision-resistant graph identities for large ecosystems;
8. preserve v1 Mapper-flow import compatibility.

## Security and authority

This fixture is public metadata only. It contains no keys, private corpus, raw
model bodies, PII or device credentials. Rendering an edge does not execute the
edge, authorize a route, mint an agent, or make an unverified integration live.
