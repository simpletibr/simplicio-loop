# Release Gate Live Lanes

live-lane readiness companion to the deterministic PLANES release gate for #114/#121; does not claim release readiness by itself

- PLANES case: `planes-ordering`
- probe shell-outs: `True`
- measured lanes: 1
- ready lanes: 0
- blocked lanes: 5

| lane | route | kind | status | available | measured |
| --- | --- | --- | --- | --- | --- |
| codex-gpt-5.4-medium | `codex-cli/gpt-5.4-medium` | shell-out | blocked | False | True |
| codex-default | `codex-cli/default` | shell-out | measured | True | True |
| claude-default | `claude-cli/default` | shell-out | blocked | True | True |
| openai-gpt-5.4 | `openai/gpt-5.4` | api | blocked | False | False |
| anthropic-claude-opus-4.7 | `anthropic/claude-opus-4-7` | api | blocked | False | False |
| deepseek-v3.1 | `deepseek-hf/deepseek-ai/DeepSeek-V3.1` | api | blocked | False | False |

## Missing Release Evidence

- full live PLANES execution receipts across the allowed provider matrix
- runtime+loop+dev-cli cross-repo receipts
- Windows/Linux live matrix
