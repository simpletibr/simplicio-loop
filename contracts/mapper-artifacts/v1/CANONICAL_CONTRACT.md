# Canonical Mapper artifact contract — v1 (#614)

This directory is the machine-readable source of truth for the five public
Mapper artifacts. The Python Mapper is the reference producer until a backend
passes the differential fixture suite.

## Public schema envelope

Each artifact keeps its existing v1 fields and MUST additionally contain
`producer`, validated by `schemas/producer-metadata.schema.json`:

| Field | Type | Semantics |
|---|---|---|
| `component` | string | Always `simplicio-mapper`. |
| `version` | string | Mapper distribution version that produced the payload. |
| `backend` | string | `python` for the canonical producer. An uncertified backend MUST NOT use a public v1 id. |
| `schema_version` | string | Contract major, currently `v1`; this is independent of the distribution version. |
| `repository_id` | string | `sha256:` id derived from the repository remote, or the local Git/filesystem identity when no remote exists. |
| `source_generation` | object | `{kind, revision, dirty}`. `revision` is the Git `HEAD` when available; `dirty` includes staged, unstaged and untracked changes. |
| `capability_coverage` | object | One of `full`, `partial`, `empty` or `unsupported` for `files`, `symbols`, `relationships`, `precedent` and `architecture`. |
| `degraded_paths` | string[] | Sorted paths whose observation was degraded. The prefix is a capability (`files:`) or metadata area (`metadata:`). |
| `omitted_paths` | string[] | Sorted intentionally omitted paths. Prefixes identify the reason: `files:<path>` for a large file, `generated:<directory>` for generated output, or `symlink:<path>` for a symlink. |
| `canonical_digest` | string | `sha256:` of the semantic payload after removing `producer`, `generated_at`, `root` and per-file `last_modified`. |

Missing optional fields mean “not observed”; `null` is used only where the
schema explicitly permits it. Unknown additive fields are allowed. Removing,
retyping or changing the meaning of a required v1 field requires a new public
schema major; v1 is never silently repurposed.

## Artifact semantics and ordering

| Artifact | Required semantic content | Canonical ordering |
|---|---|---|
| `simplicio.project-map/v1` | Repository file inventory, product, modules, entities, architecture, dependencies, changes and integration pointers. `agent_tree` is a deterministic Brown–Hilbert projection. | Files and path arrays ascending by repository-relative POSIX path; modules/entities/signals/dependencies sorted by their documented key; `changed_files` and `recent_changes` sorted by path. |
| `simplicio.symbol-index/v1` | One record per detected definition; `qualified_name` is `<defined_in>::<name>`, so duplicate names are valid. | Symbols sorted by `name`, then `defined_in`, then `line`; counts equal the emitted records. |
| `simplicio.call-graph/v1` | Every relation uses `source_file`/`target_file` (never `from`/`to`), a stable `relation_id`, `evidence_class`, `resolution_status` and structured `provenance`. `target_file: null` is an explicit unknown target. | Edges sorted by `source_file`, `target_file`, `type`, then `target_symbol`/`import`, line and `relation_id`; duplicate logical edges are removed; counts equal the emitted edges. `coverage` reports observed/emitted/omitted edges, the configured limit, truncation, ambiguity and unknown targets. |
| `simplicio.precedent-index/v1` | Bounded snippets with stable ids, source path/line, language, change type, tags and summary. | Per-file ranked items are interleaved by rank; files are ordered by descending importance then path; final output is capped deterministically. |
| `simplicio.architecture-inventory/v1` | Join of the project map, symbol index and call graph with module/layer/file relationships and coverage. Relationships retain the canonical call-graph fields and `relationship_coverage` reports the inventory's own bound. | Modules/layers/files and their path lists are ascending by name/path; relationships inherit call-graph ordering; coverage counts the emitted arrays. |

All repository paths use `/`, are relative to the mapped root, and are not
resolved through symlinks. Text is decoded with replacement for invalid UTF-8;
the resulting replacement text is the observed semantic input. Generated and
ignored directories are omitted by the Mapper and are reported when the
omission is a known degraded path.

### Relation evidence

`evidence_class` is an assertion about how the endpoint was obtained, not a
calibrated probability: `semantic_resolved` and `runtime_observed` require
language/runtime evidence; `import_resolved` is a unique import-path match;
`lexical_unique` is a unique symbol-name match; `lexical_ambiguous` preserves
all candidates without claiming semantic resolution; and `heuristic` covers
unresolved or otherwise heuristic observations. `confidence` is `null` for
the Python producer unless a calibrated value is actually available.
`resolution_status` is `resolved`, `inferred`, `ambiguous` or `unknown`.
Name-inferred test links are emitted separately as `inferred_by_name`; they
must not be read as execution or coverage evidence. There is no implicit
`from`/`to` migration alias: a legacy-shaped relation is rejected and counted
as degraded coverage until an explicit producer migration supplies the
canonical endpoints.

The digest is SHA-256 over UTF-8 JSON with sorted object keys and producer
canonical array order. It intentionally excludes timestamps and machine-local
root paths so equal semantic inputs produce equal digests across repeated
runs. `canonical_digest` itself is excluded by excluding the whole producer
object.

## Backend compatibility policy

The Node mirror in `bin/mapper-artifacts.js` is not differential-parity
certified in this issue. Its payloads therefore use private ids:
`simplicio.mapper-native/<artifact>/v1`. They are not accepted as public v1
artifacts. Promotion requires the same fixture output shape, semantic ordering,
golden digest and degradation behavior, followed by an explicit contract
change. The Rust extension is an acceleration helper used behind the Python
producer and does not emit public artifact envelopes.

Native JSON-with-header is not canonical token-oriented TOON. A native backend
MUST NOT claim TOON equivalence or reuse a public artifact id until it passes
the round-trip and token-shape fixtures in [`TOON-CONTRACT.md`](../../../TOON-CONTRACT.md).

## Fixture suite

`fixtures/fixture-matrix.json` is the machine-readable case index. The
generated artifacts under each fixture's `artifacts/` directory are golden
outputs from the real Python entry point, normalized only for timestamps and
machine-local identity/path values. The matrix covers Python, TS/JS, Rust,
Go, Java/Kotlin, C#/Razor, SQL, a mixed-language monorepo, empty repositories,
unknown languages, generated directories, large files, symlinks, invalid
UTF-8/legacy text, duplicate symbol names, dirty worktrees and untracked
files. `scripts/regen_contract_fixtures.py check` regenerates the real output
and fails on drift; `update` is only for a deliberate contract change.
