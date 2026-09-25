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
| `dashboard` | Open or stop the token-monitor dashboard. |
| `task` | Compile, validate, or preview a Markdown task contract. |
| `prototype` | Route prototype planning and validation commands. |
| `plan` | Compile a raw task into a frozen contract. |
| `prepare` / `arm` | Arm and preflight a run without executing tasks or calling a provider; returns a `run_id` for `tick`, `batch`, `wave`, or `prism`. |
| `run` | Arm, execute, and independently verify a task. |
| `orient` | Build bounded context through Fast and emit `simplicio.llm-max-speed-orientation/v1` plus a hash-bound `simplicio.loop-orient-receipt/v1`; auto may fall back read-only to Mapper, while required Fast/Rust fails closed. |
| `retrieve` | Retrieve and verify a tee-cache result. |
| `extensions doctor` | Inspect an exact extension-provider/runtime handshake. |
| `oracle` | Evaluate completion and cross-runtime parity. |
| `status` | Inspect the latest or a selected run. |
| `stack lock/verify` | Create or verify an installed-stack lock. |
| `doctor` | Inspect stack identity, source adapters, resources, or storage routing. |
| `inspect` | Inspect MapperStore capabilities and storage routing. |
| `map` | Inspect or build map-service receipts. |
| `preflight` | Verify Mapper, Dev CLI, Runtime, and Fast operators. |
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
| `checkpoint` | Inspect, cancel, or garbage-collect Fast V3 checkpoints. |
| `maintenance-deferred` | Record a maintenance-deferred backlog transition. |
| `deliver` | Reconcile delivery state with source evidence. |
| `decide` | Apply a human decision and invalidate dependent artifacts. |
| `sync-source` | Requery external source state and reconcile delivery. |
| `drain` | Evaluate or persist a queue-drain receipt. |
| `agent-slots` | Inspect and reclaim Loop-owned agent capacity. |
| `generation-broker` | Inspect and reconcile persisted generation bindings. |
| `queue` | Operate the durable queue (`status`, `top`, `drain`, `resume`, `doctor`, `reclaim`, `gc`, `migrate`, `inspect`, `cancel`). |
| `single-task-fast` | Execute one bounded JSON task locally, or exactly two dependent Markdown tasks through the provider-backed Loop route. |
| `ledger` | Replay or validate the operational event ledger. |
| `findings` | List, report, reconcile, diagnose, or import routed findings. |
| `learn retrospective` | Derive durable lessons from completed runs. |
| `hub-drain-plan` | Read-only GitHub drain intake. |
| `hub-drain-admit` | Admit a held final checkpoint without dispatching it. |

### Zero-config start

```bash
# Multi-tarefas / Governed waves (padrão recomendado):
simplicio-loop wave RUN_ID

# Preparar / Armar run a partir de markdown:
simplicio-loop prepare --task task.md --repo .

# Tarefa única ultrarrápida (local-first):
simplicio-loop single-task-fast --task-file task.json

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

`single-task-fast --task-file TASK_FILE` keeps a one-task JSON input on the
local-first Mapper/Fast/Dev CLI route. A file containing exactly two dependent
tasks may be Markdown (or a compatible task-contract collection); that form
selects the configured provider worker, defaults to `openrouter`, requires Fast
preparation for each task, and executes the existing ordered Loop batch. The
creation predecessor must complete with verified per-task receipts before the
edit task is admitted. Missing Mapper, Fast, provider, Dev CLI, dependency, or
evidence receipts remain blocked.

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
2. `simplicio-fast --help` when Fast is operational; it supplies bounded context, not authority.
3. `simplicio-dev-cli --help` → `task --help` for the governed edit and verification step.
4. `simplicio-loop preflight --help`, focused tests, then `simplicio-loop verify --help`.

The benchmark verified installed Loop `3.43.10` on 2026-09-11. Other component
versions must be read from their installed release receipts, not inferred from
an older coordinated-train list. When a command is added, add a meaningful
`help=` string, document it here, and add a `--help` regression check.
