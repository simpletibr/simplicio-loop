# Runbook — distributed-queue credentials, rotation, revocation, kill switch (#289)

- **Status:** operational
- **Owner:** security owner listed in `.github/security/distributed-trust-policy.json`'s
  `contacts` field per environment.
- **Scope:** the credential/transport surface described in issue #289 for
  `simplicio_loop.remote_queue.HTTPRemoteQueue` / `create_http_queue_server`,
  `simplicio_loop.secure_transport`, `scripts/distributed_trust_policy.py`, and
  `scripts/short_lived_credentials.py`.

This is the operational counterpart to `docs/adr/0003-distributed-proof-trust-boundaries.md`
(the *why*). This document is the *how* — what to do during rotation, an incident, or a
suspected compromise.

## 1. What is and is not implemented

| Control | Status |
|---|---|
| Enumerated `environment_id` → policy-resolved origin (no free-text URL/host/port/fingerprint from a caller) | Done (#320/#346) |
| Connect-time DNS pin + TLS handshake + measured-certificate pin check, zero redirects, proxy-env ignored | Done (#346, `simplicio_loop/secure_transport.py`) |
| Short-lived, revocable HMAC bearer credential (`exp`, `nbf`, `jti`, scope) | Done (#346, `scripts/short_lived_credentials.py`) |
| Static-token fallback is opt-in, not silent | Done (this change) — `SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1` required, every use audited |
| Operation-level credential scoping (`ops` claim, checked per queue operation) | Done (this change) |
| Structured audit log of every authorize/check_endpoint/verify_token decision | Done (this change) — `.simplicio-loop/orchestrator/security/audit-log.jsonl` |
| SPKI pin rotation with `current` + `next` | Done (this change) — `tls_sha256_pins` accepts `{"sha256","status"}` entries |
| Additional live negative/fault-injection tests (redirect, DNS rebinding, proxy injection) | Done (this change) — `tests/test_secure_transport_fault_injection.py` |
| **OIDC broker exchange (GitHub Actions issuer → broker → short-lived cloud/queue credential)** | **Permanently blocked.** The specific `.github/workflows/distributed-183-proof.yml` OIDC surface #289 was written against was removed in #311. The two current workflows (`simplicio-status-sync.yml` and `windows-progress-smoke.yml`) do not request `id-token: write`, provide no release/OIDC gate, and were not executed or used as evidence here. There is therefore no current source for the initial JWT this control depends on. This is not deferred pending more engineering time — it is architecturally unavailable until/unless a CI-hosted trigger with OIDC support is introduced, at which point this line item should be revisited from scratch, not resumed from partial work. |
| GitHub Environment protection / job separation for the proof workflow | Not applicable to the removed `distributed-183-proof.yml` (#311); the two current workflows do not implement this proof/release gate. |

## 2. Rotating a signing secret (`SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET`)

1. Generate a new random secret (32+ bytes, e.g. `openssl rand -hex 32`).
2. Update the secret in the environment/secret store the queue server and every legitimate
   worker read `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` from.
3. Restart the queue server (`create_http_queue_server(..., token_secret=<new>)`).
4. Restart/re-provision workers so they mint new tokens against the new secret.
   `_resolve_queue_token` in `simplicio_loop/runner.py` mints a fresh, short-TTL token per
   process — there is nothing else to "rotate" client-side, tokens already expire on their
   own (`max_ttl_seconds`, capped further by `SIMPLICIO_REMOTE_QUEUE_TOKEN_TTL_SECONDS`).
5. Confirm `python3 -m scripts.security_audit_log tail -n 20` shows fresh `accept` decisions
   after the restart and no `reject` entries citing the old secret's tokens as invalid beyond
   the expected cutover window.

## 3. Rotating the SPKI pin (certificate rotation)

`tls_sha256_pins` entries in `.github/security/distributed-trust-policy.json` may be either a
bare string (legacy shape, implicitly `"current"`) or `{"sha256": "<hex>", "status": "current"
| "next" | "retired"}`. Schema validation (`scripts/distributed_trust_policy.validate_schema`)
requires at least one `"current"` pin at all times.

1. **Before** rotating the certificate: add the *new* certificate's SHA-256 SPKI/leaf digest
   to the policy as a `"next"` entry, alongside the existing `"current"` entry. Get this PR
   reviewed by CODEOWNERS and merged — connections continue to authorize against the old
   `"current"` pin only, `"next"` is not yet accepted for a live connection unless it is also
   presented (it is checked as an *active* pin as soon as it is present with any non-`retired`
   status, so both certificates work simultaneously during rollout).
2. Deploy the new certificate to the queue server.
3. Once the new certificate is confirmed serving (`check_endpoint()` accepting connections
   with the new fingerprint, visible in the audit log as `pin_status: "next"`), open a second
   PR promoting the new pin's status to `"current"` and the old pin's status to `"retired"`.
4. A `"retired"` pin is rejected by `check_endpoint()` (`tls_sha256 does not match any active
   pin in the policy`) — this is deliberate: retiring closes the window rather than leaving a
   stale certificate acceptable indefinitely.
5. Confirm no `reject` audit entries reference the retired pin's fingerprint after cutover.

## 4. Revoking a specific credential (`jti`)

```bash
python3 scripts/short_lived_credentials.py revoke --jti <jti> \
  --revocation-store .simplicio-loop/orchestrator/security/revoked-jti.json
```

The revoked `jti` is rejected immediately by `verify_token()` (checked before any queue
mutation runs), independent of its `exp`. Find the `jti` for a suspicious session from the
audit log (`who`/`operation`/`jti` are logged; the token/secret itself never is):

```bash
python3 scripts/security_audit_log.py tail -n 100 | grep '"who": "<suspect-agent-id>"'
```

## 5. Kill switch

There is no separate "disable the queue" flag distinct from removing trust: to stop **all**
short-lived-credential issuance/acceptance for an environment immediately:

1. Rotate `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` (§2) without redistributing the new value to
   any worker yet. Every previously issued token fails signature verification the moment the
   server restarts with the new secret — this is the fastest full stop, faster than walking a
   revocation list.
2. If the static-token fallback (`SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1`) is in use anywhere
   (it should not be in production — see §6), unset `SIMPLICIO_REMOTE_QUEUE_TOKEN` and the
   opt-in flag and restart the queue server without a `token=`/`token_secret=` value the
   attacker's credential matches.
3. Remove or restrict the environment's entry in `.github/security/distributed-trust-policy.json`
   (empty `allowed_actors`/`allowed_repos`/`allowed_refs`, or delete the environment id
   entirely) so `authorize()` fails closed for every future call, independent of credential
   state.

## 6. Static-token fallback (deprecated, opt-in only)

`_resolve_queue_token` in `simplicio_loop/runner.py` no longer silently falls back to the
legacy static `SIMPLICIO_REMOTE_QUEUE_TOKEN` scheme when `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET`
is unset. It now raises `RuntimeError` unless `SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1` is also
set. If you see this error:

- **Preferred:** configure `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` instead (§2) — this is the
  only path production usage should take.
- **Local/dev only:** set `SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1` to explicitly accept the
  deprecated, indefinitely-lived shared-secret mode. Every use appends an audit-log line
  (`event: "runner.resolve_queue_token", decision: "accept", reason: "deprecated static-token
  auth mode explicitly opted into..."`) so this is discoverable in a security review, not
  invisible. This mode is not removed outright because local/dev workflows in this repo have
  no CI-issued identity to bootstrap a signing secret from automatically; hard-removing it
  would break those workflows entirely rather than degrade them safely.

## 7. Incident response checklist

1. Identify the affected `jti`/`sub`/`environment_id` from
   `.simplicio-loop/orchestrator/security/audit-log.jsonl` (never from a token value — tokens are never
   logged).
2. Revoke the specific `jti` (§4) and/or rotate the signing secret (§2/§5) depending on blast
   radius.
3. Check for `reject` entries immediately preceding the incident window with
   `event: "secure_transport.request_json"` and `event:
   "distributed_trust_policy.check_endpoint"` — these show whether the attacker's *connection
   attempt* (not just the credential) was already being blocked, which narrows whether this is
   a credential-only incident or a policy/pin gap.
4. If a pin mismatch or unexpected origin appears in the log, treat the policy file
   (`.github/security/distributed-trust-policy.json`) as compromised-adjacent: get CODEOWNERS
   to re-review the file's current content against the last known-good commit before trusting
   it further.
5. File a follow-up noting whether OIDC (permanently blocked per §1) would have prevented the
   incident — this is tracked evidence for revisiting that decision if a CI identity provider
   is ever reintroduced.

## 8. OIDC: why this stays permanently blocked, not merely deferred

Issue #289's architecture calls for a GitHub Actions OIDC token exchange: the workflow run
gets a short-lived `id-token: write` JWT from GitHub's own OIDC issuer, a broker validates
issuer/audience/repository/workflow ref/environment claims, and only then mints the queue
credential. That entire chain starts from a GitHub Actions job requesting the token — and
`.github/workflows/distributed-183-proof.yml`, the workflow in this repo that would have
requested it, was deleted in #311. The current `simplicio-status-sync.yml` and
`windows-progress-smoke.yml` workflows do not run with `id-token: write` against the distributed
queue and were not used as evidence here.

Implementing "OIDC support" without that starting point would mean either (a) building a fake
local OIDC issuer purely for this repo's tests, which proves nothing about the real GitHub
Actions trust chain and would misrepresent the acceptance criteria as met, or (b) reintroducing
a CI workflow whose removal (#311) was itself a deliberate decision this issue does not
re-litigate. Both are out of scope here. The correct status is: **this gap is real, it is
called out explicitly in every remaining-gap review, and it stays open** until a CI identity
provider exists in this repo again.
