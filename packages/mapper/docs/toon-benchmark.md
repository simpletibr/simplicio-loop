# TOON benchmark — mapper survey artifacts

Re-measured: 2026-07-02 (issue #148, follow-up to #144).

Tokenizer used: regex word-boundary approximation (`\S+`-ish split on `[A-Za-z0-9_]+` runs and individual punctuation characters), **not** `chars/4` and **not** a real BPE tokenizer — `tiktoken` is not installed in this repo (no new dependency added without human confirmation, per AGENTS.md). Char-count reduction is the exact, primary number; the token column is a documented, reproducible proxy for it.

| Artifact | JSON chars | TOON chars | Char reduction | JSON tokens (approx) | TOON tokens (approx) | Token reduction (approx) | Lossless | Fallbacks |
|---|---:|---:|---:|---:|---:|---:|:---:|---:|
| `project-map.json` | 218,383 | 156,553 | 28.3% | 78,659 | 49,713 | 36.8% | yes | 1 |
| `precedent-index.json` | 51,833 | 40,823 | 21.2% | 18,986 | 12,319 | 35.1% | yes | 0 |
| `flow-inventory.json` | 13,193 | 13,181 | 0.1% | 6,415 | 6,385 | 0.5% | yes | 1 |

## Fallbacks (non-tabular arrays)

- `project-map.json` `$.agent_tree.children` — nested_containers
- `flow-inventory.json` `$.flows` — nested_containers

## History

- **Pre-fix (#144, PR #145)**: 7.1% / 4.5% / 8.4% char reduction on `project-map` / `precedent-index` / `flow-inventory` — the tabular path rejected any array whose elements contained a list cell (`files[].exports/imports/roles`, `items[].tags`), which is most of the mapper's real data shape, so almost everything fell back to embedded compact JSON.
- **Post-fix (#148)**: the tabular path now accepts cells whose value is a list of scalars (`[a,b,c]` inline within the row), which is exactly that shape. Remaining fallbacks are genuine nested dict-valued cells (`agent_tree.children`, `flows[].steps`), not a bug — honestly reported below via `toon_fallbacks`, not silently dropped.

