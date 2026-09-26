# Remote queue contract (`simplicio.queue/v1`)

Operational runbook (starting/monitoring a worker, lease-expiry triage, the
receipt-verification failure reason codes, and the LOCAL_ONLY/REMOTE_READY/
REMOTE_MEASURED tri-state `scripts/doctor.py` reports): see
[`docs/REMOTE_WORKER_RUNBOOK.md`](REMOTE_WORKER_RUNBOOK.md).

The queue is the shared coordination boundary for Codex, Claude, Cursor, and
other runtimes. A task is mutated only while its lease is valid and its
fencing token is current. A worker that loses connectivity must pause and
produce a handoff; it must not continue mutating a checkout offline.

## Installed binaries (issue #286 step 11)

`pip install simplicio-loop` installs three console scripts backed by
`simplicio_loop/remote_queue_server_cli.py`, `simplicio_loop/remote_worker_cli.py`, and
`simplicio_loop/remote_worker_supervisor_cli.py` -- real, packaged binaries, not source that only
runs from a git checkout:

| Console script | What it runs |
|---|---|
| `simplicio-remote-queue-server` | the HTTP facade (same flags as `scripts/remote_queue_server.py`) |
| `simplicio-remote-worker` | the worker daemon (`claim`/`cancel`/`enqueue`/`serve` subcommands, same as `scripts/remote_worker_daemon.py`) |
| `simplicio-remote-worker-supervisor` | the lifecycle supervisor (same flags as `scripts/remote_worker_supervisor.py`) |

The historical `scripts/remote_queue_server.py`, `scripts/remote_worker_daemon.py`, and
`scripts/remote_worker_supervisor.py` remain as thin backward-compatible shims over these
modules for repo-local tooling/tests; the supervisor spawns its workers via
`python -m simplicio_loop.remote_worker_cli serve`, which resolves regardless of whether
`scripts/` is present on disk.

## Server-side receipt verification (issue #286 step 9)

`RemoteQueue.complete(lease, *, receipt_ref, receipt=None)` accepts an optional wire receipt in
addition to the historical opaque `receipt_ref` string. When `receipt` is supplied, the **queue
server itself** -- not merely the client presenting it -- independently:

1. runs it through `receipt_verifier.verify_receipt()` against
   `receipt_verifier.QUEUE_RECEIPT_SCHEMA` (schema literal, required fields, hash/tamper check,
   optional freshness window);
2. cross-checks the receipt's declared `task_id`/`agent_id`/`fencing_token` against the *active*
   lease presenting it.

