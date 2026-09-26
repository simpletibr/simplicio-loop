# Asolaria ecosystem fixture for Simplicio Canvas

This directory connects the organized public Asolaria repository graph to the
versioned Simplicio ecosystem contract and to the artifact shape that the current
Simplicio Canvas importer can already open.

## Files

- `ecosystem-graph.json` — the authoritative metadata-only fixture for
  `simplicio.ecosystem-graph/v1`. It pins repository revisions, repository URLs,
  access state, roles, typed cross-repository edges, evidence URLs, three external
  research references, and explicit boundaries.
- `canvas-flow.json` — a compatibility projection into the current
  `simplicio-mapper-flow` shape consumed by Canvas 2.13. The pseudo paths are
  visualization roles, not claims that files with those names exist in the source
  repositories.

## Open it in Canvas today

1. Clone and run `wesleysimplicio/simplicio-canvas` locally.
2. Select **Import map**.
3. Choose `canvas-flow.json` from this directory.

The current Canvas importer renders the node paths and edges safely in browser
memory. It does not yet preserve every rich field from `ecosystem-graph.json`.
Native import of the versioned ecosystem contract should retain repository URL,
revision, access, status, evidence kind, edge kind, and boundary metadata.

## Evidence layers kept separate

The fixture deliberately distinguishes:

- source and deterministic test evidence;
- runtime evidence;
- operator-reported and third-seat evidence;
- immutable-head CI evidence;
- repository-reported historical training metrics;
- external research papers;
- architecture/canon;
- unverified live integration.

A repository being visible is not proof that its process is live. A private or
unavailable repository remains visible with its access state. An external paper can
calibrate or motivate an integration without being presented as proof that the
integration has already been built.

## Research connections

- Encrypted quantum cloning is represented as a quantum sibling of the locally
  insufficient / jointly recoverable Path-2 pattern. The Rust recovery crates remain
  classical.
- The nanoparticle matter-wave experiment is represented as an external calibration
  source for the Q-PRISM Talbot-Lau simulator, not as proof of neural quantum control.
- The LLM global-workspace result motivates a capacity-limited visual focus/broadcast
  layer in Canvas, not a consciousness claim.

## Privacy and authority

The fixture contains public metadata and public evidence links only. It contains no
private corpus, raw model weights, keys, device identifiers, PII, or live control
credentials. Importing or rendering the graph grants no runtime, write, mint, device,
or operator authority.
