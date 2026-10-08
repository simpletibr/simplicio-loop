# Simplicio Live dashboard

Status: backend contract for the runs, tail and state modules (issue #1400). The HTTP routes are served by `server.py`; this page is the contract they must honor.

## Overview

The dashboard is a local, read-only view of loop runs. Each repo keeps runs in two roots: `.simplicio-loop/loop-runs/<id>` and `.simplicio-loop/orchestrator/runs/<id>`.

- `simplicio_loop/dashboard/runs.py` discovers runs, summarises them with `progress.build_progress`, and reads artifacts safely.
- `simplicio_loop/dashboard/tail.py` follows a run's `events.jsonl` incrementally for the SSE stream.

Neither module writes to a run. The only file the dashboard writes is its state file (see Environment).

## API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | liveness and version |
| GET | `/api/runs` | `{"runs": [...]}` summaries, newest `updated_at` first; filters `status`, `repo`, `since` |
| GET | `/api/runs/{id}` | summary, `state.json`, `manifest.json`, `plan.json`, and a receipt index (name and size only) |
| GET | `/api/runs/{id}/events` | SSE stream of the run's events (see SSE contract) |
| GET | `/api/runs/{id}/artifacts/{path}` | bytes of one artifact with secrets masked; 403, 404 or 413 on refusal |
| GET | `/api/queue` | queued work items (UNVERIFIED data source) |
| GET | `/api/agents` | agents and models (UNVERIFIED) |
| GET | `/api/tokens` | token usage (UNVERIFIED) |
| GET | `/` | Simplicio Live Pipeline vivo page (HTML); needs the token `t`, else 401 |
| GET | `/static/{path}` | kit and page assets (js, css, html, json, woff2, txt); no token; 403 or 404 on refusal |

Summary fields come from `build_progress` (`phase`, `percent`, `tasks`, `gates`, `completion`, and so on) plus:

- `status`: the raw state status (for example `running` or `done`), which is the filter key.
- `progress_status`: the progress builder's verdict (`RUNNING`, `COMPLETE`, `BLOCKED`, ...).
- `repo`, `started_at`, `finished_at`, `updated_at`.
- `duration_s`: `started_at` to `finished_at`, or to `updated_at` while unfinished.
- `last_seq`: highest `seq` in `events.jsonl`.
- `cost_usd`: always null until a measured receipt backs it.

## SSE contract (`/api/runs/{id}/events`)

- `retry: 1000` is sent once when the stream opens.
- Each event carries `id: <seq>` and one `data:` line holding the event JSON.
- A heartbeat comment line (`: heartbeat`) is sent every 15 seconds.
- Resume with the `Last-Event-ID` header or with `?since_seq=<n>`. Only events with `seq > n` are replayed.
- `seq` must increase strictly. `EventTail` skips any `seq` at or below its cursor.
- Poll cadence: 0.1 s after new events, 0.25 s while idle, 2.0 s once the run is terminal.

`EventTail` reads only the bytes after its saved offset, consumes only newline-terminated lines, and keeps only the offset and the last `seq` in memory. A rotated file (new inode) restarts from byte 0. A file that shrinks below the offset also restarts from byte 0.

## Security model

- Binds to 127.0.0.1 only.
- Every request needs the per-session token, except `/static/{path}`, which serves the kit and page assets with no token. Host and Origin are still checked there.
- The `Host` and `Origin` headers are checked against the loopback address.
- GET only. Every other method is refused.
- Every response carries a strict Content-Security-Policy. It includes `font-src 'self'`, so the Atkinson font loads from the same origin.
- No writes to repos or runs.
- Run ids must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Symlinked run directories are skipped.
- Artifact paths are percent-decoded once. Absolute paths, backslashes, NUL bytes, and empty, `.` or `..` segments are refused (403). So is any real path that leaves the run directory, which blocks symlink escapes.
- Artifacts larger than 1,000,000 bytes are refused (413).
- Returned text is masked by `redact_text`: bearer tokens, `sk-` and `ghp_` tokens, `AKIA` keys, email addresses, and `api_key=`-style values. Keys named like secrets, tokens or passwords are masked whole.

## Environment

| Variable | Effect |
|---|---|
| `SIMPLICIO_DASHBOARD_STATE` | Path of the dashboard state file. Written with mode 0600. Default: `~/.simplicio-loop/dashboard/state.json`. |

`write_state_file` and `read_state_file` use this path. The state file is the only file the dashboard writes.

## Module API

- `runs.discover_runs(repos)` returns `RunRef` dicts with `repo`, `run_id` and `run_dir`.
- `runs.list_runs(root, status=None, repo=None, since=None)` returns a list of summaries, newest first. The HTTP layer wraps it as `{"runs": [...]}`.
- `runs.run_summary(ref)` and `runs.run_detail(ref)` build the summary and detail payloads.
- `runs.read_artifact(run_dir, rel, max_bytes=MAX_ARTIFACT_BYTES)` raises `ArtifactForbidden`, `ArtifactNotFound` or `ArtifactTooLarge`.
- `tail.EventTail(path, terminal=False)` has `poll()`, `last_seq` and `next_delay(idle_max)`.

## CLI

`simplicio-loop dashboard` starts the panel on 127.0.0.1. The default port is 8765. It prints `http://127.0.0.1:<port>/?t=<token>` on stdout and opens a browser unless `--no-browser` is set.

| Flag | Effect |
|---|---|
| `--run <id>` | Select a run. Default: the newest active run. |
| `--repo <path>` | Watch a repo root. Repeatable. Default: the current directory. |
| `--port <n>` | Loopback port. `0` picks a free port. |
| `--no-browser` | Do not open a browser. |
| `--stop` | Stop the running panel. |
| `--status` | Print the status as JSON, with no token. Schema `simplicio.dashboard-status/v1` at `contracts/dashboard-status/v1/schema.json`. |
| `--snapshot <out.html>` | Write a self-contained offline HTML file of a run. No server. |
| `--tui` | Show a run in the terminal. |
| `--tokens` | Open the legacy Token Monitor on port 9090. Goes only with `--port`, `--no-browser` and `--stop`. |

State file: `~/.simplicio-loop/dashboard/state.json`. Override it with `SIMPLICIO_DASHBOARD_STATE`. Mode 0600. It holds the pid, port, token and repos.

Exit codes: 0 ok. 1 start failure. 2 usage error, unknown run, repo mismatch, or no runs. 3 port in use; the holder pid is named.

`simplicio-loop progress <run>` prints `panel: <url>` on stderr while the panel runs. It never does this with `--format json`.

## Page

`GET /` serves the Simplicio Live Pipeline vivo page (`static/live/index.html`). It needs the token.

Query parameters:

- `t`: the per-session token. Without it the response is 401.
- `run`: the run id to show.
- `theme`: `dark`, `light` or `contrast`.

Honesty rules:

- The ring stops at 99%. It reaches 100% only after a completion receipt with `ready` true and a verdict in `COMPLETE`, `DRAINED` or `VERIFIED`, read from `/api/runs/{id}`.
- The page polls `/api/runs/{id}` every 500 ms only while the run is done and the receipt is not ready yet, because the receipt file has no event.
- The connection goes stale after 45 s without activity.

The page is a fetch-stream client, not `EventSource`, so the heartbeat is visible. It reads `/api/runs/{id}/events` with the token in the `Authorization` header.

The page shows:

- The phase rail: 8 phases, with time in phase and the number of entries.
- The 99% ring.
- The Agora card: current action and next action. The running command is UNVERIFIED because no producer exists.
- Six gates: evidence, watcher, oracle, dod, quality, action.
- Health indicators: connection, events per minute, last heartbeat, stall.

The kit is served under `/static/components/` and the page assets under `/static/live/`, both without a token (see Security model).

### Swimlanes

One lane per worktree or lane id, shown under the phase rail. Each lane holds blocks, one per iteration. A block is coloured by its state (`RUNNING`, `PASS`, `FAIL`, `BLOCKED`, `STALLED`, `UNVERIFIED`) and carries a glyph, so the state is never shown by colour alone.

- A block is closed by gate results (evidence and quality), by `apply_result` `blocked`, and by `iteration_finished`.
- A stall marks the block `STALLED` until the next non-stall event.

### Drill-down

Click a phase, a block or a lane to open the side panel (`#drill`). It shows the facts for that target and its log lines, rendered with `sl-log-viewer`. `Escape` closes it and restores focus.

### Keys

- `j` and `k` move between lanes.
- `g` opens the gates. `l` opens the logs.
- `Escape` closes the drill-down. `Ctrl+K` opens the command palette.

The keys are ignored while the focus is in an input or textarea.

### Command palette

`Ctrl+K` opens the phase, task and file commands. A task command opens the lane drill-down. A file command opens the artifact in a new window, with no `opener`.

### Follow and pause

The "Seguir o run" button (`#follow`, `aria-pressed`) follows the run. While paused, events still reduce into state, but the view does not update until you resume.

### TV mode

Add `tv=1` to the URL. It sets `html[data-tv="1"]`: larger type and blocks, the same layout. TV run rotation is deferred (see Unverified).

### Stall toast

A `stall_detected` alert shows once, with `role="alert"`, if its time is within 60 seconds of now. Alerts are deduplicated by alert id.

### Hover timings

Each block's `data-tip` attribute carries the plain-text timings. CSS shows them on hover only.

### Frame time

The e2e test measures the median animation frame in headless software Chromium: 16.7 ms over 60 frames (MEASURED). This is software rendering, not a GPU measurement, so 60 fps on a real GPU is UNVERIFIED.

## Iteracoes e qualidade (#1403)

The timeline has one row per iteration, oldest first. Iterations come only from the Stop-hook hosts, which emit `iteration_started` and `iteration_finished` (`hooks/loop_stop.py`). Runner and turbo events carry no iteration, so a turbo run shows no iterations.

Verdicts:

- `PROGRESS`: a finished iteration with no `stall_detected`.
- `STALLED`: a `stall_detected` in that iteration. The stall fingerprint and streak are shown when present.
- No verdict: the iteration is still open.

Convergence is a proxy, labelled "gates reprovados x iteracao". For each finished iteration it counts the gates failing and the gates unverified at finish. It is not a test count.

Definition of done: seven pillars (implementation, unit, integration, system, regression, benchmark, coverage) read from `quality-matrix.json` in the run directory. Each pillar shows one state:

- `PASS`: the receipt measures it as passing. Coverage passes when measured coverage is at least 85.
- `FAIL`: the receipt measures it as failing.
- `PENDING`: `not_applicable`. A pending pillar never shows PASS.
- `UNVERIFIED`: the receipt is missing. With no receipt, every pillar is UNVERIFIED with the reason "quality-matrix.json ainda nao gerado".

The page fetches `quality-matrix.json` only when the run receipts list includes it.

Qualidade panel: tests, lint, coverage trend, flaky tests and diff stay UNVERIFIED with the reason "sem produtor no fluxo atual" until a producer exists.

Rule: the page never shows PASS for a pending or unverified item.

## Unverified (UNVERIFIED)

- Agent, model, token and cost data. `cost_usd` is always null, and no receipt backs token counts yet.
- `/api/queue`, `/api/agents` and `/api/tokens` depend on sources that have not been measured.
- Windows and macOS have not been tested.
- Events in rotated files (`events.jsonl.1` and similar) are not read, so `last_seq` covers only the current file.
- A truncation that refills the file past the saved offset is not detected, because the size check only sees a shrink.
- Real browser opening on Windows and macOS.
- The live `tui` animation on a real TTY.
- Agent and cost data (issue #1404).
- The rich queue (issue #1407).
- Deferred to the producer slice of #1403: test matrix counts and red and green transitions, lint per rule, coverage lines and branches with a sparkline, the flaky rule (needs per-test ids), the per-iteration diff with the virtualised 5,000-line benchmark, and files touched.
- The running command has no producer.
- Agent and model names need #1404. The lease heartbeat needs #1403 and #1404.
- Palette "jump to run" and TV run rotation: deferred to slice 4b-3, because they need a run list fetch.
- The contract title of a task: needs a fetch of `task-contract.json`.
- Reference-image diff: the baseline is font and platform fragile, so the PR carries screenshots instead.
- Agent and model names, the lease heartbeat, the running command and the quality gate: no producer yet, so they show UNVERIFIED (#1403 and #1404).
- Real-GPU 60 fps: UNVERIFIED. Only the software Chromium measurement exists.
