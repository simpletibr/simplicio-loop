# Troubleshooting

Use this file to capture repeatable fixes. Prefer concrete commands and log paths.

## Port Already In Use

- Symptom: app fails to bind `<PORT>`.
- Diagnose: list processes listening on the port.
- Fix: stop the previous local server or change the configured port.

## Database Connection Fails

- Symptom: startup or tests fail while connecting to `<DATABASE_REQUIREMENT>`.
- Diagnose: verify VPN/network, host, credentials, migrations and seed data.
- Fix: connect required network, start local database, or update environment variables.

## Authentication Fails

- Symptom: redirect loop, 401/403, callback error, missing user profile.
- Diagnose: confirm `<AUTH_FLOW>`, redirect URI, client id, cookies and local HTTPS.
- Fix: update auth config or use documented demo flow.

## Frontend Calls Wrong API

- Symptom: UI loads but data comes from another environment or fails.
- Diagnose: inspect frontend config and server logs.
- Fix: set API URL to `<BACKEND_URL>` for local execution.

## Build Fails With Locked Files

- Symptom: compiler cannot copy or overwrite build artifacts.
- Diagnose: a local server or compiler process is holding the file.
- Fix: stop the running app, shut down build servers, then rebuild.

## Playwright Browser Or FFmpeg Missing

- Symptom: E2E fails before opening the page or video cannot be recorded.
- Diagnose: check Playwright install output.
- Fix:

```bash
npx playwright install
npx playwright install ffmpeg
```

## `simplicio-py task` Hangs On A Shell-Out Provider (claude-cli / codex-cli)

Issue #210: a bounded task operator replaced the old single blocking
`subprocess.run(timeout=600)` call in `simplicio/providers.py::_shell_out`
(the code path behind `SIMPLICIO_MODEL=claude-cli/*` and `codex-cli/*` —
`generate()` → `_shell_out_claude`/`_shell_out_codex` → `_shell_out` →
`simplicio.task_operator.run_bounded_subprocess`). This section is the
loop-facing contract: what a host loop (e.g. simplicio-loop) should expect,
retry, and attach as evidence when a provider call doesn't complete
cleanly.

### Env vars

| Var | Default | Meaning |
|---|---|---|
| `SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S` | disabled | Optional maximum seconds with **zero** stdout/stderr bytes before the call is classified as a startup stall. |
| `SIMPLICIO_PROVIDER_TOTAL_TIMEOUT_S` | disabled | Optional maximum seconds for the whole call, regardless of output. |
| `SIMPLICIO_PROVIDER_LONG_RUNNING_REVIEW_S` | `1800` | Elapsed seconds before one PID-backed `provider_long_running` review event is emitted; the child keeps running. |
| `SIMPLICIO_PROVIDER_HEARTBEAT_INTERVAL_S` | `15` | How often a `provider_heartbeat` event is emitted while the child is alive. |

Unset, invalid, zero, or non-positive timeout values disable that deadline;
use an explicit positive value only when a caller needs a cancellation policy.

### Phase classification

Every call now resolves to one of five phases, surfaced both in the
`SystemExit` message `simplicio-py` raises and — when `SIMPLICIO_LOG_ROOT`
is set — in `<root>/.simplicio/events.jsonl` (see `emit_event`'s contract
in `simplicio/observability.py`, schema `simplicio.dev-cli-event/v1`):

- `completed` — normal exit, `returncode == 0`.
- `startup_timeout` — no provider output at all before the startup
  deadline. Usually means the CLI isn't logged in, network/DNS is stuck, or
  the binary itself is hanging before it even reaches the model. **Retry
  policy**: do not blind-retry the same command; first check
  `claude`/`codex` login state, then retry once.
- `total_timeout` — the provider was producing output but ran past the
  explicitly configured total deadline. Usually a genuinely large/slow task.
  **Retry policy**: narrow the task scope (smaller `--target`/`--bound-paths`)
  before retrying, or remove that opt-in deadline when continued observation
  is appropriate.
- `cancelled` — an external cancellation fired (cooperative, via
  `task_operator.run_bounded_subprocess`'s `cancel_event`). **Retry
  policy**: caller-driven; this repo never auto-retries a cancellation.
- `failed` — the CLI wasn't found on PATH, or exited non-zero. **Retry
  policy**: fix the underlying cause (install the CLI, check `stderr` in
  the message) before retrying; retrying an unchanged non-zero exit will
  just fail the same way.

Long-running work is not another terminal phase: after 30 minutes by default,
it produces one `provider_long_running` warning with the child PID, elapsed
time, and output-observation state so an operator can inspect the process
without discarding valid work.

On every non-`completed` phase, the whole descendant process tree is
killed (POSIX: `os.killpg` on the child's own session; Windows: `taskkill
/PID <pid> /T /F`, falling back to a direct `Popen.kill()` if `taskkill`
itself is unavailable) — no orphaned `claude`/`codex` subprocess or
grandchild process should ever survive a bounded call.

### What to attach as evidence when the provider is unavailable

There is no separate "task receipt" artifact beyond what's already emitted:

1. The `SystemExit` message itself — it names the phase, the elapsed time,
   and a `recovery` hint (e.g. "check that the CLI is logged in and
   reachable").
2. If the caller ran with `SIMPLICIO_LOG_ROOT` set, the matching
   `provider_<phase>` line(s) in `<root>/.simplicio/events.jsonl` — this is
   the structured, timestamped version of the same information a host
   loop's journal can ingest directly (see `simplicio/observability.py`'s
   `emit_event` docstring for the full schema).
3. `simplicio-py doctor --json` — `events_summary()` renders a summary of
   recent events (including provider phases) without needing to hand-parse
   `events.jsonl`.

Attach all three (or as many as are available) rather than just the bare
error string — the phase + elapsed time is what lets a human or a loop
tell "the CLI isn't logged in" apart from "this task is just too big" apart
from "something is genuinely stuck".

## Add Project-Specific Issues

### `<SYMPTOM>`

- Cause: `<CAUSE>`
- Diagnose: `<COMMAND_OR_LOG>`
- Fix: `<FIX>`
