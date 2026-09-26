# ADR-0003 — Distributed-proof trust boundaries: remaining #289 gaps closed, OIDC permanently blocked

- **Status:** accepted
- **Date:** 2026-07-15
- **Relates to:** issue #289 (security P0), PR #320 (trust-policy resolver + connect-time
  DNS/TLS enforcement), PR #346 (short-lived HMAC credentials + revocation, secure transport,
  CODEOWNERS), PR #363 (wiring `AttemptCoordinator`/`MergeExecutor`), issue #311 (removal of
  `.github/workflows/distributed-183-proof.yml`), issues #183/#286/#287 (dependents blocked on
  this gate).

## Context

Issue #289's threat model is: `workflow_dispatch` inputs (queue URL, TLS hostname, TLS
fingerprint) chose the destination a real bearer token was sent to, mixing untrusted input
with a privileged credential (direct exfiltration) and letting less-trusted code redirect a
privileged runner against an unintended endpoint (confused deputy). The full architecture the
issue specifies is: a versioned, CODEOWNERS-reviewed trust policy; job separation with
`permissions: {}` by default; GitHub Environment protection; an OIDC broker exchange for
short-lived cloud/queue credentials; DNS/TLS/pin hardening at connect time; structured audit
logging; and an offensive test suite covering redirects, DNS rebinding, proxy injection, and
more.

PRs #320/#346/#363 closed most of this for the surface that actually exists in this repo
today (`simplicio_loop.remote_queue.HTTPRemoteQueue` / `create_http_queue_server`, not the
now-deleted workflow). What remained open going into this change:

1. `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` unset silently fell back to the legacy static
   `SIMPLICIO_REMOTE_QUEUE_TOKEN` scheme with no warning and no way to discover that the weaker
   mode was in use.
2. A short-lived credential's `scope` claim was environment-level only (e.g. `"staging"`); a
   token was not restricted to specific queue operations, so a `pull`-only worker's leaked
   token could still `claim`/`complete` tasks.
3. Every accept/reject decision (`secure_transport.request_json`, `distributed_trust_policy
   .authorize`/`.check_endpoint`, `short_lived_credentials.verify_token`) happened silently —
   no durable record of who/what/when/verdict/reason existed to support an incident
   investigation.
4. `tls_sha256_pins` was a flat list with no formalized "current vs. next" rotation state, so a
   certificate rotation required the policy PR and the certificate deployment to land at
   effectively the same instant to avoid an outage.
5. The negative test suite exercised the policy functions in isolation (mocked DNS, unit
   assertions) but had no live proof against a real redirect response, a simulated DNS-rebind
   sequence, or an injected proxy environment variable.
6. No single document tied the above together operationally, or stated in one place, with
   rationale, that the OIDC broker exchange remains unimplemented and why.

## Decision

Close gaps 1–5 as scoped, additive changes to the existing modules rather than a rewrite, and
add gap 6 as `docs/security/distributed-credentials-runbook.md`. Concretely:

- **Static-token fallback is opt-in, not silent** (`simplicio_loop/runner.py
  ::_resolve_queue_token`). Without `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` set, resolving a
  queue token now raises `RuntimeError` unless the caller also sets
  `SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1`; every use of the opt-in path appends a line to the
  new audit log. This is a breaking change for any deployment silently relying on the old
  fallback — deliberately so; the alternative (leaving it silent) is the exact gap being
  closed.

- **Operation-level credential scoping** (`scripts/short_lived_credentials.py::issue_token`/
  `verify_token`, `simplicio_loop/remote_queue.py::create_http_queue_server`). Tokens may now
  carry an optional `ops` claim (a list of allowed queue operations); `verify_token(...,
  expected_operation=...)` rejects a presented token whose `ops` claim does not include the
  operation being attempted. `simplicio_loop.runner` mints worker tokens scoped to
  `WORKER_QUEUE_OPERATIONS` (`pull`, `claim`, `heartbeat`, `complete`, `assert-active`,
  `cancel`, `release`, `events`, `task` — deliberately excluding `enqueue`, since workers
  consume tasks, they do not create them). Tokens without an `ops` claim remain unrestricted
  (legacy shape) — this is additive, not a breaking change to tokens already in flight.

