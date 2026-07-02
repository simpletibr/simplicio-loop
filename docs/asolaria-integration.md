# Asolaria integration (issue #150)

Scope of this change: **P0 only**, per the issue's own instruction ("implemente
os itens P0 apenas ... Documente P1/P2 como follow-up explícito no PR, não
implemente"). This document records what P0 delivered and lists P1/P2 as
explicit, undone follow-up.

## P0 — done

### Tagging discipline

`simplicio-mapper index <path> --tagged` attaches an Asolaria-style
confidence tag to every entry in the `counts` payload:

- `MEASURED` — read directly off the code on disk this run (files,
  precedents, changed_files, symbols, relationships, docs).
- `CANON` — derived from doc/README/architecture-convention claims rather
  than a direct code read (modules, layers — these lean on folder/naming
  conventions, not a verified runtime cross-check).
- `OPERATOR` — reserved for a human-supplied exact number (screen -> photo
  -> extract provenance); this CLI never emits it on its own, since it has
  no operator-input channel today.
- `UNVERIFIED` — default for anything not covered above; never silently
  omitted ("no deflate-gate").

`--confidence <tag>` filters `counts` down to entries at least as strong as
the given tag and — per the Asolaria "no deflate-gate"/"no claims-gate" rule
cited in the issue — records exactly what was filtered out and why under
`confidence_filtered_out`, rather than making the weaker data vanish.

### Addressing geometry

`simplicio-mapper index <path> --geometry` attaches, per artifact path in
the `index` payload:

- `realmathpos` — `{file, line, col}`. For this top-level artifact-address
  pass it degenerates to the artifact file's own root position
  (`line: 1, col: 1`) rather than a specific symbol position; per-symbol
  positions already exist elsewhere in this CLI (`ask`, `endpoints`) and are
  out of scope for this pass (see P1 below).
- `fnv1a64` — FNV-1a, 64-bit, of the path string, as 16 hex chars. Pure
  Python, no new dependency.
- `sha16` — `sha256(path)` truncated to 16 hex chars (8 bytes). Chosen to
  match the convention this repo's own `precedent-index.json` item ids
  already use (16-hex-char ids), not an arbitrary truncation.
- `citizen_identity` — `"<repo-dir-name>::<artifact-key>"`, a stable
  identity for the entry within the federation of mapped repos.

Both flags compose with `--json` and `--for-llm toon`.

Tests: `tests/python/test_cli_toon_asolaria.py` (`AsolariaTaggingTest`,
`AsolariaGeometryTest`).

## Command surface note

The issue's proposal text says `simplicio runtime map --tagged` — that
command belongs to the separate `simplicio-runtime` (Rust) binary in a
different repo, which itself shells out to this Python mapper as an
adapter. This repo's own command surface is `simplicio-mapper index`
(its "instant map refresh with JSON output" command), which is where these
flags are implemented. Wiring an equivalent `--tagged`/`--geometry` pass-
through on the `simplicio-runtime` side is out of scope here — that repo
is not touched by this PR.

## P1 — not implemented, explicit follow-up

- **BEHCS encoding tiers** (`--tier 256|1024|hyper`) — three resolution
  tiers of the map output. The closest existing analog is `--for-llm
  markdown` (compact) vs the full JSON/TOON payload; a true 3-tier system
  needs its own token-budget design, not a re-label of what exists.
- **Spindle-wave scanning** (`--scan spindle`) — concentric-wave file
  traversal starting from the most-referenced files. This repo's file walk
  is currently a plain directory walk; re-ordering traversal by reference
  count is a real algorithmic change, not attempted here.

## P2 — not implemented, explicit follow-up

- **Omniquant engine** (`--quant`) — structural-preserving prose
  compression on top of `--for-llm markdown`.
- **Binary/hash/hex/crypto tuple output** — expressing every map entry in
  4 simultaneous encodings. `--geometry` above already covers the
  hash/hex half (`fnv1a64`/`sha16`); the binary/crypto halves are not
  implemented.
- **Rust Host-8 migration** (`--host8`, JSON-free binary wire format) — a
  new binary output format is a substantial format-and-decoder addition on
  both the Python and Node sides; not attempted here.

None of the P1/P2 items above touch any existing command surface, so they
are safe to schedule as independent follow-up issues without blocking P0.
