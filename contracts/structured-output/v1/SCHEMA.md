# structured-output/v1

Closed response contracts for every model answer the loop parses (issue #1612).
`plan.schema.json` is the edit plan (`simplicio.model-plan/v1`), `verdict.schema.json` the review or judge verdict
(`simplicio.model-verdict/v1`). The handoff answer is `simplicio.agent-handoff/v1` (agent-handoff contract). It is
registered in `simplicio_loop/plan_scope.py` `RESPONSE_SCHEMAS` by the PR that adds that contract, not copied here.

Rules: `additionalProperties: false` everywhere, every string and array has a maximum, no free text in a plan, one
short optional `note` in a verdict finding. The post-answer validation (`plan_scope.check_response`) is the only
validator. A provider `response_format` or a CLI flag only narrows what the model emits.

Fixtures (`fixtures/`): `<kind>.valid.*` must pass. `<kind>.invalid.<code>.*` must fail with a violation that starts
with `<code>`. `.txt` fixtures hold raw model text (prose around the JSON).

The plan may ask for lines it cannot see: `{"operations": [], "need": [{"path", "start", "end"}]}` (at most 8 items).
An empty `operations` is valid only with a non-empty `need`.

Origin (`simplicio_loop/structured_output.py`): the schema a CLI flag or a provider `response_format` receives is the
contract with only portable keywords and every property required. `find` is then `""` for a new file and `need` is `[]`.
The receipt `structured_output: enforced|validated_only` and its reason say whether the origin got a schema.
