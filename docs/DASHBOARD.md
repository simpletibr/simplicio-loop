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
| GET | `/api/history` | `{"history": [...]}` one `simplicio.dashboard-history/v1` record per past run (verdict from `run-outcome.json`, `duration_s`, `iterations`, `stalls`, `tokens`, `cost_usd`, `phase_durations_s`), newest `started_at` first; filters `verdict`, `repo`, `since`, `until`, `min_/max_duration_s`, `min_/max_iterations`, `min_/max_cost_usd`, `limit`; a bad value is 400. Unmeasured fields are `null`, and a filter on one excludes the run |
| GET | `/api/history/compare` | `?a=<run>&b=<run>`: phases (union, `null` where a run never reached one), iterations, stalls, tests, tokens, cost and duration with `delta` (b minus a); `comparable` is false when the runs reached different phases (for example blocked against done); 404 for an unknown run |
| GET | `/api/history/trends` | `?bucket=week\|month` (UTC; weeks start Monday): per bucket `complete_rate` and `not_complete_rate`, `avg_phase_s`, `iterations_per_task`, `cost_per_task_usd`, `top_stall_causes`; same filters as `/api/history` |
| GET | `/api/history/lessons` | `{"lessons": [...]}` the lessons `simplicio-loop learn retrospective` wrote (`lessons.jsonl`), most repeated first, text redacted |
| GET | `/api/history/heatmap` | `{"heatmap": [7][24]}` run starts, weekday (Monday = 0) by hour, UTC |
| GET | `/api/history?format=csv` | the history records as CSV (formula-leading text is quoted); JSON is the default |
| GET | `/api/runs/{id}` | summary, `state.json`, `manifest.json`, `plan.json`, and a receipt index (name and size only) |
| GET | `/api/runs/{id}/events` | SSE stream of the run's events (see SSE contract) |
| GET | `/api/runs/{id}/config` | opt-in flags from `dashboard.toml` (`browser_notifications`, `webhook`); never the URL |
| GET | `/api/runs/{id}/artifacts/{path}` | bytes of one artifact with secrets masked; 403, 404 or 413 on refusal |
| GET | `/api/queue` | queued work items (UNVERIFIED data source) |
| GET | `/api/coordination` | backlog as kanban columns, dependency edges, drain progress and worker slots (see below) |
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
| `--snapshot <out.html> --history` | Write the offline history page: run list, weekly trends, day-by-hour heatmap and learn lessons. No server, no script. |
| `--tui` | Show a run in the terminal. On a TTY it redraws in place; `q` or Ctrl-C quits and restores the cursor. Off a TTY it prints once. |
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

