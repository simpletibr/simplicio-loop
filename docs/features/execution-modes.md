# Execution modes

Coordinator-facing task, feature, and sprint entrypoints accept `--mode auto|integrated|standalone`.
The same setting is available through the Python API (`mode=`), `SIMPLICIO_EXECUTION_MODE`, or
`.simplicio/execution.json`. Precedence is flag/API, environment, project config, then `auto`.

| Requested | Result |
|---|---|
| `standalone` | Explicit local lifecycle; receipts never claim Runtime gating or evidence. |
| `integrated` | Requires a versioned Runtime EffectTransaction capability, production sink, and canonical Mapper ContextSnapshot; otherwise blocks before planning/effects. |
| `auto` | Selects integrated only from the versioned handshake and rollout policy. It may degrade to standalone only when fallback policy permits, and records the reason. |

Inspect negotiation without executing work:

```bash
simplicio-py runtime capabilities --mode auto --json
```

Project configuration:

```json
{"mode":"auto","allow_standalone_fallback":true,"rollout":"shadow"}
```

Rollout values are `shadow`, `canary`, and `default`. Shadow records eligibility but executes once in
standalone. `SIMPLICIO_INTEGRATED_KILL_SWITCH=1` rolls back selection; integrated requests still fail
closed, while auto follows the explicit fallback policy. Set
`SIMPLICIO_ALLOW_STANDALONE_FALLBACK=false` when a coordinator must never degrade.

An `effect_unknown` outcome belongs to the selected Runtime transaction. Callers must reconcile it;
they must not retry in standalone or renegotiate the mode. Until issue #256 supplies the production
RuntimeEffectSink, installed CLI integrated requests correctly report `RUNTIME_SINK_REQUIRED` (or an
earlier missing contract) rather than using the test-only recording sink.
