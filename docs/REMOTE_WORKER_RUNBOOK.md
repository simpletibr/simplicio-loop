# Remote worker runbook (issue #286)

This is the operational companion to [`docs/REMOTE_QUEUE.md`](REMOTE_QUEUE.md) (the
protocol/contract doc). That doc describes *what* the remote-worker protocol is; this
doc is for the person on call: how to start a worker, how to tell if it's healthy, what
to do when a lease expires unexpectedly, and how to read a receipt-verification
failure.

Scope note up front: everything here runs today on a single physical machine using
loopback HTTP and/or a shared SQLite file as the "network." The wire protocol, fencing,
heartbeat, cancellation, and server-side receipt verification are real and exercised by
genuine separate OS processes (`tests/test_remote_worker_http_e2e.py`,
`tests/test_remote_worker_e2e.py`). A genuine two-**physical**-machine run has not been
performed in this environment (see "Two-machine status" below) — track that
distinction with `scripts/doctor.py` / `scripts/remote_worker_measurement.py`, not by
assuming a passing local E2E test proves cross-device operation.

## 1. Starting a worker

Minimum viable local setup: a queue server plus one or more workers pointed at it.

```powershell
# 1. Start the queue server (the state/lease/fencing authority)
python scripts/remote_queue_server.py --db .simplicio-loop/orchestrator/shared-queue.db `
    --host 127.0.0.1 --port 8765 --token $env:SIMPLICIO_QUEUE_TOKEN

# 2. Point a worker at it and claim/serve tasks
python scripts/remote_worker_daemon.py serve --http http://127.0.0.1:8765 `
    --token $env:SIMPLICIO_QUEUE_TOKEN --agent-id "worker-a" `
    --status-file .simplicio-loop/orchestrator/worker-status/worker-a.json
```

Or run several workers under the lifecycle supervisor, which respawns any child that
exits (crash, kill, or otherwise):

```powershell
python scripts/remote_worker_supervisor.py --db .simplicio-loop/orchestrator/shared-queue.db `
    --workers 3 --status-dir .simplicio-loop/orchestrator/worker-status