Click a phase, a block or a lane to open the side panel (`#drill`). It has six tabs (issue #1405, slices 1405a and 1405b):

- **Resumo**: the facts for the target.
- **Logs**: the target's log lines in `sl-log-viewer`, with its level filter, search and follow.
- **Recibos**: the run's indexed receipts, each linked to its raw artifact, with its schema verdict. A receipt is **VALID** or **INVALID** only when it has a schema the package ships (today: `simplicio.stage-receipt/v1`). A receipt with any other schema id says "Não validado" with the reason. No receipt is shown as valid without that check.
- **Comandos**: the exact `simplicio-loop progress <run> --repo <repo>` lines (state, and state as one JSON read), with a copy button. Nothing is executed. The repo path is single-quoted when it has special characters. The tab is empty until the run reports its repo path.
- **Contrato**: the run's `task-contract.json`, shown as it is in a JSON tree. The page reads it when the tab opens, and only when the run detail lists it. The contract has no per-criterion status field, so the tab shows the contract and no status.
- **Contexto**: the run's `mapper-context.json`, the same way.

Arrow keys, Home and End move between tabs. `Escape` closes the panel and restores focus.

**Deep links.** Opening a phase, lane, block or the logs writes its fragment into the address bar: `#/run/<run>/phase/<phase>`, `#/run/<run>/lane/<lane>`, `#/run/<run>/lane/<lane>/block/<index>`, `#/run/<run>/logs`, `#/run/<run>/iteration/<n>` and `#/run/<run>/phase/<phase>/iteration/<n>` (the iteration's situation, duration, gate counts, stall and the lane lines of that iteration). Loading a page with one of these opens the drawer on that target. A fragment for another run is ignored. Closing the drawer clears the fragment.

Receipt verdicts: the run detail checks each receipt against the schemas the package ships (`receipt_check.py`), with `jsonschema` as a runtime dependency. The check is structural: it does not recompute hashes, so a VALID stage receipt is schema-compliant, not proven authentic. Adding a schema is one row in `SHIPPED_SCHEMAS`.

**Log viewer at 100 000 lines.** `sl-log-viewer` is virtualized: only the rows in view plus an overscan are in the DOM, each row has one fixed height, and a long message is cut with an ellipsis (its full text is the row title). Benchmark, in a real Chromium 141 on the cloud container (wall clock, so it varies by machine):

```
.venv/bin/python scripts/benchmark_log_viewer.py --lines 100000 --json
```

| Measure | Before (every line in the DOM) | After (virtualized) |
|---|---|---|
| Render 100 000 lines | 20 036 ms | 42 ms |
| DOM rows | 100 000 | 45 |
| Follow (jump to the end) | 23 327 ms | 35 ms |
| Level filter (1 031 lines match) | 543 ms | 29 ms |
| Text search | 507 ms | 34 ms |

`tests/test_live_log_virtualization_e2e_system.py` runs the same benchmark with loose limits (rows < 200, each step < 2 s) and skips when no Chromium is available.

### Keys

- `j` and `k` move between lanes.
- `g` opens the gates. `l` opens the logs.
- `Escape` closes the drill-down. `Ctrl+K` opens the command palette.

The keys are ignored while the focus is in an input or textarea.

### Command palette

`Ctrl+K` opens the phase, task, run and file commands. A run command ("Run <id>", from `GET /api/runs`, never the open run) moves the page to that run and keeps the token and the other URL parameters. A task command opens the lane drill-down. A file command opens the artifact in a new window, with no `opener`.

### Follow and pause

The "Seguir o run" button (`#follow`, `aria-pressed`) follows the run. While paused, events still reduce into state, but the view does not update until you resume.

### TV mode

Add `tv=1` to the URL. It sets `html[data-tv="1"]`: larger type and blocks, the same layout. With `tv=1` the page moves to the next run every 20 s, wrapping around (`rotate=<seconds>` sets the interval, 1 to 3600). It does not rotate under `prefers-reduced-motion: reduce`, or with fewer than two runs; the palette still jumps by hand.

### Stall toast

A `stall_detected` alert shows once, with `role="alert"`, if its time is within 60 seconds of now. Alerts are deduplicated by alert id.

### Hover timings

Each block's `data-tip` attribute carries the plain-text timings. CSS shows them on hover only.

### Frame time

The e2e test measures the median animation frame in headless software Chromium: 16.7 ms over 60 frames (MEASURED). This is software rendering, not a GPU measurement, so 60 fps on a real GPU is UNVERIFIED.

### Quadro por etapa (kanban)

O quadro mostra cada run dos repositórios observados como um cartão, na coluna da fase atual: Contrato (`intake`), Mapeamento (`mapping`), Plano (`planning`), Execução (`executing`), Validação (`validating`), Watcher (`watching`), Entrega (`delivering`) e Concluído (`done`). As fases `blocked`, `awaiting_decision`, `cancelled` e as desconhecidas ficam na coluna **Fora do trilho**.

- A fonte é `GET /api/runs`. O campo `phase` de cada resumo vem do `state.json` do run. Um run novo aparece no quadro na consulta seguinte.
- A página consulta a cada 3 s enquanto houver token. O quadro funciona sem o parâmetro `run`.
- Clicar em um cartão abre o run na página do pipeline (`?run=<id>`).
- Colunas por tarefa (itens do backlog em cada coluna) não estão nesta fatia. Ficam com a issue #1407.

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

Qualidade panel: tests, lint, coverage trend and diff read from the quality events (`test_result`, `lint_result`, `coverage_result`, and `apply_result` with `step: diff`) when present; otherwise they stay UNVERIFIED with the reason "sem produtor no fluxo atual". Flaky tests stay UNVERIFIED: the events carry counts, not per-test ids.

Rule: the page never shows PASS for a pending or unverified item.

## Agentes, tokens e custo (#1404)

The economy panel is global, not per run. It reads `~/.simplicio-loop/proxy_savings.json` and the provider catalog through `/api/tokens`. No field is tied to a `run_id`.

Every token and USD number is estimated, and the labels say "estimado". The estimator counts about 4 characters per token. The savings series is cumulative (labelled "acumulado").

The cost row (slice 1404b) estimates the input cost of the tokens sent through the proxy. It multiplies the measured `tokens_after` and `tokens_saved` by the input price of the active model. The prices come from `simplicio_loop/dashboard/prices.json`, which names its `as_of` date and the official `source_url`. Update that file by PR when the source changes. The engine's per-family `usd_saved` figure is a rough estimate of its own and is not replaced. If the active model has no entry, the cost row stays UNVERIFIED with that reason. A price entry can apply only up to a stated prompt size; the entry's `note` in `prices.json` gives the rate above it.

The `simplicio-loop economy` command is not the source of token numbers. It shows the environment and parallelism profile. The real sources are `get_status()` of the Token Monitor and the savings ledger at `.simplicio-loop/ledger/savings-events.jsonl`.

The cost row shows "Estimado". The budget row shows "Estimado" for a projection and FAIL only for a use already past the limit. Tokens por fase shows PASS only when `token_usage` events exist (measured). Every other row is UNVERIFIED with a reason:

| Row | State | Reason or source |
|---|---|---|
| Mapa de agentes | UNVERIFIED | lists the roles and stages of `contracts/stage-agents/v1/stages.json`; no instance is measured |
| Tokens por fase | PASS or UNVERIFIED | sums of the measured `token_usage` events by phase and model (`/api/runs/<id>/budget`); UNVERIFIED while no producer writes them |
| Custo | ESTIMADO or UNVERIFIED | estimate of the active model's input cost; see above |
| Orcamento | ESTIMADO, FAIL or UNVERIFIED | limits from the run's `task-contract.json` (`routing.budget`, summed over tasks); use from `token_usage`/`cost_sample` events and the event clock; the projection extrapolates by phase progress (use / phase fraction) and is labelled `estimado` |
| Comparacao com os ultimos 10 runs | ESTIMADO or UNVERIFIED | `budget.compare` over the `/api/history` reader (#1408): duration, tokens, cost and iterations against the average of the last 10 finished runs, the current run skipped; a field no run measured is UNVERIFIED |

`token_usage` and `cost_sample` stay reserved kinds with no producer (see [DASHBOARD_EVENTS.md](DASHBOARD_EVENTS.md)). Page data: `/api/tokens` carries the price table as `pricing`, and `/api/agents` carries the contract roles.

Budget slice (#1404): `simplicio_loop/dashboard/budget.py` reads the declared limits, sums the usage events and projects. The alert rules `budget-projected:<tokens|usd|seconds>` (warning, the projection passes the limit) and `budget-exceeded:<...>` (critical, measured use passed it) run in the alert watch. A dimension with no declared limit, no measured use or no phase progress is UNVERIFIED. Still deferred to issue #1404: the token producer (no `token_usage` writer exists, so tokens and USD stay UNVERIFIED on a real run), cost per run, task and iteration. The last-10 comparison is done on top of the #1408 reader. The decisions were: the price table lives in the repo; no token producer in this round; agent roles come from the stage contract.

## Coordination (`/api/coordination`)

Read-only, token-gated like `/api/queue`. The source is the backlog JSONL: `$SIMPLICIO_BACKLOG_FILE` when set, else `<repo>/.simplicio-loop/orchestrator/backlog/backlog.jsonl` for the first watched repo. The builder is `simplicio_loop/dashboard/coordination.py` (`build_coordination`).

- `status` is `MEASURED` when the backlog is read. It is `UNVERIFIED` when the file is missing or unreadable, with a `reason`, six zero-count columns, and empty `items`, `edges` and `slots`. The route still returns 200.
- `columns` always lists `ready`, `claimed`, `running`, `verifying`, `done` and `blocked`, in that order. A `ready` item whose dependencies are not done is shown in `blocked`, with `blocked_by` naming those dependencies.
- `items` carry `column`, `blocked_by` and `lease` (`null`, or `state` `live`, `stale` or `expired`). `edges` link a dependency to its dependent, with `satisfied`.
- `drain` shows `total`, `done`, `remaining`, `blocked` and `percent`. `eta_s` is set only from at least two done items with timestamps. Otherwise it is `null` with `eta_label` `UNVERIFIED`.

## Unverified (UNVERIFIED)

- Agent and model data: UNVERIFIED. The agent map has no run-dir producer yet, and `/api/agents` depends on a source that has not been measured.
- Token data: UNVERIFIED. The token figures are estimates ("estimado"), and no receipt backs token counts yet. `token_usage` has no producer.
- Cost data: UNVERIFIED. `cost_usd` is always null, and the USD figure is an input-only estimate with no per-run usage.
- `/api/queue`, `/api/agents` and `/api/tokens` depend on sources that have not been measured.
- Windows and macOS have not been tested.
- Events in rotated files (`events.jsonl.1` and similar) are not read, so `last_seq` covers only the current file.
- A truncation that refills the file past the saved offset is not detected, because the size check only sees a shrink.
- Real browser opening on Windows and macOS.
- The live `tui` on Windows and macOS terminals (verified on a Linux pseudo-terminal by `tests/test_dashboard_cli_system.py`; the Windows path reads keys with `msvcrt` and is not run here).
- Agent and cost data (issue #1404).
- The rich queue (issue #1407).
- Deferred from #1403 (see [DASHBOARD_EVENTS.md](DASHBOARD_EVENTS.md#quality-producers)): the test matrix by unit, integration, system and regression level, red and green transitions per test id, the flaky rule (needs per-test ids), and the diff virtualisation with the 5,000-line benchmark (no measurement exists).
- The running command has no producer.
- Agent and model names need #1404. The lease heartbeat needs #1403 and #1404.
- Reference image: `tests/fixtures/live_pipeline/pipeline-dark-1280x900.png` is a Chromium screenshot (dark, 1280x900, board hidden). The diff tolerates 16 of 255 per channel on up to 2% of the pixels. Other browsers or font stacks may need a new reference (`SL_UPDATE_REFERENCE=1`).
- The contract title of a task: needs a fetch of `task-contract.json`.
- Reference-image diff: the baseline is font and platform fragile, so the PR carries screenshots instead.
- Agent and model names, the lease heartbeat, and the running command: no producer yet, so they show UNVERIFIED (#1404).
- Real-GPU 60 fps: UNVERIFIED. Only the software Chromium measurement exists.

## Alerts (#1406, slices 1406a and 1406b)

The server evaluates the run alert rules over the event stream (`simplicio_loop/dashboard/alerts.py`). Each stream connection gets its own watch, and the server sends only changes, so one alert is raised once while it stays active. The alert center is the **Alertas (N)** button in the header. It counts only the alerts you can see. Each alert names its severity in text, its reason, and a **Ver** action when it points to a drill target.

| Rule | Severity | Raised when | Evaluated by |
|---|---|---|---|
| `run-stalled` | critical | the journal reports a stall (`stall_detected`), until a different phase starts | server |
| `gate-failing:<gate>` | warning | a gate's latest verdict is FAIL | server |
| `phase-silent:<phase>` | warning | no event for more than 5 minutes | server |
| `budget-projected:<dim>` | warning | the usage projected to the end of the run passes the declared limit (estimate) | server |
| `budget-exceeded:<dim>` | critical | measured usage is past the declared limit | server |
| `oracle-unverified` | warning | the run is done and its receipt is ready, but the oracle gave no verdict | server |
| `stream-lost` | warning | the stream is stale, offline or closed | page (it is the page's own connection) |

**Frames.** Each connection starts with `event: alert_snapshot`, which lists the alerts active now. Later changes arrive as `event: alert_raised` and `event: alert_cleared`. These frames are not stored in `events.jsonl`, and the page does not treat them as dashboard events. See [DASHBOARD_EVENTS.md](DASHBOARD_EVENTS.md).

**Silence.** **Silenciar 1 h** hides an alert for an hour in this page. Nothing is stored outside the page. The first snapshot after connecting sets a baseline, so alerts that were already active do not notify.

**Settings (`.simplicio-loop/dashboard.toml`, opt-in).** The file is optional; without it every default holds. A bad value keeps its default and the server keeps running. The file is read per run, from the run's repo.

```toml
[alerts]
phase_silence_minutes = 5      # default 5; a number above 0

[notifications]
browser = false                # default false; true shows the "Ativar notificações do navegador" button

[webhook]
# url = "https://hooks.example.test/simplicio"   # off unless set; http or https only
```

**Browser notifications.** Off by default. With `browser = true` the alert center offers a button; the browser asks for permission only after you press it. A new alert then raises a browser notification (the same text as the toast). Silenced alerts and alerts already active when the page connected do not notify. The page learns the flags from `GET /api/runs/{id}/config`, which returns `{"browser_notifications": bool, "webhook": bool}` and never the URL.

**Webhook.** Off by default; nothing is sent unless `[webhook] url` is set. Each raised alert is posted once (JSON, `simplicio.dashboard-alert/v1`: `run_id` and `alert`) while it stays active, however many pages watch the run. A failed post is dropped and never affects the stream. Only the dashboard process posts, from this machine.

**Not done, with reasons.** The budget alerts are in (see the Orcamento row above); the lease rule waits on the lease heartbeat (#1407); neither is on main, so no substitute was written. Desktop (OS) notifications beyond the browser's own Notification API are not written. **Latency (measured on a loopback server, 16 cycles per case).** From the event being written to its alert appearing: on a running run, median 0.10 s on the stream and 0.10 s in the page (worst 0.25 s and 0.15 s). On a finished run, median 0.50 s on the stream. The finished-run poll is 0.5 s, so the 2-second target holds with margin. The end-to-end page latency on a finished run was not measured.

## Idle CPU measurement (#1400)

`python -m simplicio_loop.dashboard.bench --runs 50 --events 10000 --idle-seconds 30 --json` serves 50 fixture runs of 10,000 events, drains one SSE stream, then samples this process (server included) for `--idle-seconds` with that stream open and nothing written. `idle_cpu.cpu_percent` is utime + stime over wall time, as a share of one core.

MEASURED on Linux (4 cores, `/proc`), one 30 s sample: 0.06 CPU s over 30.0 s wall = 0.2 % (limit 2 %); RSS 47,000 KiB after the full run (limit 80 MB). One sample, not a distribution. Windows and macOS: UNVERIFIED (no `/proc`, no machine to run on).

## Quality gate (issue #1409)

**Accessibility.** `tests/test_live_a11y_e2e_system.py` runs axe 4.12.1 (tags wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice) in a real Chromium on the pipeline page (dark, light, contrast themes, populated by the lifecycle fixture), the board, the drill-down with each of its six tabs, and TV mode. Result: 0 violations of any impact. It also checks keyboard reach, a visible focus indicator, Escape returning focus to the opener, `lang="pt-BR"`, and accessible names. One real gap was found and fixed: a phase change was not announced, so a visually hidden `role="status"` line (`#phase-status`) now carries "Fase atual: <fase>". Alerts were already announced (`role="alert"` for STALLED).

**Performance** (`tests/test_live_perf_e2e_system.py`, loopback, one run on this container; set `SL_PERF_REPORT=<file>` to write the numbers as JSON).

| Check | Measured | Budget |
|---|---|---|
| LCP, 5 cold loads, median | 180 ms (160 to 240) | under 1500 ms |
| Burst of 1000 events, time to last seq | 0.43 s | under 15 s |
| Long tasks during that burst | 1 task, 282 ms | total under 1000 ms, max 500 ms |
| Heap after GC, 3000 events | 2.79 MB at 500, 3.05 MB at 3000 (growth 173 KB) | under 10 MB |
| DOM nodes / listeners | 1261 / 56, flat | within 10% |
| Read routes p50 / p95 (20 runs, 1000 events) | health 1.5 / 2.0 ms, runs 10.1 / 14.9 ms, run detail 2.3 / 2.8 ms, artifact 1.6 / 2.0 ms | p95 under 100 ms |

The 8 h session is not run for real: it is a compressed 3000-event session, so the 8 h claim is UNVERIFIED beyond that proxy.

**Security** (`tests/test_dashboard_security_review_integration.py`). Fixed: secrets leaked on SSE events and alert frames; redaction gaps (private key blocks, Anthropic and project-style keys, GitHub fine-grained tokens, short `password=`/`token=` pairs, secret-shaped JSON keys); unmasked run summaries, receipt reasons and `/api/tokens`; symlinks followed out of the run directory (state, manifest, plan, events, receipts); HEAD sending a body; TRACE/CONNECT answering 501; error pages without security headers. CSP now also sets `base-uri`, `form-action` and `object-src` to `'none'`, with `X-Frame-Options`, COOP and CORP. Checked and clean: token never echoed, traversal variants, Host/Origin rebinding, wrong or oversize token, GET-only. Residual: `simplicio_loop/progress.py` follows symlinks for four sidecar receipts (outside the Live server, not changed here).
