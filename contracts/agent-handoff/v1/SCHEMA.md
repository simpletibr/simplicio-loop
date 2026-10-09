<!-- simplicio-contract:begin -->
contract: agent-handoff/v1
schema: simplicio.contract-doc/v1
purpose: Checkpoint that a loop agent writes before its next LLM request passes the input-token ceiling, so a new agent continues the task.
rules: The JSON schema next to this file is authoritative. Mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.agent-handoff/v1`

Owner rule: no LLM request of a loop agent carries more than 98,000 input tokens. The default ceiling is 98,000.
Set it with the key `agent_input_token_ceiling` in `<repo>/.simplicio-loop/loop.toml` or with the environment
variable `SIMPLICIO_AGENT_INPUT_TOKEN_CEILING`. The variable wins over the key.

The ceiling applies to the total prompt of one request: new input tokens, cache reads and cache writes.
The price tier depends on the whole prompt.

When the projected total prompt of the next request reaches 90% of the ceiling, the agent writes this document.
A new agent of the same family and role continues from it.
The loop writes the document to `<root>/.simplicio-loop/orchestrator/handoff/<run_id>/<n>.json`.
The loop never writes under `.simplicio/`.

## Fields

The document has these fields and no others.

| Field | Rule |
|---|---|
| `schema` | `simplicio.agent-handoff/v1` |
| `run_id` | `[A-Za-z0-9._-]{1,128}`, not `.` and not `..` |
| `task_id` | non-empty string |
| `continuation` | integer from 1 to 1000. The first handoff is 1. |
| `reason` | `input_ceiling`, `host_signal` or `manual` |
| `agent` | `family` (string), `role` (`planning`, `coordination` or `execution`), `model` (string) |
| `objective` | non-empty string, 2000 characters at most |
| `acceptance_criteria` | 1 to 50 non-empty strings |
| `done.files` | up to 200 objects `{path, sha256}`. See the path rule below. |
| `done.commands` | up to 100 objects `{command, exit_code, summary}` |
| `next_steps` | 1 to 50 non-empty strings |
| `open_questions` | up to 50 non-empty strings |
| `tokens` | See the token rules below. |
| `lease` | `{key, owner}`. These are the `key` and `owner` fields of the claim in `claim_lease.py`. The `owner_token` never enters a handoff. |
| `created_at` | UTC, `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` |

## Token rules

`tokens` has `basis`, `estimator`, `prompt_tokens`, `input_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`, `output_tokens`, `ceiling` and `cumulative_prompt_tokens`.

- `prompt_tokens` is the total prompt of the last request.
- `basis` is `MEASURED` when the provider reported the counts. Then `estimator` is `null`, the three input counts are
  integers, and `prompt_tokens` equals their sum.
- `basis` is `ESTIMATED` when the host reports no usage. Then `estimator` names the estimator
  (for example `conservative-v1`) and the three input counts are `null`.
- A MEASURED number and an ESTIMATED number never share a field.
- `output_tokens` is an integer or `null`. `ceiling` is the ceiling in force when the agent wrote the handoff.

## Rules the schema cannot state

`simplicio_loop.agent_handoff.validate_handoff` enforces these rules. Each failure has a `reason_code`.

| Rule | `reason_code` |
|---|---|
| The document does not match the schema. | `handoff_schema_invalid` |
| A `done.files[].path` is absolute, contains `..`, `.`, an empty part, a backslash or a drive letter, or has the prefix `.simplicio/`. | `handoff_path_invalid` |
| A MEASURED `prompt_tokens` is not the sum of the three input counts. | `handoff_tokens_inconsistent` |
| The canonical JSON is more than 6000 estimated tokens. | `handoff_too_large` |

The size uses `estimate_tokens` from `simplicio_loop/input_ceiling.py` on the JSON with sorted keys and no spaces.
The estimate is high for prose and code and low for rare Han, Ethiopic and mathematical symbols. The module docstring has the numbers.

## Compatibility

A new optional field or a new enum value needs `agent-handoff/v2`, because the schema allows no other field.
Renaming or removing a field also needs `agent-handoff/v2`.

The fixtures in `fixtures/` are valid (`valid-*.json`) or invalid (`invalid-*.json`).
`tests/test_agent_handoff_contract_unit.py` checks every fixture.
The wheel carries a copy of `schema.json` in `simplicio_loop/_contracts/agent-handoff/v1/`. The test also checks that the copy is byte-identical.
