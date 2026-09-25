# Auditable S0-S3 E2E protocol

This harness is the preregistration and validation slice for issue #163. It deliberately ships no
claimed E2E measurements. Cross-repository cells stay `blocked` until the exact component artifacts,
provider and second environment are available.

## Frozen matrix

| Scenario | Components | Engine cells |
|---|---|---|
| S0_BASELINE | no Simplicio integration | off |
| S1_RUNTIME | Runtime | off |
| S2_RUNTIME_LOOP | Runtime + Loop | off |
| S3_FULL_STACK | Runtime + Loop + Mapper + Dev CLI + Fast | rust, python, off |

Every engine cell uses the five workloads and the 1/20/100-slot matrix, with at least ten repetitions.
The generated order is deterministically randomized from the recorded seed.

## Required lifecycle

1. Freeze source commit, corpus SHA-256, acceptance criteria, prompts and toolchain.
2. Record exact component versions/commits and an environment receipt; hash the receipt.
3. Run an uncounted capability-handshake smoke test.
4. Generate and retain the preregistration before observing results.
5. Restore the frozen source before every repetition; failure produces `blocked`, not a skipped row.
6. Execute the preregistered order with explicit cold/warm policy.
7. Record raw metrics, including refresh and IPC in total cost.
8. Validate the dataset before aggregation or publication.
9. Repeat in a second environment and explain directional divergence.
10. Publish raw JSON/CSV/HBP receipts; derived reports must label observed, inferred and unverified data.

Generate a plan without running anything:

```bash
python - <<'PY'
import json
from benchmarks.e2e_protocol import preregister
print(json.dumps(preregister(seed=163), indent=2))
PY
```

Validate a collected dataset:

```bash
python - <<'PY'
from benchmarks.e2e_protocol import load_and_validate
print(load_and_validate("benchmarks/results/e2e-s0-s3.json"))
PY
```

## Honesty invariants

- Missing metrics are `{"value": null, "reason": "<reason-code>"}`; null is never zero.
- A complete run cannot contain a missing metric.
- Blocked runs retain a machine-readable reason and all unavailable measurements.
- Corpus, source commit and environment identity cannot drift inside a comparison dataset.
- Underfilled cells are reported; the validator never fabricates repetitions.
- Query-only speedups cannot be described as E2E delivery gains.
- Positive and negative results remain in raw output.

The JSON Schema gives interoperability checks. The Python validator enforces stricter semantic
rules, including engine/scenario compatibility, complete metric coverage and frozen identity.
