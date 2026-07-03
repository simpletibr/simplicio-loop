# Spec: Asolaria Geometric Mapping

**Issue:** #150  
**Date:** 2026-07-03  
**Status:** Spec  
**Tags:** enhancement, asolaria, geometry, mapping

## Objective

Evolve `simplicio-mapper` from plain-text repo mapping to geometric/hyper-dimensional
mapping using Asolaria Algorithms + HYPER-BECHS concepts.

## Architecture

### Layer 1: Tagging Discipline (P0)

Every mapper output item carries one of 4 tags:

| Tag | Meaning | Implementation |
|---|---|---|
| `MEASURED` | Code read / executed | Actual file hash + line count verified |
| `CANON` | Doctrine/README states | Source file reference + match |
| `OPERATOR` | Operator gave exact number | Provenance: screen→photo→extract |
| `UNVERIFIED` | Cannot confirm against running system | Detected but not verified |

### Layer 2: Addressing Geometry (P1)

Replace flat file paths with geometric addressing:

- `REALMATHPOS`: `file:line:col` triples
- `FNV-1a64`: fast non-crypto hash (directory walk → O(1) lookup)
- `sha16`: truncated SHA-256 for canonical module identity
- `citizenIdentity`: full identity in the federation

### Layer 3: BEHCS Encoding Tiers (P2)

Three encoding tiers for different payload sizes:

| Tier | Space | Use Case |
|---|---|---|
| 256 | `256^60 ≈ 10^144` | Small repos, single modules |
| 1024 | `1024^60 ≈ 10^180` | Medium projects |
| HyperBEHCS | `1024^256 ≈ 10^768` | Large monorepos |

### Layer 4: Brown-Hilbert Addressing (P3)

`port.port.port` addressing for nested module hierarchies,
with Sidon sets for collision avoidance.

## Implementation Plan

### Phase 1: Tagging (current)

- [x] Create spec document
- [x] Create example implementation
- [ ] Integrate tagging into mapper.py output

### Phase 2: Geometric Addressing

- [ ] Implement `REALMATHPOS` in `simplicio_mapper/mapping/`
- [ ] Add FNV-1a64 hash for fast module lookup
- [ ] Add sha16 for canonical identity

### Phase 3: BEHCS Encoding

- [ ] Implement 256/1024/HyperBEHCS encoders
- [ ] Auto-detect appropriate tier per repo size
- [ ] Benchmark encoding vs JSON baseline

### Phase 4: Brown-Hilbert

- [ ] Implement nested addressing with Sidon sets
- [ ] Integrate with existing module hierarchy

## Acceptance Criteria

- [ ] Tagging discipline applied to all mapper output
- [ ] Geometric addressing (REALMATHPOS) replaces flat paths in map results
- [ ] FNV-1a64 hash lookup < 1µs per path
- [ ] BEHCS encoding matches JSON output size for test corpora
- [ ] Brown-Hilbert addressing works for repos with 1000+ modules
- [ ] All existing tests pass

## References

- `YOOL_TUPLE_HAMT.md` (canonical spec in repo)
- `examples/brown-hilbert-addresses.json`
- https://github.com/JesseBrown1980/Algorithms-of-Asolaria
- https://github.com/JesseBrown1980/HYPER-BECHS--the-third-set
