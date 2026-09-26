# Issue #302 — Loop authority-boundary evidence

This document defines the cross-repository evidence lane for
`wesleysimplicio/simplicio-dev-cli#302`. The Loop is the coordinator-facing
boundary; the Dev CLI remains the owner of effect-specific proposal binding
and the Runtime sink remains the final transport gate.

## Boundary implemented in Loop

`simplicio_loop.authority_boundary` accepts only the fixed coordinator artifact
`.simplicio-loop/orchestrator/.../effect-authorization.json`. It validates the versioned
schema, exact fields, canonical digest, coordinator issuer, validity window,
and optional causal bindings. Mapper/LLM payloads are never searched for an
authorization path. A valid artifact is forwarded to the installed Dev CLI
as `--effect-authorization`; invalid or missing artifacts fail closed for the
Runtime-backed path. Receipts/log summaries expose only the authorization
digest and issuer, not prompts, secrets, or the authorization payload.

## Installed E2E command

Run this from a clean environment containing the installed packages and their
console scripts:

```bash
python scripts/authority_e2e.py run --out .simplicio-loop/orchestrator/runs/issue-302/authority-e2e.json
```

The command exits non-zero when `simplicio-dev-cli`, `simplicio-mapper`, or
`simplicio-loop` is missing, when the imported Dev CLI is not installed from a
site-packages location, or when any case is not `PASS`. It never converts an
unavailable installed toolchain into a green result.

## Receipt matrix

| Case | Required observation |
|---|---|
| missing authorization | `EFFECT_AUTHORIZATION_REQUIRED`; transport call count remains zero |
| model issuer | `LLM_CANNOT_AUTHORIZE` |
| valid coordinator authorization | completed receipt carries the same authorization digest |
| tampered authorization | digest verification fails before effect |
| expired authorization | `AUTHORIZATION_EXPIRED` |
| human-gated write | authorization includes a recorded human-gate receipt |
| path traversal | unsafe write set is rejected before transport |
| authorization path escape | symlinked coordinator artifact outside the run root is rejected |
| replay | one submit, one explicit reconcile; no blind retry |
| transport ambiguity | typed `effect_unknown` |
| sensitive receipt | `RECEIPT_REDACTION_INVALID` and no accepted receipt |

The source-only gate is:

```bash
python scripts/authority_e2e.py selftest
python -m py_compile simplicio_loop/authority_boundary.py scripts/authority_e2e.py
```

An installed E2E result is considered `UNVERIFIED` until the `run` command is
executed in an environment where the three required packages are installed.