A receipt that fails either check raises `QueueConflict` (HTTP 409) and leaves the task/lease
untouched -- fail closed, never a silent downgrade to "trust the ref". Both `RemoteWorkerDaemon`
(`simplicio_loop/worker_daemon.py`) and `AttemptCoordinator`
(`simplicio_loop/work_item_claims.py`) build this receipt automatically via
`simplicio_loop.remote_queue.build_completion_receipt`, so every genuine worker/coordinator
completion is now server-verified without any caller having to opt in. `receipt=None` still works
(existence-only, the pre-#286-step-9 contract) for callers that only exercise the lease/fencing
mechanics.

## Development backend

`simplicio_loop.remote_queue.SQLiteRemoteQueue` is a real transactional backend
for one machine or a shared filesystem that provides SQLite locking:

```python
from simplicio_loop.remote_queue import SQLiteRemoteQueue
q = SQLiteRemoteQueue(".simplicio-loop/orchestrator/shared-queue.db")
q.enqueue("issue-185", {"source": "github", "number": 185})
lease = q.claim("issue-185", "codex@laptop-a", idempotency_key="run:185")
lease = q.heartbeat(lease)
q.complete(lease, receipt_ref=".simplicio-loop/orchestrator/receipts/185.json")
```

Claims are idempotent by `idempotency_key`; expired leases are reclaimable and
increment a fencing token. Every transition appends a monotonic event, so a
reconnecting client can call `events(after=last_seq)` and reconcile without
guessing state. The backend never silently falls back when the store is
unavailable (`QueueUnavailable`).

## HTTP network adapter

The repository now ships a stdlib-only HTTP facade and client. The server keeps
the SQLite transaction boundary authoritative while clients on separate
machines use the same claim/lease/fencing protocol:

```powershell
python scripts/remote_queue_server.py --db .simplicio-loop/orchestrator/shared-queue.db --host 0.0.0.0 --port 8765 --token "$env:SIMPLICIO_QUEUE_TOKEN"
```

Network-facing binds are fail-closed unless TLS is configured. Provide a certificate and
private key (TLS 1.2 or newer) through flags or environment variables:

```powershell
$env:SIMPLICIO_QUEUE_TLS_CERTFILE = "C:\\etc\\simplicio\\queue.crt"
$env:SIMPLICIO_QUEUE_TLS_KEYFILE = "C:\\etc\\simplicio\\queue.key"
python scripts/remote_queue_server.py --host 0.0.0.0 --port 8765
```

Plain HTTP is supported only on loopback for local tests. Production deployments still require
a firewall/network policy, token rotation, and a trusted certificate chain.

```python
from simplicio_loop.remote_queue import HTTPRemoteQueue
q = HTTPRemoteQueue("https://queue.example.internal", token=os.environ["SIMPLICIO_QUEUE_TOKEN"])
lease = q.claim("issue-185", "claude@machine-b", idempotency_key="run:185")
q.complete(lease, receipt_ref="receipts/185.json")
```

Authentication is required when the server is configured with `--token`; every
transport failure raises `QueueUnavailable` and therefore pauses mutation. A
stale lease remains rejected by the server's SQLite fencing check. Do not use
GitHub issue labels as a lock. For production, put the service behind TLS and a
network policy; Redis/SQL service implementations can target the same protocol.

### Measured local multi-worker proof

The live transport test starts the HTTP facade and then uses two independent
spawned Python processes (one Codex-style identity and one Claude-style
identity). It verifies bearer-token rejection, one atomic winner, expiry
reclaim with a higher fencing token, stale completion rejection, monotonic
event replay, and the completion `receipt_ref`:

```powershell
python -m pytest -q tests/test_remote_queue_live.py tests/test_remote_queue.py
```

This is a local process-isolation proof of the wire contract. It does **not**
claim TLS termination, firewall policy, or a live deployment on separate
physical machines; those remain deployment acceptance gates.

## Worker daemon: heartbeat loop + cooperative cancellation (issue #286)

`simplicio_loop.worker_daemon.RemoteWorkerDaemon` is a standalone worker that discovers
(`pull`), claims, and heartbeats a task on its own -- independent of any local
coordinator -- for the life of an arbitrarily long unit of work (not just a bounded
subprocess). A background thread heartbeats every `heartbeat_interval` seconds; the
moment the queue reports the lease cancelled (`RemoteQueue.request_cancel`) or the
heartbeat itself fails (reclaimed lease / unreachable queue), the worker's cooperative
`work_fn` is signalled to stop and the outcome is reported as `"cancelled"` or
`"lease_lost"` respectively -- never silently completed under a stale fence:

```python
from simplicio_loop.remote_queue import SQLiteRemoteQueue
from simplicio_loop.worker_daemon import RemoteWorkerDaemon, sleep_in_slices

queue = SQLiteRemoteQueue(".simplicio-loop/orchestrator/shared-queue.db")
worker = RemoteWorkerDaemon(queue, agent_id="codex@laptop-a", heartbeat_interval=1.0, lease_ttl=5.0)
lease = worker.try_claim("issue-185", idempotency_key="run:185")

def work(check_cancelled):
    return {"finished": sleep_in_slices(30.0, slice_seconds=0.1, check_cancelled=check_cancelled)}

outcome = worker.run_task(lease, work, receipt_ref=".simplicio-loop/orchestrator/receipts/185.json")
# outcome.status is one of "completed" | "cancelled" | "lease_lost"
```

A cancellation is issued from any other process against the shared queue and is
scoped to the current fencing token (it does not "stick" to a future reclaim):

```python
queue.request_cancel("issue-185", reason="operator requested stop")
```

`scripts/remote_worker_daemon.py claim --db ... --agent-id ... --task-id ...` and
`scripts/remote_worker_daemon.py cancel --db ... --task-id ...` wrap the same class as a
standalone CLI process, used by the real (not mocked) two-OS-process end-to-end test:

```powershell
python -m pytest -q tests/test_remote_worker_e2e.py tests/test_worker_daemon.py tests/test_remote_queue_cancellation.py
```

`tests/test_remote_worker_e2e.py` spawns two genuine `subprocess.Popen` processes
against one shared SQLite file and proves, without mocking any of it: process A claims
and heartbeats a task; process B's claim of the same task is rejected while A's lease is
alive; process A is `kill()`ed mid-task (a real crash, no graceful release); process B
then successfully claims and completes the same task once A's lease genuinely expires.
A second scenario proves cooperative cancellation across three real processes (claimant,
canceller, and the queue file) without killing anything.

### Trust-policy hardening for network destinations (issue #289)

Setting `SIMPLICIO_REMOTE_ENVIRONMENT_ID` on the `simplicio_loop.runner` side
(see `_distributed_configuration`) turns the queue destination into a
policy-resolved, enumerated `environment_id` instead of a freeform URL
(`.github/security/distributed-trust-policy.json`, `scripts/distributed_trust_policy.py`).
Once that's set:

* `HTTPRemoteQueue` requires every request to pass `check_endpoint()` -- DNS
  resolved once and pinned to the connection to avoid rebinding, disallowed
  addresses (loopback/link-local/private/metadata) rejected before connecting,
  zero HTTP redirects, and the *measured* TLS leaf certificate hashed and
  compared against the policy's pins -- before any bearer token is written to
  the socket (`simplicio_loop.secure_transport`).
* The bearer credential itself can be short-lived instead of a static secret:
  set `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` (an HMAC signing secret, never
  sent on the wire) and the runner mints a fresh token per process via
  `scripts/short_lived_credentials.py`, bound to the worker's agent identity
  and the environment_id, expiring in `max_ttl_seconds` (or
  `SIMPLICIO_REMOTE_QUEUE_TOKEN_TTL_SECONDS` if lower) and restricted to
  `runner.WORKER_QUEUE_OPERATIONS` (pull/claim/heartbeat/complete/... --
  never `enqueue`; see "Operation-level credential scoping" below). Run the
  queue server with `--token-secret`/`--token-scope`/`--revocation-store` (or
  the matching `SIMPLICIO_QUEUE_*` env vars) to verify it and support
  immediate revocation by `jti` (`scripts/short_lived_credentials.py revoke`).
* The legacy static `SIMPLICIO_REMOTE_QUEUE_TOKEN` is **not** a silent
  fallback when `SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET` is unset: the runner
  raises `RuntimeError` unless `SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1` is also
  set, and every use of the opt-in path appends a line to the audit log
  (`.simplicio-loop/orchestrator/security/audit-log.jsonl`, `scripts/security_audit_log.py`)
  so an indefinitely-lived shared secret in production is discoverable, not
  invisible.
* Operation-level credential scoping: a short-lived token's `ops` claim (set
  via `issue_token(..., operations=[...])`) is checked per-operation on the
  server (`create_http_queue_server`/`verify_token(expected_operation=...)`)
  -- a token scoped to `pull` does not authorize `claim`/`complete` even
  though its coarser environment `scope` claim matches.
