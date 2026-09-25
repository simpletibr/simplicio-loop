# Fast changeset v2

Dev CLI is the official executor for `simplicio.fast.changeset/v2`. Fast
produces a plan; it does not write files when this integration is available.

```console
simplicio-py changeset --plan changeset.json --json
simplicio-py changeset --plan changeset.json --current-generation gen-42 --apply --json
```

Dry-run is the default. The adapter accepts `replace_range`, `create`,
`delete`, `move`, `json_patch`, and Python `ast_patch`; it translates them to
the established `simplicio.mechanical-edit/v1` boundary. Every path must be
listed in `allowlist`. A supplied current generation must equal the changeset
generation. File/range hash mismatches and overlapping ranges are rejected
while the executor is still operating on its in-memory snapshot.

Apply writes the complete post-edit snapshot and then runs validation. A
failure restores every original file. Receipts use
`simplicio.fast.changeset-receipt/v2`, preserve changeset/generation/
correlation IDs, and report per-file before/after hashes. `effect_unknown`
remains explicit rather than being reported as success.
