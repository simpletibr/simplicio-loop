# Patch receipts

`simplicio-py task --json` emits a `patch` receipt whenever the operator parses a candidate patch.
The receipt is evidence for the parser strategy and the capability actually used by the lane.

```json
{
  "schema": "simplicio.dev-cli.patch-receipt/v1",
  "parser_strategy": "unified_diff",
  "fingerprint": "<sha256 of the normalized patch>",
  "files": ["src/app.py"],
  "capability": {
    "requested": {"model": "codex-cli/gpt-5.6-luna", "effort": "medium", "tier": "fast"},
    "effective": {"model": "codex-cli/gpt-5.6-luna", "effort": "medium", "tier": "fast"}
  }
}
```

Recovery strategies are explicit. `full_file_artifact` means the model returned a complete target
file without a unified diff; `full_file_after_patch_failure` means a stale or corrupt diff failed
validation and the complete target file produced a deterministic replacement diff. A lane must not
claim success without the parser receipt and the normal verification receipt.
