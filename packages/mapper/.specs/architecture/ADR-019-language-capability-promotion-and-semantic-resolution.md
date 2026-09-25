# ADR-019: Gate native Mapper promotion by language capability evidence

## Status

`Aceito`

## Data

`2026-09-06`

## Autores

- Simplicio Mapper maintainers

## Contexto

Issue #617 requires parity to be tracked independently for language and
capability.  The reusable Rust core from [ADR-018](./ADR-018-reusable-rust-mapper-core-and-differential-shadow.md)
cannot safely become the default for a language when only one extraction
kernel is equivalent to the Python Mapper.  C# and Razor also need compiler
identity for overloads; regex/name lookup is useful for discovery but is not
semantic evidence.  SQL object discovery must remain separate from call-graph
inference.

## Decisão

Adotamos uma versioned language/capability matrix, explicit Python fallback
routes, and an optional deterministic compiler-semantic service at the Mapper
boundary.

- The catalog tracks 34 priority-stack languages and 15 required capabilities.
- Native selection is language-aware and only applies to an advertised core
  capability; unsupported work stays on the canonical Python path.
- A language is never fully promoted while any required row is `MISSING` or
  `MISMATCH`.
- C#/Razor semantic services receive a bounded JSON source-generation request
  through `SIMPLICIO_MAPPER_SEMANTIC_COMMAND`. Resolved identities and overloads
  are marked semantic; service absence or failure produces explicit heuristic
  or inferred evidence and a degradation receipt.
- SQL emits table/view/function/procedure symbols and is excluded from the
  call graph until call-site semantics are supported.
- `project-map.json`, fast handoffs, differential fixtures, and the matrix
  expose capability status, route backend, degradation, and promotion blockers.

## Consequências

### Positivas (+)

- A native kernel cannot silently discard a known-language file or claim
  unsupported semantic evidence.
- C# overload resolution can use compiler-provided symbol identity without
  changing the public Mapper artifact schemas.
- Downstream Runtime/Loop consumers can inspect a bounded receipt instead of
  inferring backend safety from process success.

### Negativas (-)

- The capability matrix and 510 fixture cases require maintenance as support
  expands.
- Semantic resolution depends on a host-provided service and degrades when it
  is unavailable.
- The compact receipt is grouped by status/backend/route rather than repeating
  the full matrix in every artifact.

### Neutras / observações

- The first native promotion remains blocked for every language until all
  advertised required capabilities have parity evidence.

## Alternativas consideradas

### Alternativa A — Promote the Rust core per language

- Use the native kernel whenever its language enum contains the file.
- Rejected because language membership does not prove parity for calls,
  semantic references, SQL objects, or retrieval-related capabilities.

### Alternativa B — Keep all extraction in regex/name lookup

- Extend the existing lightweight parser and label every result resolved.
- Rejected because duplicate C# overloads cannot be safely identified and
  heuristic evidence would be indistinguishable from compiler resolution.

### Alternativa C — Require Roslyn as a Python package dependency

- Ship a .NET/Roslyn runtime with the Mapper installation.
- Rejected because it expands package/runtime ownership; the host Runtime can
  supply a deterministic adapter while the Mapper keeps a bounded fallback.

## Critério de revisão

- Revisit a language when its matrix reaches all `NATIVE_PARITY`, when the
  semantic service protocol needs a breaking change, or when a downstream
  Runtime contract adds a required capability.

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/617
- Related: [ADR-018](./ADR-018-reusable-rust-mapper-core-and-differential-shadow.md)
- Contract: [`contracts/mapper-capability/v1/README.md`](../../contracts/mapper-capability/v1/README.md)
