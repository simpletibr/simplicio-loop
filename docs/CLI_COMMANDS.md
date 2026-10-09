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
| `dashboard` | Open the Simplicio Live run panel on 127.0.0.1:8765 (prints a tokenised URL); `--run`, `--repo`, `--port`, `--no-browser`, `--stop`, `--status`, `--snapshot` (with `--history` for the run history page), `--tui`; `--tokens` opens the legacy Token Monitor on port 9090. |
| `task` | Compile, validate, or preview a Markdown task contract. |
| `prototype` | Route prototype planning and validation commands. |
| `plan` | Compile a raw task into a frozen contract. |
| `turbo` | The default way to run a task; `simplicio-loop "<task>"` is the shortest form (a first argument that is not a subcommand is a task, unless it asks for all issues/tickets/tarefas, which goes to the drain intake). No provider and no API key: the invoking model plans and `simplicio-dev-cli` edits, in exactly two commands. `turbo --task T` surveys with Mapper and prints a `simplicio.turbo-request/v1` document (`status: "needs_plan"`: `tasks`, the `map` slice, the current text of the named `files`, `format`, `rules`, and `apply`, the one next command with a heredoc for the plan). `turbo --apply - [--verify V] <<'PLAN'` reads the find/replace JSON plan from stdin (`--apply FILE` reads a file: the same code path), applies it through dev-cli, runs `--verify`, and prints `simplicio.turbo-run/v1` with `mode: "host"` (`status` ok or failed, `applied`, `failed` with the dev-cli reason and a file excerpt, `verify`). `--task` (repeat for several), `--target`/`--context` (one task), `--tasks-file`, `--verify "<tests>"`. `--provider openrouter` is headless automation only; agents invoking the skill must not use it: one model call per lane to OpenRouter (`deepseek/deepseek-v4.1-flash`, `SIMPLICIO_TURBO_MODEL` overrides; pinned session, reasoning off; a duplicate request only after `SIMPLICIO_TURBO_HEDGE_AFTER` seconds, default 10), a rejected plan goes back once, and it needs `OPENROUTER_API_KEY` (`status: blocked`, `turbo_provider_key_missing` without it). Exit 0 ok or needs_plan, 1 failed, 2 blocked. |
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
| `doctor mapper` | Check that the installed `simplicio_mapper` is the expected build (origin, state dir, source commit); each blocker names a `reason_code` and a `fix`. |
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
# Default: any task, one or many. Exactly two commands, no provider and no API key.
# 1. Mapper surveys and the command prints a needs_plan request (tasks, map, files, format, rules, apply):
simplicio-loop "Create pricing.py with order_total" --verify "python -m pytest -q"
# 2. Run the printed apply command once, with {"operations":[{"path","find","replace"}]} as its heredoc body:
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

For a goal over a queue ("all open issues", "drain the board"), list the items (GitHub:
`gh issue list --state open --json number,title,body`) and run the two commands per item, in order:
`simplicio-loop turbo --repo <path> --task "<title>: <body>" --verify "<tests>"`, then the printed apply
command with your plan as its heredoc body; one CLAIMED issue and one PR per item.

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
