# Goal Result — GitHub issue #320

## Result

A tested fail-closed patch is ready. The change does not claim the full binary
migration complete: strict mode correctly blocks release until internal JSON is
removed and every external evidence criterion is explicitly observed.

## Delivered

- Explicit TOML observations for cross-repository E2E, performance, HBP receipt,
  and HBI conformance.
- Release failure on missing, malformed, negative, or incomplete observations.
- Safe Markdown evidence rendering for multiline output and table delimiters.
- npm prepublish integration and operator documentation.
- Focused regression coverage and durable local execution evidence.

## Exit status

`BLOCKED` for full issue completion because required Runtime/adjacent-package
conformance and the underlying internal-format migration are unavailable. The
issue must remain open until those criteria pass after merge.
