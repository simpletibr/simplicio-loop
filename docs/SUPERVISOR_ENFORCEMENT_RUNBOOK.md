# Supervisor enforcement runbook + threat model (issue #516)

Parent epic: [#498](https://github.com/wesleysimplicio/simplicio-loop/issues/498) — one
Process Supervisor for every process the Simplicio ecosystem starts. This doc covers
[#516](https://github.com/wesleysimplicio/simplicio-loop/issues/516): detection of
out-of-supervisor processes, the `status`/`top`/`queue`/`cancel`/`drain`/`reports` CLI
surface, opt-in enforcement, and a circuit breaker with standalone fallback.

**Scope note, up front:** this is the first real slice, not the full #498 DoD. It is
built on the already-merged [#514](https://github.com/wesleysimplicio/simplicio-loop/issues/514)
Python `ProcessSpec`/`ProcessLease`/`ProcessResult` contract
(`simplicio_loop/process_supervisor.py`) and works standalone with the Python adapter —
it does **not** assume the Rust/Tokio backend from
[#515](https://github.com/wesleysimplicio/simplicio-loop/issues/515) exists. See
"Implemented now vs. deferred" below for an honest line between what this slice proves
and what the epic still needs.

## What's implemented now

| Capability | Module | Real, tested behavior |
|---|---|---|
| Detector | `simplicio_loop/process_enforcement.py` — `scan_host_processes`, `is_simplicio_cmdline`, `detect_unsupervised` | Enumerates live OS processes (`/proc/<pid>/cmdline` on Linux, `ps -axo pid=,args=` fallback elsewhere on POSIX) and flags any whose argv matches a Simplicio-ecosystem signature (`SIMPLICIO_SIGNATURES`) but whose pid is not in the supervisor's own bookkeeping (`ProcessRegistry`). |
| Bookkeeping | `ProcessRegistry` | A JSON file (default `.simplicio-loop/orchestrator/supervisor/registry.json`) recording pid → lease_id/spec_hash/argv for every process currently running through `SupervisedProcessAdapter`. Persisted so a separate CLI invocation can read it. Stale entries (pid reused after a crash) are pruned via `os.kill(pid, 0)` liveness probing on every read. |
| Supervised spawn | `SupervisedProcessAdapter` | Wraps the #514 `PythonProcessAdapter`. Uses a new, additive `on_spawned` hook on `PythonProcessAdapter.run()` (backward compatible — default `None`, existing #514 tests unchanged) to register the real OS pid the instant it's known, and unregisters it when the process ends. |
| CLI | `simplicio_loop/process_enforcement_cli.py` (`python -m simplicio_loop.process_enforcement_cli ...`) | `status` (enforcement mode + active count + breaker state), `top` (active supervised processes with pid/lease/age), `queue` (in-flight leases — see caveat below), `cancel --pid/--lease-id` (real SIGTERM), `drain --timeout [--force]` (waits for leases to finish; `--force` SIGTERMs stragglers), `reports [--scan] [--limit]` (replay a JSONL event log, or run + log a fresh detection pass). |
| Enforcement mode | `enforcement_enabled()` / `enforce()` | **Opt-in, default OFF** (`SIMPLICIO_SUPERVISOR_ENFORCE=1` to turn on). Off: `enforce()` only reports what it *would* do (`action: "observed_only"`), never sends a signal — proven by a test that spawns a real flagged process and asserts it is still alive afterward. On: `enforce()` sends a real `SIGTERM` to flagged pids — proven by a test that spawns a real flagged process and asserts it is actually gone afterward. |
| Circuit breaker | `CircuitBreaker` | Trips **OPEN** after `failure_threshold` (default 3) *consecutive* supervised-spawn failures classified as `spawn_error`/`executable_not_found` (not ordinary non-zero exit codes from the user's own command — that's a documented, narrow trip condition, not "anything failed"). Moves to `half_open` after `cooldown_seconds`; a subsequent success closes it. State persists to disk (`breaker.json`) so the CLI can report it across invocations. |
| Fallback | `run_guarded()` | When the breaker is OPEN, subsequent work runs through a **plain, unsupervised** `PythonProcessAdapter` (still argv-only/spec-validated, just not registered) instead of being refused — proven by a test where, after two forced failures trip the breaker, a *good* spec still executes successfully via `mode: "standalone_fallback"`. |

All of the above is exercised by `tests/test_process_enforcement.py` with **real
subprocesses** (never mocked): a canary spawned outside the supervisor is shown to be
flagged; the same kind of process spawned through `SupervisedProcessAdapter` is shown
NOT to be flagged while it's still running; enforcement-off is shown to leave a flagged
process alive; enforcement-on is shown to actually terminate one; the breaker is shown
to trip and to still complete new work via fallback; the CLI subcommands are exercised
end-to-end as a real subprocess against a real registry file.

```bash
python3 -m pytest tests/test_process_enforcement.py -v
python3 -m pytest tests/test_process_supervisor_spec.py tests/test_async_io_supervisor.py -v  # no regression on #514
```

## Threat model

**Assets protected:** host resources (CPU/RAM/disk/process table) and the integrity of
the supervisor's own bookkeeping.

**In scope for this slice:**

- *A Simplicio-ecosystem command bypasses the supervisor entirely* (an IDE, a shell
  alias, a stale script invoking a Simplicio CLI directly). Mitigated by detection
  (observability today; termination only when the operator opts in via
  `SIMPLICIO_SUPERVISOR_ENFORCE=1`/`--enforce`).
- *The supervisor itself is unavailable or crashes mid-run.* The registry is a plain
  file with pid-liveness pruning, not a lock the supervisor process must hold open —
  a crashed supervisor leaves entries that are pruned as soon as anything reads the
  registry and finds the pid gone, per the #498 invariant "failure of the supervisor
  must not leave orphans undetected."
- *An operator wants proof that enforcement is genuinely opt-in.* Both the default
  (`enforcement_enabled()` reads an env var that defaults falsy) and the behavioral
  proof (off ⇒ nothing signaled) are unit-tested, not just documented.

**Explicitly out of scope for this slice (deferred — see below):** privilege
escalation via a spoofed cmdline (an unrelated process could name its argv to *look*
like a Simplicio process and get flagged, or an actual Simplicio process could obscure
its argv to *evade* detection — the signature match is a heuristic, not a
cryptographic attestation); resource-limit enforcement (cgroups/Job Objects); whole-tree
cancellation from the standalone enforcement CLI (that path still signals only
the direct pid; the registry-backed Hub path is described below); any
authentication/authorization on who may run `cancel`/`drain`/`--enforce` (this is a
local, single-operator CLI today, same trust boundary as running `kill` yourself).

## What's deferred (and why)

The issue's own AC lists a much larger surface than one slice can honestly close in one
pass. Deferred, with reasons:

- **Rollout shadow/canary automation.** No shadow-vs-canary traffic splitting or
  automated rollout percentage exists yet. This slice gives the primitives an
  automated rollout would gate on (detection + breaker + opt-in enforcement), but the
  rollout *policy* (percentages, promotion/rollback criteria) is a separate piece of
  work once there's a real fleet of supervised workloads to roll out against.
- **Full cross-platform enforcement.** The detector's Linux path (`/proc`) is
  exercised by the test suite on this host. The macOS/other-POSIX `ps` fallback is
  observation-only: it cannot produce the stable process identity needed to
  signal safely, so enabled enforcement deliberately fails closed on macOS/BSD
  instead of sending a signal to a reusable numeric PID. Windows
  process enumeration is explicitly **not implemented** (`scan_host_processes()`
  returns `[]` on `os.name == "nt"`) rather than guessed at — the epic's own test plan
  calls for "Windows Job Objects/Linux cgroups/fallback macOS" stress testing, which is
  real, separate work.
- **Process-tree cancellation — partially closed.** `ProcessRegistry.terminate(lease_id)`
  (`simplicio_loop/process_enforcement.py`, backing `kill_process_tree()`) signals a
  Linux process **group** only when its registry record explicitly proves the supervisor
  created a dedicated group. Unsupervised Linux enforcement signals only the pinned pidfd;
  macOS/BSD fails closed; Windows uses `taskkill /T /F`. `HubDaemon.handle(method="cancel")`
  calls this path when the request
  carries a `lease_id` — closing the specific gap called out after the wave-1 pass: an
  `execute` blocked in flight on one connection thread previously had no way to be killed
  by a `cancel` arriving on another thread (the old `cancel` only flipped a *queue job*'s
  state, never touched a real OS process). See
  `tests/test_hub_supervisor_epic_e2e.py::test_hub_cancel_kills_an_in_flight_execute_for_real`.
  The standalone `simplicio_loop/process_enforcement_cli.py` `cancel`/`drain --force`/
  `enforce` verbs still `os.kill()` the single registered pid only — they do not yet call
  `ProcessRegistry.terminate()`/`kill_process_tree()`, so that path keeps the descendants
  gap open. Unifying them is the natural next slice (see below).
- **Quotas / fairness / admission control.** Untouched by this slice; those are #498
  items 5–10, owned by other sub-issues.
- **`queue` command depth.** Reports only the registry's *active* (in-flight)
  supervised leases — there is no separate pending-priority queue wired into this
  slice. A real multi-class pending queue is `hub_scheduler.py`/`hub_queue_retry.py`
  territory; wiring `queue` to that is the natural next step (see below).

## Recommended next slice

Wire `SupervisedProcessAdapter`/`ProcessRegistry` into `hub_scheduler.py` (the existing
fair client scheduler) so `queue` reports real pending-vs-active depth per class. Also
switch `process_enforcement_cli.py`'s `cancel`/`drain --force`/`enforce` verbs from a bare
`os.kill(pid, SIGTERM)` to `ProcessRegistry.terminate()`/`kill_process_tree()` (already used
by the Hub's `cancel` IPC method, see above), carrying explicit dedicated-group evidence
where the supervisor owns it. Unsupported macOS/BSD enforcement must remain fail-closed.

## Second implementation: `scripts/supervisor_enforcement.py` — threat model + rollback

A later #516 slice added a second, independent worker,
`scripts/supervisor_enforcement.py` (six verbs: `status`, `detect`, `enable`, `disable`,
`rollout`, `selftest`; tested by `tests/test_supervisor_enforcement.py`). It is a
*state-and-observability* layer, distinct from the `simplicio_loop/process_enforcement.py`
module documented above — it does **not** call `os.kill` anywhere in its own code and
has **no caller anywhere else in the tree that reads its `enabled` flag to gate a real
action** (confirmed: `grep -rn supervisor_enforcement simplicio_loop/ scripts/` outside
the module and its test returns nothing). Concretely, today:

- `enable`/`disable` only flip a persisted JSON flag
  (`.simplicio-loop/orchestrator/supervisor_enforcement.json`, or `$SIMPLICIO_SUPERVISOR_STATE_FILE`).
  Nothing in this repo currently reads that flag to terminate, block, or otherwise act
  on an unsupervised process — `enable` is a documented no-op beyond making `status`
  report `enabled: true`. Do not assume flipping it on will start killing processes.
- `rollout --mode canary --percent N --allow ws` persists `canary_percent` and
  `canary_allowlist` and appends one JSONL event
  (`.simplicio-loop/orchestrator/supervisor_enforcement_events.jsonl`, schema
  `simplicio.supervisor-enforcement-event/v1`), but nothing yet *consumes* those fields
  to decide which workspace is actually enforced — the percentage/allowlist are
  recorded for a future consumer, not evaluated by anything today.
- `detect` never signals a real process (by design, per its own docstring); with
  `--scan-os` it enumerates the live OS process table through `psutil.process_iter()`
  and exits **3** (not an empty "all clear" result) when `psutil` is not installed —
  confirmed in this environment, where `psutil` is absent and `--scan-os` reliably
  exits 3.
- `status --governor-state-file FILE` only *reads* a `ResourceGovernor.status()`
  snapshot (`simplicio_loop/hub_governor.py`, #506) if one is written to that path.
  Nothing in production currently writes that snapshot from a live Hub — the
  integration is read-side only. A missing/stale file reports
  `governor.available: false`, which an operator could misread as "no pressure"
  rather than "not wired up."

**Failure modes (given the current code) and how to detect them:**

| Failure | Detection | Real cause in code |
|---|---|---|
| State file is corrupt or truncated (disk full mid-write, killed process) | `status` silently reports `enabled: false` even though it was enabled before | `load_state()` catches `(OSError, ValueError)` on JSON parse and returns `default_state()` — fails safe (disabled), never crashes, but also never surfaces *that* it fell back. Inspect `.simplicio-loop/orchestrator/supervisor_enforcement.json` by hand (`cat` + `python3 -m json.tool`) if `status` shows unexpectedly-disabled state. |
| `--scan-os` reports exit code 3 with no output | operator ran `detect --scan-os` expecting a real scan | `psutil` is not installed in the environment; `scan_os_processes()` returns `None` on `ImportError` and `cmd_detect` propagates that as exit 3, on purpose (never a fake empty list). Fix: `pip install psutil`. |
| `status --governor-state-file` always shows `governor.available: false` | operator expects breaker-open visibility during a real incident | No writer in this repo currently produces a `ResourceGovernor.status()` JSON snapshot at that path in production — only tests write one manually. This is a real, open integration gap, not a bug to "fix" by editing this worker. |
| `rollout --mode canary --percent 10` "isn't working" (still enforcing/not-enforcing everywhere) | `rollout` command exits 0 and persists the state, but behavior across workspaces is unchanged | there is no consumer of `canary_percent`/`canary_allowlist` yet — see bullet above. This is expected with the current code, not a defect. |

**Rollback (how to turn this off):**

- `python3 scripts/supervisor_enforcement.py disable` — always allowed, no guard,
  immediately flips the persisted `enabled` flag back to `false`.
- Because nothing in this repo currently consumes the `enabled` flag to take a real
  action (see above), the practical "kill switch" for this slice is simply: stop
  invoking the CLI. There is no running daemon or background thread it starts.
- If the state file itself is suspect, delete it
  (`rm .simplicio-loop/orchestrator/supervisor_enforcement.json`, or `$SIMPLICIO_SUPERVISOR_STATE_FILE`
  if overridden) — `load_state()` treats a missing file identically to a fresh,
  disabled install (`default_state()`), which is exercised by
  `test_missing_state_file_falls_back_to_disabled_safely`.
- To stop `rollout` from writing observability events, unset or redirect
  `$SIMPLICIO_SUPERVISOR_EVENTS_FILE`; there is no flag to suppress the event write
  other than not calling `rollout`.

## Third slice: `metrics` — rollout dashboard

Closes the previously-open "dashboard de métricas de rollout (só o log estruturado bruto
existe)" gap. `python3 scripts/supervisor_enforcement.py metrics [--json] [--events-file FILE]`
replays the same JSONL event log `rollout` writes
(`.simplicio-loop/orchestrator/supervisor_enforcement_events.jsonl`, or `$SIMPLICIO_SUPERVISOR_EVENTS_FILE`) and
reports, deterministically from that log — never fabricated:

- `total_transitions` — count of accepted rollout-mode changes ever recorded.
- `transitions_by_mode` — per-mode (`shadow`/`canary`/`full`) transition counts.
- `last_transition` — the most recent event record (mode, percent, allowlist, timestamp), or
  `None` if the log is empty/absent.
- `current_enabled` / `current_mode` — folded in from the current persisted state
  (`load_state`), so the dashboard shows "where we are" alongside "how we got here" in one call.

A missing or empty events file reports zero transitions honestly (`load_rollout_events`
returns `[]`) rather than guessing at history; a line that fails to parse as JSON is skipped,
not treated as a fatal error, so one corrupt line does not blank the whole dashboard. This is
still a raw-log replay, not a running daemon or a persisted rollup — there is no caching or
retention policy beyond whatever grows `supervisor_enforcement_events.jsonl` itself.

```bash
python3 scripts/supervisor_enforcement.py metrics
python3 scripts/supervisor_enforcement.py metrics --json
```

**In scope for this second slice:** an operator being able to trust that `enable`
never silently defaults to on (`SIMPLICIO_SUPERVISOR_I_UNDERSTAND=1` or `--i-understand`
required, tested), that a corrupt/missing state file never crashes `status`/`detect`
(tested), and that `detect` truly never signals a process regardless of state (tested,
including a monkeypatched `os.kill` spy that asserts it is never called).

**Out of scope / explicitly not yet true:** any real enforcement action gated on
`enabled`; any real canary-percentage evaluation; any production writer of the governor
snapshot this worker reads. Treat `enable`/`rollout` as recording operator *intent* for
a future consumer, not as live safety controls, until one of those gaps above is closed.

## Windows scanner migration and rollback

The Windows process table now prefers `psutil` and falls back to read-only CIM. Simplicio
processes are admitted to detection/enforcement only after their creation-time identity is
stable across argv collection; CIM command lines are parsed with `CommandLineToArgvW`.
Rollout remains protected by the existing opt-in enforcement switch. Roll back by disabling
enforcement first, then reverting the scanner change; persisted registry and JSONL receipt
schemas are unchanged, so restart/replay requires no data migration or destructive cleanup.