* Authorization decisions are audited: `distributed_trust_policy.authorize()`
  / `.check_endpoint()`, `secure_transport.request_json()`, and
  `short_lived_credentials.verify_token()` each append a structured line
  (who/what/when/verdict/reason, never the credential itself) to the #289
  audit log; see `docs/security/distributed-credentials-runbook.md`.
* `tls_sha256_pins` supports a `current`+`next` rotation set: entries may be
  either bare strings (implicit `current`, legacy shape) or
  `{"sha256": "...", "status": "current"|"next"|"retired"}`, so a certificate
  rotation adds the new pin as `next` before the certificate changes, then
  promotes it once the rotation is live -- no single commit has to change the
  policy and the certificate at the same instant.
* This is not the full OIDC broker exchange #289 describes (no CI identity
  provider exists in this repo to issue the initial trust -- **this gap is
  permanently blocked** absent a CI identity provider and is not attempted
  here), and job separation / GitHub Environment protection do not apply now
  that `.github/workflows/distributed-183-proof.yml` has been removed (#311)
  -- see the issue thread and
  `docs/security/distributed-credentials-runbook.md` for the current,
  re-scoped remaining gaps.

### The coordinator no longer executes remotely-dispatched tasks itself (issue #286)

`simplicio_loop.runner._operator_dispatch_attempt` used to claim and call `execute_operator()`
in its own process regardless of which `RemoteQueue` backend was configured -- so a real,
networked `HTTPRemoteQueue` never actually left the coordinator's process. It now switches on
the queue's *type*: `SQLiteRemoteQueue` keeps the co-located, guarded-dispatch path from #288
unchanged; a real `HTTPRemoteQueue` takes the new `_operator_dispatch_attempt_remote_worker`
path instead, which only enqueues the `simplicio.remote-worker/v2` task envelope
(`contracts/remote-worker/v2/schema.json`) and polls `queue.task()` for a terminal `completed`
status -- it never claims and never calls `execute_operator()`. See
`docs/adr/0002-remote-worker-v2-protocol.md` for the full rationale, and opt back into the old
in-process shortcut only for a deliberate same-host smoke test via
`SIMPLICIO_REMOTE_WORKER_ONLY=0`.

### Worker-daemon lifecycle supervisor (issue #286)

`scripts/remote_worker_supervisor.py` runs as its own OS process, spawns `--workers` real
`scripts/remote_worker_daemon.py serve` child processes, polls each child's liveness every
`--health-interval` seconds, and respawns any child that has exited -- crashed, killed, or
otherwise -- after `--restart-backoff-seconds`:

```powershell
python scripts/remote_worker_supervisor.py --db .simplicio-loop/orchestrator/shared-queue.db --workers 3 --status-dir .simplicio-loop/orchestrator/worker-status
```

`tests/test_remote_worker_supervisor.py` hard-kills a real supervised worker process by PID
(discovered only through the status file the supervisor writes, exactly as an operator would
find it) and proves the supervisor detects the exit, spawns a genuinely new PID, and that the
*new* worker actually completes a real task -- not merely stays alive.

### Real HTTP client/server two-process proof (issue #286)

`tests/test_remote_worker_http_e2e.py` removes even the shared-SQLite-file proxy: it spawns
`scripts/remote_queue_server.py` as its own OS process bound to `127.0.0.1` on an OS-assigned
port, then drives `scripts/remote_worker_daemon.py`'s `claim`/`cancel`/`enqueue` subcommands
(`--http URL`) as separate OS processes making real HTTP requests over that loopback socket --
the closest achievable local proxy for two physically separate devices without a second
machine. Every claim, heartbeat, cancel, and complete crosses a real TCP connection between two
independent processes.

```powershell
python -m pytest -q tests/test_remote_worker_http_e2e.py tests/test_remote_worker_supervisor.py
```

### Receipt verification wired into the remote-queue completion path (issue #288)

`work_item_claims.AttemptCoordinator.accept_receipt(..., schema=...)` now optionally runs
the bound receipt through `receipt_verifier.verify_receipt` (schema/hash/freshness/
provenance) before recording it, and `AttemptCoordinator.verify_and_complete(...)` gates
the queue's `complete()` transition on a `VERIFIED` verdict -- a non-`VERIFIED` result
raises `ReceiptVerificationFailed` and leaves the lease active instead of silently
transitioning the task to `completed`. `schema=None` preserves the pre-#286
existence-only behavior for callers that have not adopted a schema yet.
