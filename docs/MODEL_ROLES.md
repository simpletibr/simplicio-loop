# Model per role (default)

Each runtime family has three roles. The loop reads the table from `simplicio_loop/_catalog/model_roles.json` and resolves it with `simplicio_loop.model_roles.resolve(family, role)`.

| Role | What it does | Claude | Codex | Grok | Gemini |
|---|---|---|---|---|---|
| `planning` | Hard decisions, plans, reflection | `claude-opus-5-5` (high) | `gpt-5.6-terra` (high) | `grok-4.7` (xhigh) | `gemini-3.8-flash` (high) |
| `coordination` | Coordinate, review, track progress | `claude-sonnet-5-5` (high) | `gpt-5.5` (high) | `grok-4.7` (high) | `gemini-3.7-flash` (high) |
| `execution` | Run the work, tests, merges, workers | `claude-haiku-5-5` (high) | `gpt-5.6-luna` (high) | `grok-4.7` (high) | `gemini-3.6-flash` (high) |

Use the Claude row with the host's model names: `opus`, `sonnet`, `haiku`. Never use xhigh or max effort for Opus.

## Caveats

- **OpenAI effort.** The Codex rows use `high`. Check the effort levels each Codex id accepts before you change them.
- **Effort names.** `xhigh` is an effort level, not a model. It exists for `grok-4.7` only in this table.
- **Verification.** The Grok and Gemini IDs come from provider documentation or launch coverage checked on 2026-10-08. The Codex IDs have no source recorded yet; `python -m simplicio_loop.model_probe --family codex` checks them against the Codex CLI. Re-check the IDs against each provider before a release.
- **Scope.** The table sets the default for subagents the host starts. The loop's own operator still uses `SIMPLICIO_MODEL` (default `codex-cli/gpt-5.4`, effort medium); changing that default is a separate decision.

## Sources

- Grok: <https://docs.x.ai/docs/grok-4-6>, <https://docs.x.ai/developers/grok-4-5>, <https://www.cometapi.com/en/models/xai/grok-4-7>
- Gemini: <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>, <https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-7-flash>, <https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-6-flash>
- OpenAI: none recorded for `gpt-5.6-terra`, `gpt-5.5` or `gpt-5.6-luna`; see Verification.
