# structured-output/v1

Closed response contracts for every model answer the loop parses (issue #1612).
`plan.schema.json` is the edit plan (`simplicio.model-plan/v1`), `verdict.schema.json` the review or judge verdict
(`simplicio.model-verdict/v1`). The handoff answer is `simplicio.agent-handoff/v1` (agent-handoff contract); it is
registered in `simplicio_loop/plan_scope.py` `RESPONSE_SCHEMAS` by the PR that adds that contract, not copied here.

Rules: `additionalProperties: false` everywhere, every string and array has a maximum, no free text in a plan, one
short optional `note` in a verdict finding. The post-answer validation (`plan_scope.check_response`) is the only
validator; a provider `response_format` or a CLI flag only narrows what the model emits.

Fixtures (`fixtures/`): `<kind>.valid.*` must pass; `<kind>.invalid.<code>.*` must fail with a violation that starts
with `<code>`. `.txt` fixtures hold raw model text (prose around the JSON).
