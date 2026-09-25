# Policy replay

`simplicio_fast.policy_replay` provides an API-only offline path for replaying
Fast policy decisions against recorded `simplicio.fast-local/v1` telemetry.
Loading validates the telemetry message before the current `SpeculationPolicy`
is called. Replay never imports or starts Simplicio Local, a model, a KV cache,
or a kernel.

## Python API

```python
from simplicio_fast.policy_replay import (
    load_snapshot,
    replay_snapshot,
    replay_snapshots,
)

one = load_snapshot("telemetry.json")
result = replay_snapshot(one)
print(result.decision_receipt)  # contract-shaped decision_receipt
print(result.report)             # stable human-readable report

batch = replay_snapshots(["telemetry-a.json", "telemetry-b.json"])
print(batch.to_dict())           # machine-readable summary and results
```

Inputs may be a contract telemetry message, a JSON path/string, or a wrapper
with `snapshot`/`telemetry_snapshot` and an optional historical
`historical_decision`/`decision_receipt`. A JSON array or `{ "snapshots": [...] }`
is accepted for batch replay. The historical receipt is validated independently;
if its source digest differs from the snapshot digest, the result remains
usable but reports `historical_source_digest_differs`.

The current policy defaults to `SpeculationPolicy()` and is identified as
`simplicio.fast.speculation-policy/v1`. A pinned policy can be supplied with
`policy=SpeculationPolicy(...)` and a caller-owned `policy_version` label. An
unknown version without an explicit policy fails closed because this module
does not invent historical policy implementations.

The nested `decision_receipt` is validated against the existing contract. The
contract currently represents `draft` as `draft_verify` and all other enabled
Fast speculation strategies as `tree`; `result.policy_result` and `diff.current`
retain the exact Fast strategy. Placement is copied from the recorded
capability details, while the replay-only context batch default is
`batch_size=1`, `ranking=balanced`.
The default receipt confidence is `1.0` for completion of the deterministic
policy rule evaluation; it is not a measured execution or performance score.
Callers can provide a different policy-evaluation confidence explicitly.

## CLI integration point

The first integration point for a future CLI command is the existing
`simplicio-fast` command registration in `src/simplicio_fast/cli.py`:
`policy-replay --snapshot <path> [--policy-version <version>]`. The command
should call `load_snapshot`/`load_snapshots`, serialize `to_dict()` for JSON
output, and use `report` for human output. This issue intentionally leaves the
shared CLI parser unchanged so the API and receipt contract can land without
conflicting command wiring.
