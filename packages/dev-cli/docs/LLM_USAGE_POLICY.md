# Simplicio Python adapter policy

**Status:** deterministic-only

`simplicio-py` does not send prompts or completions to any LLM. This includes
local engines, OpenRouter, Anthropic, OpenAI-compatible endpoints, and logged-in
provider CLIs.

The package also does not load, download, or provision model weights. Provider
SDK extras and the local-model extra were removed from `pyproject.toml`.

## Runtime behavior

- task/run never synthesize a diff inside the package; mutation must arrive as an explicit mechanical-edit/changeset plan or through the negotiated Runtime Effect API.
- Blocked provider receipts include requested_route, effective_route=deterministic, model_invoked=false, and side-effect flags.

- `simplicio-py smoke` reports the deterministic-only adapter and performs no
  network or model operation.
- Generation and planning entry points fail closed with
  `reason_code=llm_execution_disabled`.
- Local model status functions are retained only as data-only compatibility
  surfaces; they never download or execute a model.
- Existing task, edit, test, cache, mapper, and evidence functionality remains
  local and deterministic.

No API key, model name, base URL, local inference flag, or provider CLI setting
can re-enable LLM execution inside this package. Use a separate external
orchestrator when an LLM is intentionally required.
