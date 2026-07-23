# Execution modes

Coordinator-facing task, feature, and sprint entrypoints accept `--mode auto|integrated|standalone`.
The same setting is available through the Python API (`mode=`), `SIMPLICIO_EXECUTION_MODE`, or
`.simplicio/execution.json`. Precedence is flag/API, environment, project config, then `auto`.

| Requested | Result |
|---|---|
| `standalone` | Explicit local lifecycle; receipts never claim Runtime gating or evidence. |
| `integrated` | Requires a versioned Runtime EffectTransaction capability, production sink, and a Mapper-validated `simplicio.context-snapshot/v1`; otherwise blocks before planning/effects. A matching schema string alone is never accepted. |
| `auto` | Selects integrated only from the versioned handshake and rollout policy. It may degrade to standalone only when fallback policy permits, and records the reason. |

Inspect negotiation without executing work:

```bash
SIMPLICIO_RUNTIME_URL=http://runtime:8080 \
simplicio-py runtime capabilities \
  --mode auto \
  --context-snapshot .simplicio/context-snapshot.json \
  --attempt-id attempt-42 \
  --lease-id lease-7 \
  --fencing-token fence-9 \
  --context-handle mapper-snapshot-123 \
  --coordinator-kind simplicio-agent \
  --coordinator-id agent-1 \
  --json
```

Project configuration:

```json
{"mode":"auto","allow_standalone_fallback":true,"rollout":"shadow"}
```

Execute one coordinator-owned atomic task from an installed entrypoint:

```bash
SIMPLICIO_RUNTIME_URL=http://runtime:8080 \
SIMPLICIO_TEST_CMD='pytest -q' \
simplicio-py task 'add the decided validation' \
  --target src/app.py \
  --mode integrated \
  --context-snapshot .simplicio/context-snapshot.json \
  --attempt-id attempt-42 \
  --lease-id lease-7 \
  --fencing-token fence-9 \
  --context-handle mapper-snapshot-123 \
  --coordinator-kind simplicio-agent \
  --coordinator-id agent-1 \
  --json
```

The same transient values can be supplied to the Python API or through
`SIMPLICIO_CONTEXT_SNAPSHOT`, `SIMPLICIO_ATTEMPT_ID`, `SIMPLICIO_LEASE_ID`,
`SIMPLICIO_FENCING_TOKEN`, and `SIMPLICIO_CONTEXT_HANDLE`. All four attempt
identity fields are required together. The context handle is the canonical
Mapper snapshot ID; it is never derived from the file path.

Explicit `standalone` does not read the context snapshot and does not probe
Mapper, the Runtime binary, or `SIMPLICIO_RUNTIME_URL`.

Rollout values are `shadow`, `canary`, and `default`. Shadow records eligibility but executes once in
standalone. `SIMPLICIO_INTEGRATED_KILL_SWITCH=1` rolls back selection; integrated requests still fail
closed, while auto follows the explicit fallback policy. Set
`SIMPLICIO_ALLOW_STANDALONE_FALLBACK=false` when a coordinator must never degrade.

An `effect_unknown` outcome belongs to the selected Runtime transaction. Callers must reconcile it;
they must not retry in standalone or renegotiate the mode. The production `RuntimeEffectSink` is selected
only with a compatible Runtime endpoint; otherwise integrated requests fail closed rather than using the
test-only recording sink.

Malformed, missing, oversized, or non-object snapshot files return
`INCOMPATIBLE_CONTEXT` before planning, provider calls, or Runtime/product
writes. A partial attempt identity returns
`COORDINATOR_CONTEXT_REQUIRED`.