- **Structured audit logging** (new `scripts/security_audit_log.py`). One JSON line per
  accept/reject decision, appended (never overwritten) to
  `.simplicio-loop/orchestrator/security/audit-log.jsonl` by default. Wired into
  `secure_transport.request_json`, `distributed_trust_policy.authorize`/`.check_endpoint`, and
  `short_lived_credentials.verify_token`. Never logs the credential or signing secret itself —
  only identifiers (`who`, `operation`, `jti`, `scope`, `pin_status`, `reason`). Writing is
  best-effort (a full disk must not turn a fail-closed decision into a silent pass); the
  decision itself is made and enforced independent of whether the audit line was
  successfully written.

- **SPKI pin rotation with `current` + `next`** (`scripts/distributed_trust_policy.py`).
  `tls_sha256_pins` entries may now be `{"sha256": "...", "status": "current"|"next"|
  "retired"}` in addition to the legacy bare-string shape (implicitly `"current"`). Schema
  validation requires at least one `"current"` pin. `check_endpoint()` accepts any pin whose
  status is not `"retired"`, so a `"next"` pin authorizes connections as soon as it is
  declared — letting a certificate rotation add the new pin, deploy the certificate, then
  promote/retire, without a single atomic cutover.

- **Additional live negative/fault-injection tests**
  (`tests/test_secure_transport_fault_injection.py`): a real local HTTPS server answering with
  a 302 to an attacker-controlled origin (proves zero-redirect enforcement against a genuine
  HTTP response, not a mock); a DNS-rebinding simulation proving `resolve_pinned_address`
  performs exactly one lookup and the subsequent connection targets only that resolved
  address, never a second (potentially rebound) answer; and a live request against a real
  queue server with `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY` pointed at an unreachable address,
  proving the request still succeeds by connecting directly (proxy env vars are never
  consulted).

- **OIDC broker exchange: permanently blocked, re-confirmed.** This ADR does not attempt it
  and explicitly does not treat it as "todo, later" — see
  `docs/security/distributed-credentials-runbook.md` §8 for the full rationale. In short: the
  one workflow that would request the initial GitHub Actions OIDC JWT
  (`.github/workflows/distributed-183-proof.yml`) was removed in #311, and no other CI-hosted
  trigger in this repo runs with `id-token: write` against the distributed queue. There is no
  substrate to exchange. A local fake OIDC issuer would not validate anything about the real
  GitHub Actions trust chain and would misrepresent this criterion as met. This item stays
  open until a CI identity provider exists in this repo again.

## Consequences

- Any deployment currently relying on the silent static-token fallback will see
  `_resolve_queue_token` start raising `RuntimeError` after this change lands, until it either
  configures `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` or sets the explicit opt-in flag. This is
  the intended forcing function.
- `.simplicio-loop/orchestrator/security/audit-log.jsonl` is a new, growing, append-only file. It is not yet
  size-bounded or rotated by this change — operators running a long-lived queue server should
  add log rotation (e.g. `logrotate`, or a periodic archive-and-truncate script) as an
  operational follow-up; this ADR does not implement that.
- Tokens minted by `simplicio_loop.runner._resolve_queue_token` are now scoped to
  `WORKER_QUEUE_OPERATIONS` by default. Any caller that expected a worker token to also
  authorize `enqueue` (there should be none in the current codebase — workers only consume
  tasks) would need `operations` extended explicitly.
- Issue #289 is **not** closed by this change: the OIDC gap, full job separation, and GitHub
  Environment protection remain out of reach absent the removed workflow and a CI identity
  provider. This ADR documents that state so it is a deliberate, re-confirmed decision each
  time the issue is reviewed, not a silently stale TODO.
