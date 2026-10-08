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
- Every request needs the per-session token.
- The `Host` and `Origin` headers are checked against the loopback address.
- GET only. Every other method is refused.
- Every response carries a strict Content-Security-Policy.
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

## Unverified (UNVERIFIED)

- Agent, model, token and cost data. `cost_usd` is always null, and no receipt backs token counts yet.
- `/api/queue`, `/api/agents` and `/api/tokens` depend on sources that have not been measured.
- Windows and macOS have not been tested.
- Events in rotated files (`events.jsonl.1` and similar) are not read, so `last_seq` covers only the current file.
- A truncation that refills the file past the saved offset is not detected, because the size check only sees a shrink.
