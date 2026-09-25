# .catalog/

Runtime catalog for the yool/tuple/HAMT pattern (see `docs/YOOL_TUPLE_HAMT.md`).

| Path | Purpose |
|---|---|
| `hamt.json` | HAMT registry built from AGENTS.md by `bin/build-hamt-catalog` |
| `tuples.jsonl` | Append-only log of tuple-space operations (`out`/`in`) |
| `receipts/<sha>.json` | Content-addressable execution records (immutable) |
| `artifacts/` | Body files referenced by receipts; subject to GC per §11.2 |

`receipts/` is the immutable Merkle chain — NEVER deleted, only artifact bodies are.
GC runs nightly per the disk guardrail (spec §11.2).