```

Once installed via `pip install simplicio-loop`, the same binaries are available as
packaged console scripts instead of repo-local paths (`docs/REMOTE_QUEUE.md` § "Installed
binaries"):

```powershell
simplicio-remote-queue-server --db .simplicio-loop/orchestrator/shared-queue.db --host 127.0.0.1 --port 8765
simplicio-remote-worker serve --http http://127.0.0.1:8765 --agent-id worker-a
simplicio-remote-worker-supervisor --db .simplicio-loop/orchestrator/shared-queue.db --workers 3
```

Before starting anything in a real environment, run the doctor check — it tells you
whether the remote-worker capability is even configured on this machine, without
starting any process:

```powershell
python scripts/doctor.py --json | python -c "import json,sys; print(next(i for i in json.load(sys.stdin) if i['name'].startswith('remote worker')))"
```

## 2. Monitoring worker health

Three signals, cheapest first:

1. **Status file** (`--status-file`/`--status-dir`). Every worker daemon and the
   supervisor write a JSON status file on every state transition
   (`claimed`/`running`/`completed`/`cancelled`/`lease_lost`). This is the cheapest,
   fully offline health check — read the file, don't guess from process liveness alone.
2. **Supervisor liveness poll.** `scripts/remote_worker_supervisor.py` polls each
   child's PID every `--health-interval` seconds and respawns anything that exited. If
   you are running workers under the supervisor, "is a worker up" is answered by
   `ls .simplicio-loop/orchestrator/worker-status/` plus the supervisor's own log line for each
   restart, not by manually watching PIDs.
3. **Queue events.** `RemoteQueue.events(after=last_seq)` (or
   `HTTPRemoteQueue.task(task_id)` for one task) gives the monotonic event trail the
   server itself recorded — claims, heartbeats, cancellations, completions. This is the
   source of truth when a status file and the server's view disagree (e.g. after a
   worker crash where the local status file is the last thing written before the kill).

Metrics the epic calls for (queue depth, pull latency, claim conflicts, active leases,
heartbeat lag, expirations, retries, cancellations, stale-receipt rejects) are **not**
wired into a metrics backend in this repo — there is no metrics sink (Prometheus/OTel/etc.)
configured here to receive them. Until one exists, the queue's own event log
(`events()`) is the closest available proxy: every one of those occurrences is a
distinct, timestamped event kind you can `grep`/aggregate from `events()` output. Treat
"real observability dashboard" as a still-open gap, not solved by this runbook.

## 3. A lease expired unexpectedly — what to do

A lease "expiring unexpectedly" means the worker's heartbeat stopped renewing it before
the work finished, and another worker (or the same one, on retry) reclaimed the task
with a new, higher fencing token. This is not silent data loss — the server made a
deliberate choice: **never allow a stale worker to keep mutating state after its lease
lapsed.**

Diagnostic steps, in order:

1. **Check the status file first.** If it shows `"state": "lease_lost"`, the worker's
   own heartbeat thread detected the loss (`simplicio_loop/worker_daemon.py`,
   `RemoteWorkerDaemon.run_task`) and the worker is correctly *not* attempting to
   complete or release the lease it no longer holds — that would either steal the
   reclaimer's lease back or emit a confusing duplicate event. Nothing to fix on the
   worker side; move to step 2 to find out why the heartbeat stopped.
2. **Find out why the heartbeat missed its window.** Common causes, cheapest to check
   first:
   - The worker process was starved (CPU/GC pause, or the work function was blocking
     the interpreter instead of yielding) longer than `lease_ttl`. Fix: raise
     `--ttl`/`lease_ttl` relative to expected pause length, or make the work function
     truly cooperative (see `sleep_in_slices` in `simplicio_loop/worker_daemon.py` for
     the pattern — poll `check_cancelled()`, don't block).
   - The queue became unreachable (network blip, server restart). `HTTPRemoteQueue`
     raises `QueueUnavailable` on any transport failure, which the daemon treats
     identically to a lost lease — check the queue server's own logs/uptime for the
     window in question.
   - `heartbeat_interval` was set too close to `lease_ttl`. The daemon enforces
     `heartbeat_interval < lease_ttl` at construction time specifically so at least one
     heartbeat lands before expiry under normal conditions; if you're tuning these
     values, keep a healthy margin (the codebase's own default is `interval <= ttl/3`).
3. **Confirm the reclaim, don't assume it.** Query `queue.task(task_id)` (or
   `events(after=...)`) and look at the `fencing_token` — it must be strictly greater
   than the one the lost worker held. If it is not higher, something is wrong with the
   queue backend itself (file corruption, concurrent-access bug) — that is a queue-level
   incident, not a worker misconfiguration, and should not be worked around by manually
   forcing state.
4. **Never manually "fix" a `claimed` task stuck past its TTL by hand-editing the
   store.** The whole point of server-side fencing is that reclaim is safe and
   automatic; a manual edit bypasses the fencing token bookkeeping and can produce two
   workers that both believe they hold the lease.
5. **Re-queue vs. give up.** `failed_retryable` tasks and expired/`released` leases are
   designed to go back to `queued` with a new `attempt_id`/fencing token
   automatically on the next `claim`/`pull` cycle — you do not need to manually
   re-enqueue unless the task was already marked terminal (`completed`,
   `failed_terminal`, `cancelled`).

## 4. Receipt-verification failure reason codes (issue #395 / #288)

`simplicio_loop/receipt_verifier.py::verify_receipt()` returns a `ReceiptVerdict` with
one of five statuses (`ReceiptStatus`). Only `VERIFIED` is safe to treat as "done."
`RemoteQueue.complete(lease, receipt_ref=..., receipt=...)` runs every wire receipt
through this same validator **server-side** before transitioning a task to
`completed` — a receipt that fails raises `QueueConflict` (HTTP 409) and leaves the
task/lease untouched, never a silent downgrade to "trust the ref."

| Status | Meaning | What to do |
|---|---|---|
| `VERIFIED` | Schema, hash, freshness, and provenance all checked out. | Nothing — this is the only status safe to treat as done. |
| `MISSING_FIELD` | A required field (or a declared provenance field) is absent, empty, or `null`. The reason string names the exact field path(s). | Fix the receipt builder — `simplicio_loop.remote_queue.build_completion_receipt` (or the worker's own receipt construction) is omitting or blanking a field the schema requires. This usually means a caller is not using the standard receipt builder, or is constructing a partial receipt for testing and shouldn't be presenting it to `complete()`. |
| `INVALID_SCHEMA` | A field with a fixed expected value (e.g. `schema: "simplicio.queue-receipt/v1"`) doesn't match, or a freshness timestamp couldn't be parsed. | Check the receipt's `schema` literal against the schema the caller passed to `verify_receipt`/`complete` — a version mismatch (old client, new server schema, or vice versa) is the most common cause. Do not silently downgrade a schema check to pass; fix the version mismatch or bump the schema deliberately. |
| `TAMPERED` | The recomputed content hash doesn't match the receipt's declared hash, OR the receipt's timestamp is more than 60s in the future (clock-skew allowance). | Treat this as a security-relevant event, not a retry-and-hope case: something modified the receipt after it was hashed, or a clock is significantly wrong. Check the audit log (`.simplicio-loop/orchestrator/security/audit-log.jsonl`, `scripts/security_audit_log.py`) and the worker's own NTP/clock sync before assuming benign clock drift. |
| `STALE` | The receipt's age (`checked_at - measured_at`) exceeds the caller's `max_age_seconds`. | The receipt was genuine but presented too late (e.g. a long queue/retry delay between the worker finishing and the completion call landing). Re-run the unit of work rather than force-accepting an old receipt — a stale receipt no longer proves the *current* repo/commit state matches what was measured. |

The reason string on every non-`VERIFIED` verdict is intentionally specific (exact
field names, the declared vs. recomputed hash, the exact age vs. threshold) — surface it
verbatim in logs/alerts rather than collapsing it to a boolean, since the reason is what
tells you which of the five remediation paths above applies.

## 5. Two-machine status

As of this writing, every remote-worker proof in this repository (`tests/test_remote_worker_e2e.py`,
`tests/test_remote_worker_http_e2e.py`, `tests/test_remote_worker_supervisor.py`) runs
**multiple genuine OS processes on one physical machine** — real process isolation,
real crashes (`kill()`), real TCP sockets over loopback, but one box. That is real
evidence the *protocol* is correct; it is not the epic's stated acceptance criterion
("a task created on one device is discovered/claimed/executed by a worker on a
different device").

`scripts/doctor.py`'s "remote worker (#286)" check and
`scripts/remote_worker_measurement.py` track this honestly with a tri-state, never
inferring the strongest claim from source code merely existing:

| State | Meaning |
|---|---|
| `LOCAL_ONLY` | No remote queue destination configured (`SIMPLICIO_REMOTE_QUEUE_URL`/`SIMPLICIO_REMOTE_ENVIRONMENT_ID` both unset). The default, and not a failure. |
| `REMOTE_READY` | A remote queue destination is configured, but this checkout has never recorded a passing cross-process proof. |
| `REMOTE_MEASURED` | A real proof (`tests/test_remote_worker_http_e2e.py` or better) has actually run and recorded a measurement receipt. |

```powershell
python scripts/remote_worker_measurement.py status --json
python scripts/remote_worker_measurement.py record   # re-runs the HTTP E2E for real; only records on a genuine pass
python scripts/remote_worker_measurement.py clear     # force a fresh re-proof
```

A genuine two-physical-machine run — e.g. one laptop running
`scripts/remote_queue_server.py` bound to a routable (not loopback) address behind TLS,
and a second, physically separate machine running `scripts/remote_worker_daemon.py`
against it over the real network — is recorded as its own tier and is **never**
fabricated automatically:

```powershell
python scripts/remote_worker_measurement.py record --proof physical-two-machine `
    --note "server on host-a (192.168.x.x), worker on host-b, observed claim/heartbeat/complete over real LAN on <date>"
```

There is currently no second physical machine available in this development
environment to perform that run (checked: single NIC on a private LAN with no other
discovered host, no `~/.ssh/config` entries, no WSL distribution installed, no local
Docker daemon). This gap is tracked, not closed, by design — `record --proof
physical-two-machine` exists precisely so a genuine run can be captured the moment
one becomes available, instead of the strongest claim being asserted without ever
having been true.
