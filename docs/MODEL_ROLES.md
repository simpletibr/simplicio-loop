# Model per role (default)

Each runtime family has three roles. The loop reads the table from `simplicio_loop/_catalog/model_roles.json` and resolves it with `simplicio_loop.model_roles.resolve(family, role)`.

| Role | What it does | Claude | Codex | Grok | Gemini |
|---|---|---|---|---|---|
| `planning` | Hard decisions, plans, reflection | `claude-opus-5-5` (high) | `gpt-6-astra` (high) | `grok-4.7` (xhigh) | `gemini-3.8-flash` (high) |
| `coordination` | Coordinate, review, track progress | `claude-sonnet-5-5` (high) | `gpt-6.1-sol` (high) | `grok-4.6` (high) | `gemini-3.7-flash` (high) |
| `execution` | Run the work, tests, merges, workers | `claude-haiku-5-5` (high) | `gpt-6-luna` (high) | `grok-4.5` (high) | `gemini-3.6-flash` (high) |

Use the Claude row with the host's model names: `opus`, `sonnet`, `haiku`. Never use xhigh or max effort for Opus.

## Caveats

- **Sol tier.** The table uses `gpt-6.1-sol`, the newer snapshot at the same list price. Sources also list `gpt-6-sol`. Change the row in `_catalog/model_roles.json` if you want the older one.
- **OpenAI effort.** `gpt-6.1-sol` does not accept `none` or `minimal`. The table uses `high`, which it accepts. Tool calling on 6.1 is documented for the Responses API.
- **Effort names.** `xhigh` is an effort level, not a model. It exists for `grok-4.7` only in this table.
- **Verification.** The Grok, Gemini and OpenAI IDs come from provider documentation or launch coverage checked on 2026-10-08. Re-check the IDs against each provider before a release.
- **Scope.** The table sets the default for subagents the host starts. The loop's own operator still uses `SIMPLICIO_MODEL` (default `codex-cli/gpt-5.4`, effort medium); changing that default is a separate decision.

## Sources

- Grok: <https://docs.x.ai/docs/grok-4-6>, <https://docs.x.ai/developers/grok-4-5>, <https://www.cometapi.com/en/models/xai/grok-4-7>
- Gemini: <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>, <https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-7-flash>, <https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-6-flash>
- OpenAI: <https://openai.com/es-ES/index/introducing-gpt-6-sol-and-luna/>, <https://www.llmreference.com/model-family/gpt-6.1>
