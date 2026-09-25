# ADR-0002: TurboQuant vector contracts and segment boundaries

- Status: proposed, versioned contract only
- Scope: issue #85 bounded slice
- Contract schemas: `simplicio.fast-vector-index/v1` and `simplicio.fast-vector-query-receipt/v1`

## Decision

Fast freezes the metadata boundary for a future TurboQuant 4-bit vector index and
its query receipt before implementing a writer or query engine. The Python
validators in `src/simplicio_fast/vector_contracts.py` reject an unknown major
schema, malformed hashes, invalid bounds, overlapping segments, non-little-endian
segments, and receipts with non-finite scores. Validation returns the original
mapping and never mutates it.

Mapper remains the owner of canonical symbol/vector IDs. Fast owns the binary
layout, quantizer metadata, immutable segment references, integral vector-store
metadata, and query observability. The receipt carries IDs and scores, never
vector payloads or prompt content.

## Manifest contract

The v1 manifest records repository, commit, generation, embedding model and
revision, dimension, metric, normalization, `turboquant-4bit` format metadata,
rotation-seed and codebook hashes, vector count, Mapper ID mapping, segment
ranges/checksums, integral-store format (`fp16` or `fp32`), build-source hashes,
creation time, and compatibility flags.

## Binary layout boundary

Published hot segments are immutable, read-only files referenced by the JSON
manifest. The normative v1 header is little-endian and 4096-byte aligned:

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 4 | magic `SFTQ` |
| 4 | 2 | format version `u16` |
| 6 | 2 | flags `u16` |
| 8 | 4 | embedding dimension `u32` |
| 12 | 8 | vector count `u64` |
| 20 | 8 | packed payload offset `u64` |
| 28 | 8 | packed payload bytes `u64` |
| 36 | N | two 4-bit codes per byte, with explicit odd-dimension padding |

Rotation seed, codebook, endianness, checksums, and segment bounds are metadata
in the manifest. The integral store is a separate cold FP16/FP32 file and is
materialized only by the future query path for candidate re-ranking.

## Non-goals and residuals

This ADR does not claim that TurboQuant quantization, approximate candidate
search, integral re-ranking, mmap publication, atomic generation promotion,
Python/Rust golden parity, planner fallback, quality gates, or benchmarks exist.
Those remain separate issue #85 slices. Rust, Loop, Runtime, and Mapper E2E
integration remain residuals. No performance or recall gain is claimed from this
contract-only change.