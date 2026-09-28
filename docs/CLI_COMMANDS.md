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
| `simplicio-hub` | Start or inspect the local Hub daemon (`serve`, `doctor`). |
| `simplicio-remote-queue-server` | Serve the remote task queue. |
| `simplicio-remote-worker` | Claim, enqueue, cancel, or serve remote work. |
| `simplicio-remote-worker-supervisor` | Supervise bounded remote worker processes. |
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
| `prepare` / `arm` | Arm and preflight a run without executing tasks or calling a provider; returns a `run_id` for `tick`, `batch`, `wave`, or `prism`. |
| `run` | Arm, execute, and independently verify a task. |
| `orient` | Build bounded context through the Mapper survey and emit `simplicio.llm-max-speed-orientation/v1` plus a hash-bound `simplicio.loop-orient-receipt/v1` (Mapper-only). `--brief` (repeatable `--task`, issue #1310) renders Turn 1 of the plan-once/apply-once hot path: route first, deduped target file content, plan groups, suggested checks, Mapper generation + a `repo_state_chain` fingerprint, and the exact `apply` command. |
| `apply` | Turn 2 of the plan-once/apply-once hot path (issue #1310): apply one `ops.json` (`{"tasks":[{"id","operations":[{path,find,replace}],"check","depends_on"}]}`). Validates every `find` in memory before any write (BLOCKED + hint, nothing written, on a miss/non-unique/chained mismatch); mutates through `simplicio-dev-cli` (compile then apply); runs independent file-disjoint chains concurrently via asyncio with an isolated check environment (`PYTHONDONTWRITEBYTECODE`, `PYTEST_ADDOPTS=-p no:cacheprovider`, a per-task `COVERAGE_FILE`); fails closed on a stale `repo_state_chain` (the same generation-identity fingerprint `orient --brief` recorded); writes a receipt under `.simplicio-loop/apply/<run_id>/receipt.json`. Exit 0 only on PASS, 2 on BLOCKED, 1 on FAIL. |
| `retrieve` | Retrieve and verify a tee-cache result. |
| `extensions doctor` | Inspect an exact extension-provider/runtime handshake. |
| `oracle` | Evaluate completion and cross-runtime parity. |
| `status` | Inspect the latest or a selected run. |
| `stack lock/verify` | Create or verify an installed-stack lock. |
| `doctor` | Inspect stack identity, source adapters, resources, or storage routing. |
| `inspect` | Inspect MapperStore capabilities and storage routing. |
| `map` | Inspect or build map-service receipts. |
| `preflight` | Verify Mapper, Dev CLI, and Runtime operators. |
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
| `hub-drain-admit` | Admit a held final checkpoint without dispatching it. |
| `intake` | Normalize any tracker export (JSON/CSV/Markdown, or an http(s) URL returning JSON) into `tasks.md`, auto-detecting GitHub/Jira/Linear/ClickUp/GitLab/Azure DevOps field shapes. |

### Zero-config start

```bash
# Multi-tarefas / Governed waves (padrão recomendado):
simplicio-loop wave RUN_ID

# Preparar / Armar run a partir de markdown:
simplicio-loop prepare --task task.md --repo .

# Tarefa única ultrarrápida (local-first): `route_mode.py` -> fast-path
# (ver SKILL.md "Pick the fastest route first"):
#   python3 scripts/route_mode.py --root . --goal "<one task, plain prose>"
#   simplicio-dev-cli edit --plan ops.json --compile plan.json
#   simplicio-dev-cli edit --plan plan.json --apply --json
#   <the task's verification command>

# Tick unitário e batch contínuo:
simplicio-loop tick RUN_ID --repo .
simplicio-loop batch RUN_ID
```

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

A single bounded task is routed through the documented fast-path instead of a
dedicated command: `python3 scripts/route_mode.py --root . --goal "<task>"`
selects `fast-path` (one task, one file, fan-in ≤1, no sensitive surface),
then `simplicio-dev-cli edit --plan ... --compile`/`--apply` performs the
governed local edit and the task's own verification command closes it out — no
run, no wave, no provider call. See
`.claude/skills/simplicio-loop/SKILL.md` § "Pick the fastest route first".

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
- **Drain** each item the normal way: `orient --brief` → `apply` for a single
  bounded task, or `prepare` → `wave` → `verify` for governed multi-item
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
See [the benchmark report](QUEUE_BENCHMARK_PROTOCOL.md) for measured coverage.

## Offline journal replay

`python scripts/journal_replay.py <suite.json> --check` replays committed
`simplicio.journal-replay-suite/v1` fixtures through the production journal and recovery
modules without network access. It emits a canonical
`simplicio.journal-replay-receipt/v1` JSON receipt and exits non-zero when an observed
outcome differs from `expected_outcome`.

## Convergence parity protocol

Run one versioned fixture through the Runtime-backed and standalone semantic
controllers with:

```text
python -m simplicio_loop.convergence_parity FIXTURE.json [--runtime-decision DECISION.json]
```

The command emits `simplicio.convergence-parity/v1`. Exit `0` means both paths
reached equivalent verified acceptance and evidence receipts. Exit `2` means an
invalid fixture or an unsupported environment; the receipt names the unsupported
path and reason, and no path may silently substitute standalone behavior for a
missing, incompatible, or non-activating Runtime decision.

## Operator order for LLMs

1. `simplicio-mapper --help` → `scan` → `inspect` → `handoff`.
2. `simplicio-dev-cli --help` → `task --help` for the governed edit and verification step.
3. `simplicio-loop preflight --help`, focused tests, then `simplicio-loop verify --help`.

The survey every flow requires is Mapper-only.

The benchmark verified installed Loop `3.43.10` on 2026-09-11. Other component
versions must be read from their installed release receipts, not inferred from
an older coordinated-train list. When a command is added, add a meaningful
`help=` string, document it here, and add a `--help` regression check.
