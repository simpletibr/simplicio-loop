# CLI command reference

Every installed entry point and every public subcommand accepts `--help`.
Use the most specific form, such as `simplicio-loop queue top --help` or
`simplicio-process-supervisor reports --help`.

## Installed entry points

| Entry point | Purpose |
|---|---|
| `simplicio-loop` | Main orchestrator: plan, execute, verify, deliver, and learn. |
| `issue-factory` | Discover ready work items from a configured source adapter. |
| `simplicio-ecosystem-doctor` | Inspect installed operator versions, capabilities, and route readiness. |
| `simplicio-loop-tools` | Run the consumer/tooling surface for Loop artifacts. |
| `simplicio-capabilities` | Inspect the capability catalog; use installed `--help` for selectors. |
| `simplicio-loop-stack` | Standalone stack command entry point. |
| `simplicio-route` | Standalone routing command entry point. |
| `simplicio-process-supervisor` | Inspect and control supervised processes (`status`, `top`, `queue`, `cancel`, `drain`, `reports`). |

## `simplicio-loop` commands

| Command | Purpose |
|---|---|
| `install` | Install bundled skills and hooks into a supported runtime. |
| `update` | Install the latest GitHub release of `simpletibr/simplicio-loop` (`--check` only reports, `--force` reinstalls) and refresh the global skills. |
| `dashboard` | Open or stop the token-monitor dashboard. |
| `task` | Compile, validate, or preview a Markdown task contract. |
| `prototype` | Route prototype planning and validation commands. |
| `plan` | Compile a raw task into a frozen contract. |
| `turbo` | The default way to run a task; `simplicio-loop "<task>"` is the shortest form (a first argument that is not a subcommand is a task, unless it asks for all issues/tickets/tarefas, which goes to the drain intake). No provider and no API key. Hybrid mode (see [Hybrid mode](#hybrid-mode)): when the invoking host has a headless CLI ([HARNESSES.md](HARNESSES.md)), ONE command runs Mapper, the model through that CLI, `simplicio-dev-cli` and `--verify`, and prints `simplicio.turbo-run/v1` with `mode: "hybrid"` and `llm: <host>`; otherwise the invoking model plans and `simplicio-dev-cli` edits, in two commands. `turbo --task T` surveys with Mapper and, when the hybrid backend cannot be used (it then adds `reason: "hybrid_unavailable: <cause>"`), prints a `simplicio.turbo-request/v1` document (`status: "needs_plan"`: `tasks`, the `map` slice, the current text of the named `files`, `format`, `rules`, and `apply`, the one next command with a heredoc for the plan). `turbo --apply - [--verify V] <<'PLAN'` reads the find/replace JSON plan from stdin (`--apply FILE` reads a file: the same code path), applies it through dev-cli, runs `--verify`, and prints `simplicio.turbo-run/v1` with `mode: "host"` (`status` ok or failed, `applied`, `failed` with the dev-cli reason and a file excerpt, `verify`). `--task` (repeat for several), `--target`/`--context` (one task), `--tasks-file`, `--verify "<tests>"`. `--provider openrouter` is headless automation only; agents invoking the skill must not use it: at most `SIMPLICIO_TURBO_HOST_PARALLEL` (default 4) model calls to OpenRouter, packed as in hybrid mode (`deepseek/deepseek-v4.1-flash`, `SIMPLICIO_TURBO_MODEL` overrides; pinned session, reasoning off; a duplicate request only after `SIMPLICIO_TURBO_HEDGE_AFTER` seconds, default 10), a rejected plan goes back once, and it needs `OPENROUTER_API_KEY` (`status: blocked`, `turbo_provider_key_missing` without it). Exit 0 ok or needs_plan, 1 failed, 2 blocked. |
| `prepare` / `arm` | Arm and preflight a run without executing tasks or calling a provider; returns a `run_id` for `tick`, `batch`, `wave`, or `prism`. |
| `run` | Arm, execute, and independently verify a task. |
| `orient` | Build bounded context through the Mapper survey and emit `simplicio.llm-max-speed-orientation/v1` plus a hash-bound `simplicio.loop-orient-receipt/v1` (Mapper-only). `--brief` (repeatable `--task`, issue #1310) renders the compact form: route first (its one next step is the `turbo` command carrying every task and `--verify`), deduped target file content, plan groups, suggested checks, Mapper generation + a `repo_state_chain` fingerprint, and the ops format of `apply`. |
| `apply` | Apply one host-written `ops.json` (issue #1310; `turbo` is the default path, this is for a plan you already have) (`{"tasks":[{"id","operations":[{path,find,replace}],"check","depends_on"}]}`). Validates every `find` in memory before any write (BLOCKED + hint, nothing written, on a miss/non-unique/chained mismatch); mutates through `simplicio-dev-cli` (compile then apply); runs independent file-disjoint chains concurrently via asyncio with an isolated check environment (`PYTHONDONTWRITEBYTECODE`, `PYTEST_ADDOPTS=-p no:cacheprovider`, a per-task `COVERAGE_FILE`); fails closed on a stale `repo_state_chain` (the same generation-identity fingerprint `orient --brief` recorded); writes a receipt under `.simplicio-loop/apply/<run_id>/receipt.json`. Exit 0 only on PASS, 2 on BLOCKED, 1 on FAIL. |
| `retrieve` | Retrieve and verify a tee-cache result. |
| `extensions doctor` | Inspect an exact extension-provider/runtime handshake. |
| `oracle` | Evaluate completion and cross-runtime parity. |
| `status` | Inspect the latest or a selected run. |
| `stack lock/verify` | Create or verify an installed-stack lock. |
| `doctor` | Inspect stack identity, source adapters, or storage routing. |
| `inspect` | Inspect MapperStore capabilities and storage routing. |
| `map` | Inspect or build map-service receipts. |
| `preflight` | Verify the Mapper and Dev CLI operators. |
| `economy` | Inspect, print, or apply the environment profile; inspect before applying, especially in CLI-only mode. |
| `ecc doctor` | Diagnose the optional ECC integration. |
| `deploy` | Plan a gated deployment; `--apply` is explicit. |
| `verify` | Run independent watcher and delivery gates. |
| `progress` | Render run progress as text, JSON, Markdown, or ANSI. |
| `resume` | Resume a non-terminal run. |
| `tick` | Execute one planned task through Dev CLI. |
| `batch` | Dispatch ready tasks with bounded isolated workers. |
| `wave` | Dispatch a governed wave and reconcile every worker before admitting another wave. |
| `prism` | Dispatch through the governed Prism route; uses the same physical governor and receipts as `batch`. |
| `cancel` | Cancel a non-terminal run. |
| `checkpoint` | Inspect, cancel, or garbage-collect candidate checkpoints. |
| `maintenance-deferred` | Record a maintenance-deferred backlog transition. |
| `deliver` | Reconcile delivery state with source evidence. |
| `decide` | Apply a human decision and invalidate dependent artifacts. |
| `sync-source` | Requery external source state and reconcile delivery. |
| `drain` | Evaluate or persist a queue-drain receipt. |
| `agent-slots` | Inspect and reclaim Loop-owned agent capacity. |
| `generation-broker` | Inspect and reconcile persisted generation bindings. |
| `queue` | Operate the durable queue (`status`, `top`, `drain`, `resume`, `doctor`, `reclaim`, `gc`, `migrate`, `inspect`, `cancel`). |
| `ledger` | Replay or validate the operational event ledger. |
| `findings` | List, report, reconcile, diagnose, or import routed findings. |
| `learn retrospective` | Derive durable lessons from completed runs. |
| `hub-drain-plan` | Read-only GitHub drain intake. |
| `intake` | Normalize any tracker export (JSON/CSV/Markdown, or an http(s) URL returning JSON) into `tasks.md`, auto-detecting GitHub/Jira/Linear/ClickUp/GitLab/Azure DevOps field shapes. |

### Zero-config start

```bash
# Default: any task, one or many. ONE command on a host with a headless CLI, no provider and no API key:
# Mapper surveys, the model plans through the host's own CLI, dev-cli applies, --verify runs; it prints the result.
simplicio-loop "Create pricing.py with order_total" --verify "python -m pytest -q"
# Only when it prints a needs_plan request (tasks, map, files, format, rules, apply; reason "hybrid_unavailable: <cause>"),
# run the printed apply command once, with {"operations":[{"path","find","replace"}]} as its heredoc body:
simplicio-loop turbo --repo . --apply - --verify "python -m pytest -q" <<'PLAN'
{"operations":[{"path":"pricing.py","find":"","replace":"def order_total(items):\n    ...\n"}]}
PLAN
# (any way of piping the plan to stdin works, e.g. a PowerShell here-string; `--apply plan.json` reads a file.
# Under SIMPLICIO_LOOP_STRICT a host may write only .simplicio-loop/turbo/plan.json.)
# Headless automation only; agents invoking the skill must not use it (asks OpenRouter for the plan, needs OPENROUTER_API_KEY):
simplicio-loop turbo --repo . --provider openrouter --task "Create pricing.py with order_total" --verify "python -m pytest -q"

# Governed runs from a tasks.md (queues, batches, Prism):
simplicio-loop prepare --task task.md --repo .
simplicio-loop wave RUN_ID
simplicio-loop tick RUN_ID --repo .
simplicio-loop batch RUN_ID
```

`turbo --apply` prints one JSON document (`simplicio.turbo-run/v1`, `mode: "host"`): `status` (`ok` or
`failed`; `blocked` when dev-cli is missing), `applied`, `failed` (per operation: the dev-cli reason and a
short excerpt of the file around a `find` that did not match), `verify`, `wall_s`. A missing plan (an
empty stdin, a terminal on stdin, no such file) is `failed` with `turbo_plan_missing`; a plan that is not UTF-8,
not JSON or not `{"operations":[...]}` is `failed` with `turbo_plan_malformed`. In provider mode the
document also carries `model_calls`, `retries`, `tokens`, `cache_hit_pct`, `cost_usd` and `calls`.
Done is `status: "ok"` and, when `--verify` was given, `verify.passed: true`. Name every file to change
in the task text.

Every `turbo` call first registers `.simplicio-loop/` (the local run state) with git, through
`state_dir.ensure_state_dir`: a line in `<git-dir>/info/exclude`, and `.simplicio-loop/` appended to the
repository's `.gitignore` when that file exists and no line already covers the directory (`.simplicio-loop`,
`.simplicio-loop/*`, `/.simplicio-loop/**` and the like). It never creates a `.gitignore`, so the directory
never shows up as untracked; never commit it.

### Hybrid mode

`simplicio-loop "<task>" [--verify V]` picks the host from the env markers a tool subprocess of that host sees (OpenCode
sets `OPENCODE=1` and `OPENCODE_PID`, Claude Code `CLAUDECODE=1`), with the parent-process names as the fallback; the hosts, their
detection and the exact headless command of each are the catalog `simplicio_loop/_catalog/harnesses.json`, listed in
[HARNESSES.md](HARNESSES.md). Every model call of the engine is then one tool-less, one-shot run of that host's CLI (the
prompt on stdin, stdin closed, the host's own model, account and configuration, nothing written to its config), so the
whole flow is one host tool call. The result is `simplicio.turbo-run/v1` with `mode: "hybrid"`, `llm` (the host),
`status`, `applied`, `failed`, `verify`, `verify_retry`, `model_calls`, `tokens` (as the host reports them), `cost_usd`
(`cost_basis: "host-reported"`, an estimate, not a bill), `calls`, `wall_s` and `budget_s`. Right after `status` it carries one fixed
`next` line (ok: report the result as printed, then stop, no reading files, no writing or running tests or scripts). A `failed` result
carries the `apply` command and the current `files`, so the host can fix it once in host mode; its `next` says so.

A run makes at most `SIMPLICIO_TURBO_HOST_PARALLEL` model calls (default 4), all at once: tasks that depend on each other (a shared file,
`depends_on`) are never split, and the other tasks are dealt round-robin by task count to the calls, each of which plans its tasks in one
plan that `simplicio-dev-cli` applies whole. Ten independent tasks are four calls in one round, not ten spawned host CLIs.

The host prompts once for the `simplicio-loop` command like for any shell command. An allow rule for it is optional and broad
(`--verify` runs any shell command); see [HARNESSES.md](HARNESSES.md#permissions) before adding one.

When the hybrid backend cannot be used, the same invocation prints the two-command host-mode request with
`mode: "host"` and `reason: "hybrid_unavailable: <cause>"` (`detail` adds the message), so the invoking agent carries on
with no user action. Causes: `no_host_detected`, `host_mode_only` (the host has no headless one-shot mode),
`host_cli_missing`, `network` (a fast connect probe of about 2 s found no route, or the host's own sandbox says so),
`host_auth`, `host_http`, `host_timeout`, `host_state_busy` (the host's own state store was busy, or failed, twice: one retry after 0.5 s), `host_error`, `budget`, `plan_rejected` (dev-cli refused the plan twice),
`opt_in` (a host whose headless run may keep its tools, named only by `SIMPLICIO_TURBO_LLM=<id>`; see [HARNESSES.md](HARNESSES.md)), `nested` and `forced_host`. A failure in the middle of a run keeps what was applied: the request then lists `applied` (task
numbers) and asks for the remaining tasks only.

OpenCode opens a SQLite session database on every `opencode run`, and lanes that share one fail with `database is locked` when they
start together (measured: 3 of 4 lanes on a fresh database). So each concurrency slot has its own,
`.simplicio-loop/host-llm/db/slot-<k>.db`, reused by the later calls that run in that slot, and no two live processes share one. An
`OPENCODE_DB` you export is not used by the hybrid lanes.

| Environment | Effect |
|---|---|
| `SIMPLICIO_TURBO_LLM` | `<harness id or alias>` forces that host (even without its markers, and without the network probe); `host` forces the two-command host mode; `provider` is the OpenRouter provider client; `auto` (default) detects. An unknown value is `blocked` (`turbo_llm_unknown`). |
| `SIMPLICIO_TURBO_BUDGET_S` | Time budget of one run, default 100 s: under the 120 s that the Claude Code and OpenCode bash tools allow by default. Past it no new call starts, what finished stays and the rest is handed to the host as a request (`budget`). Raise it only together with your host's tool timeout. |
| `SIMPLICIO_TURBO_CALL_TIMEOUT_S` | Timeout of one host CLI call, default 90 s. The process group is killed on a timeout (`host_timeout`). |
| `SIMPLICIO_TURBO_HOST_MODEL` | Model passed to the host CLI (`-m` and the like); default the host's own model. |
| `SIMPLICIO_TURBO_HOST_PARALLEL` | Host CLI processes at once, and the most model calls one run makes (independent tasks beyond that share a call), default 4 (8 `opencode run` processes at once were slower than 4 on an 8 GB machine: 20.9 s against 11.3 s for 8 tasks). |
| `SIMPLICIO_TURBO_PROBE` | `0` skips the connect probe (a proxy in the environment is probed instead of the API host). |
| `SIMPLICIO_TURBO_NESTED` | Set to `1` by the engine on the host CLI it starts: a nested `simplicio-loop` refuses to start the hybrid backend again (`nested`). |

For a goal over a queue ("all open issues", "drain the board"), list the items (GitHub:
`gh issue list --state open --json number,title,body`) and run per item, in order:
`simplicio-loop turbo --repo <path> --task "<title>: <body>" --verify "<tests>"` (and, on `needs_plan`, the printed
apply command with your plan as its heredoc body); one CLAIMED issue and one PR per item.

> **Nota de Descontinuação**: O comando `simplicio-loop run` foi descontinuado. Qualquer invocação a `simplicio-loop run --task task.md` ou `simplicio-loop run <run_id>` é interceptada e automaticamente redirecionada para o fluxo governado padrão `wave`.

`prepare` (also exposed as `arm`) performs the same contract/Mapper/operator
preflight as arming a run, but does not execute a task or call a provider. Its
JSON receipt contains the `run_id` needed by the explicit execution commands.
The default execution worker remains deterministic `simplicio-dev-cli`. An
external OpenRouter proposal worker is opt-in only:

```bash
simplicio-loop tick RUN_ID --repo . --provider-worker openrouter
simplicio-loop batch RUN_ID --provider-worker openrouter
simplicio-loop wave RUN_ID --provider-worker openrouter
```

The OpenRouter worker pins `deepseek/deepseek-v4.1-flash`, reads credentials
only from `OPENROUTER_API_KEY`/`OPENROUTER_BASE_URL`, converts its proposal to a
`simplicio.mechanical-edit/v1` plan, and sends that plan through Dev CLI. A
provider failure is blocked; it never falls back to manual or deterministic
artifact generation.

`wave` and `batch` initialize the Mapper-owned operations store when required,
use the Mapper handoff, reconcile one normal cold-start inspection internally when
the index is still warming, and derive worker demand from the task set. Physical
admission still controls safe CPU/RAM/disk concurrency; `--serial` is an explicit
conflict/dependency choice, not the default. Receipts and validation gates remain
mandatory.

## Generic task intake

`simplicio-loop intake` drains work items from any tracker into `tasks.md`
without a dedicated adapter per tool (issue #1312). GitHub keeps its native
`hub-drain-plan` path; `intake` is the universal fallback for everything else
— Jira, Linear, ClickUp, GitLab, Azure DevOps, Notion exports, a spreadsheet,
or plain text.

```bash
simplicio-loop intake --from tasks.json --repo . --out tasks.md
simplicio-loop intake --from tasks.csv  --repo .
simplicio-loop intake --from https://example.test/board.json --repo . --json
cat export.json | simplicio-loop intake --from - --repo .
```

- **Input formats**: a JSON array, `{items|issues|data|value|nodes: [...]}`,
  CSV, the existing `tasks.md` Markdown grammar (passed through), or an
  http(s) URL that returns JSON. `--from -` reads stdin. This command handles
  no credentials — when a source needs auth, fetch it with the host's own
  connector/CLI (`gh`, `jira`, `linear`, an MCP connector, …) and pass the
  exported file here.
- **Field auto-detection** covers the common export shapes of GitHub
  (`number`, `title`, `body`, `labels[].name`, `html_url`), Jira (`key`,
  `fields.summary`, `fields.description`, `fields.labels`,
  `fields.issuelinks` "is blocked by"), Linear (`identifier`, `title`,
  `description`, `labels.nodes[].name`, `url`, `relations`), ClickUp (`id`,
  `name`, `description`, `tags[].name`, `url`, `dependencies`), GitLab
  (`iid`, `title`, `description`, `labels`, `web_url`), and Azure DevOps
  (`id`, `fields["System.Title"]`, `fields["System.Description"]`,
  `fields["System.Tags"]`, `url`). `--map key=dotted.path` (repeatable)
  overrides any of the seven normalized fields (`id`, `title`, `body`,
  `labels`, `depends_on`, `source`, `url`) for anything else.
- **Dependencies** are read from each tracker's own relation/link field when
  present, and are also mined from body text lines such as `Depends on #12`
  / `blocked by ABC-3`.
- **Output**: `tasks.md` blocks in the same grammar `prepare` compiles — one
  `System:`/`Feature:`/`Type:` block per item, an Acceptance Criteria
  scenario derived from the item body, `Depends on: task N` lines mapped
  from source ids to this batch's task indices, and `Source: <url>` under
  Additional Information. `--freeze-backlog` additionally freezes the same
  items into `--repo`'s `scripts/task_backlog.py` backlog through that
  script's own `init --item-file` API (skipped with a warning if `--repo`
  has no `scripts/task_backlog.py`) — `intake` never writes under the state
  directory itself. `--json` prints a per-item summary (id, title, source,
  url, resolved dependency task indices).
- **Malformed input** (invalid JSON, a JSON object with none of
  `items`/`issues`/`data`/`value`/`nodes`, an empty CSV, or markdown with no
  `System:`/`Sistema:` block) fails closed: a typed `reason_code` on stderr
  and exit code 2.
- **Drain** each item the normal way: `turbo --task "<item>"` for a bounded
  task, or `prepare` → `wave` → `verify` for governed multi-item
  delivery. Write-back (closing the source issue, posting a comment) stays
  with the host, which owns the tracker credentials; `intake`/the loop only
  print the per-item result and source URL for the host to post.

## Prism and wave

`simplicio-loop wave` and `simplicio-loop prism` are public aliases of the governed
batch surface. Both preserve physical CPU/RAM/disk admission and stop before the
next wave when reconciliation is missing or failed. `simplicio-prism` remains the
routing skill in `.claude/skills/simplicio-prism/SKILL.md`.
`python3 scripts/arm_drain_prism.py --help` describes the drain arming script.
It writes a scratchpad and environment recommendations; it does not start
agents or deliver tasks. Its source adapter queries GitHub, so arming a local
simulated queue does not certify Jira/Azure DevOps integration.

A wave is a batch followed by lease/result reconciliation before the next batch.
`simplicio_loop.prism_scheduler.PrismScheduler.execute` dispatches admitted
workers in task groups with a barrier between batches. It does not perform
source edits itself: workers and independent validation must be bound.

## Offline journal replay

`python scripts/journal_replay.py <suite.json> --check` replays committed
`simplicio.journal-replay-suite/v1` fixtures through the production journal and recovery
modules without network access. It emits a canonical
`simplicio.journal-replay-receipt/v1` JSON receipt and exits non-zero when an observed
outcome differs from `expected_outcome`.

## Operator order for LLMs

1. `simplicio-loop "<task>" [--verify "<tests>"]` (short for
   `simplicio-loop turbo --repo . --task "<task>"`): the default way to run a task. It runs the Mapper
   survey and prints a request; you run the printed apply command once with your plan as its heredoc body,
   and Dev CLI edits. Exactly two commands: do not explore, list or read files, and do not run the tests
   yourself. No provider and no API key.
2. `simplicio-mapper --help` and `simplicio-dev-cli --help` to inspect an operator, not to run a delivery.
3. `simplicio-loop preflight --help`, focused tests, then `simplicio-loop verify --help` for governed runs.

The survey every flow requires is Mapper-only.

Component versions must be read from their installed release receipts, not inferred
from an older coordinated-train list. When a command is added, add a meaningful
`help=` string, document it here, and add a `--help` regression check.
