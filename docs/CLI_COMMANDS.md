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
| `login` | Sign in. The login is the same one the Simplicio Runtime uses: both programs share one file (`~/.simplicio/login.json`). The command looks for the Runtime (`simplicio` on PATH, then `~/.simplicio/bin`). If it finds the Runtime, it runs `simplicio login google` in your terminal. Then it reads the shared file and prints the account (e-mail masked), the token expiry and the Runtime version. If the Runtime is absent, standalone login is UNVERIFIED, because this repository documents no sign-in endpoint. The command then prints the Runtime install commands. `--json` prints one JSON document (the Runtime output goes to stderr). `--no-browser` sets `BROWSER=true` for the Runtime (UNVERIFIED that the Runtime obeys it). The Runtime receives a minimal environment: it does not receive `GH_TOKEN`, `GITHUB_TOKEN` or other credentials of your shell. Exit 0 = verified, 1 = not verified. |
| `logout` | Remove the shared login file. By default the Runtime reads the same file, so the Runtime is logged out too. If `SIMPLICIO_247_LOGIN` points to another file, the Runtime stays logged in, and the command says so. Without `--yes` the command removes nothing and exits 2. The command does not revoke the refresh token on the server, because no revoke endpoint is documented here. `--json` prints one JSON document. |
| `auth status` | Print the login state. It shows the file, the account (e-mail masked), the expiry of both tokens and the entitlement tier from the cached validation. It also shows the Runtime version. It warns when the loop and the Runtime use different files. The command never prints a token. `--online` also runs the subscription check. That check can refresh the token once and then asks the server. `--json` prints one JSON document. Exit 0 = a usable login, 1 = no usable login. |
| `install` | Install bundled skills and hooks into a supported runtime. The command is idempotent: it rewrites only the files that differ. It prints what it created and what it updated. It prints how many files did not change. It also prints what it left alone: files that Loop does not own, and entry files such as `AGENTS.md` that already exist. `--check` writes nothing (exit 0 = up to date, 10 = changes pending). `--dry-run` writes nothing. `--json` prints one JSON document. `--global` also refreshes the skills and the host rules of each host that already has them. The command reads the bundled data through `importlib.resources`, so it also works from the binary. |
| `update` | Install the latest GitHub release of `simpletibr/simplicio-loop`, then run `install --global`. The command acts by how Loop was installed (`doctor` shows it). A pip install receives the release wheel. A git checkout is refused: use `git pull` and `bash scripts/dev_install.sh`. A binary downloads `simplicio-loop-v<version>-<os>-<arch>` (`.exe` on Windows) and `SHA256SUMS` from the release. It checks the SHA256 before it changes anything. Then it swaps the file by one rename and keeps the old file as `<name>.bak`. It puts the old file back if the new file does not answer `--version` as the new version. The command refuses a missing asset, a missing or wrong checksum, and a downgrade. On Windows the verified file waits as `<name>.new` and replaces the binary at the next start (UNVERIFIED on a real Windows host). `--check` changes nothing and saves the answer for `doctor`. Its exit codes are 0 (up to date), 10 (update available) and 2 (error). `--dry-run` prints what would run. `--force` reinstalls the latest release and allows a downgrade. |
| `setup` | Run after `install` (`install` starts it in a terminal). It checks Python 3.11 or newer, pip, venv, git, gh, bwrap (Linux) and uv. It finds the agent CLIs of the Runtime host list (`claude`, `codex`, `grok`, `kimi`, `opencode`, `agy`, `copilot` and more) and shows version, login, and watcher support. It picks a default host from the installed hosts that have a login. It finds the GitHub login in this order: `GH_TOKEN`, `GITHUB_TOKEN`, `gh auth token`, the git credential helper, the stored token, a hidden prompt. It checks the token with `GET /user`, warns when `repo` or `workflow` is missing, and shows the masked token and the login. The token goes only to `api.github.com`, and `setup` refuses a redirect. `setup` stores only a token you type or pipe (`~/.simplicio-loop/github.json`, mode 600). `gh` and `uv` come from their official release with a SHA256 check. A missing Python comes from `uv python install`. git and bwrap install only with `--yes`, as root or with `sudo -n`. Otherwise `setup` prints the package manager command. `--check` changes nothing (exit 0 nothing pending, 10 pending). `--dry-run` changes nothing. `--json` prints one JSON document without the token. `--github-token-stdin` reads the token from a pipe. `--host <id>` sets the default host. The command writes `~/.simplicio-loop/setup.json` (mode 600, no secret). `doctor` and the watcher read it. The watcher tries the default host first when `SIMPLICIO_EXEC_FAMILIES` is not set. Windows and macOS: UNVERIFIED. |
| `daemon` | Manage the per-user daemon. Use `serve` to start, `status` to check, `stop` to shut down. |
| `dashboard` | Open the Simplicio Live run panel on 127.0.0.1:8765 (prints a tokenised URL); `--run`, `--repo`, `--port`, `--no-browser`, `--stop`, `--status`, `--snapshot` (with `--history` for the run history page), `--tui`; `--tokens` opens the legacy Token Monitor on port 9090. |
| `task` | Compile, validate, or preview a Markdown task contract. |
| `prototype` | Route prototype planning and validation commands. |
| `plan` | Compile a raw task into a frozen contract. |
| `turbo` | The default way to run a task; `simplicio-loop "<task>"` is the shortest form (a first argument that is not a subcommand is a task, unless it asks for all issues/tickets/tarefas, which goes to the drain intake). No provider and no API key: the invoking model plans and `simplicio-dev-cli` edits, in exactly two commands. `turbo --task T` surveys with Mapper and prints a `simplicio.turbo-request/v1` document (`status: "needs_plan"`: `tasks`, the `map` slice, the current text of the named `files`, `format`, `rules`, and `apply`, the one next command with a heredoc for the plan). A file can be too big for its share of the request (16,000 characters at most). The whole `files` object stays under 40% of the input-token ceiling of `input_ceiling`. The command does not cut such a file at the start. `files[path]` becomes `{total_lines, total_chars, windows: [{start, end, text}], omitted: [{start, end}], more}`. Windows cover the header, `path:LINE`, and each task identifier that exists in the file. A Python `def` or `class` window holds its whole body. `text` is the exact lines, so a `find` copied from it matches. `--window PATH:START-END` adds lines. A plan `{"operations": [], "need": [{"path", "start", "end"}]}` adds lines too. Then nothing is applied and the same run prints its request again. An empty plan over a request with `omitted` lines fails with `turbo_context_truncated`, not `turbo_plan_malformed`. `turbo --apply - [--verify V] <<'PLAN'` reads the find/replace JSON plan from stdin (`--apply FILE` reads a file: the same code path), applies it through dev-cli, runs `--verify`, and prints `simplicio.turbo-run/v1` with `mode: "host"` (`status` ok or failed, `applied`, `failed` with the dev-cli reason and a file excerpt, `verify`). `--task` (repeat for several), `--target`/`--context` (one task), `--tasks-file`, `--window PATH:START-END`, `--verify "<tests>"`. `--provider openrouter` is headless automation only; agents invoking the skill must not use it: one model call per lane to OpenRouter (`deepseek/deepseek-v4.1-flash`, `SIMPLICIO_TURBO_MODEL` overrides; pinned session, reasoning off; a duplicate request only after `SIMPLICIO_TURBO_HEDGE_AFTER` seconds, default 10), a rejected plan goes back once, and it needs `OPENROUTER_API_KEY` (`status: blocked`, `turbo_provider_key_missing` without it). Exit 0 ok or needs_plan, 1 failed, 2 blocked. |
| `prepare` / `arm` | Arm and preflight a run without executing tasks or calling a provider; returns a `run_id` for `tick`, `batch`, `wave`, or `prism`. |
| `run` | Arm, execute, and independently verify a task. |
| `orient` | Build bounded context through the Mapper survey and emit `simplicio.llm-max-speed-orientation/v1` plus a hash-bound `simplicio.loop-orient-receipt/v1` (Mapper-only). `--brief` (repeatable `--task`, issue #1310) renders the compact form: route first (its one next step is the `turbo` command carrying every task and `--verify`), deduped target file content, plan groups, suggested checks, Mapper generation + a `repo_state_chain` fingerprint, and the ops format of `apply`. |
| `apply` | Apply one host-written `ops.json` (issue #1310; `turbo` is the default path, this is for a plan you already have) (`{"tasks":[{"id","operations":[{path,find,replace}],"check","depends_on"}]}`). Validates every `find` in memory before any write (BLOCKED + hint, nothing written, on a miss/non-unique/chained mismatch); mutates through `simplicio-dev-cli` (compile then apply); runs independent file-disjoint chains concurrently via asyncio with an isolated check environment (`PYTHONDONTWRITEBYTECODE`, `PYTEST_ADDOPTS=-p no:cacheprovider`, a per-task `COVERAGE_FILE`); fails closed on a stale `repo_state_chain` (the same generation-identity fingerprint `orient --brief` recorded); writes a receipt under `.simplicio-loop/apply/<run_id>/receipt.json`. Exit 0 only on PASS, 2 on BLOCKED, 1 on FAIL. |
| `retrieve` | Retrieve and verify a tee-cache result. |
| `extensions doctor` | Inspect an exact extension-provider/runtime handshake. |
| `oracle` | Evaluate completion and cross-runtime parity. |
| `status` | Inspect the latest or a selected run. |
| `stack lock/verify` | Create or verify an installed-stack lock. |
| `doctor` | With no subcommand it runs `doctor all`. The `stack`, `source`, `mapper` and `--storage` forms inspect stack identity, source adapters, the mapper build and storage routing, and their output does not change. |
| `doctor all` | Run seven checks. Each check is ok, warn or fail, and it names the fix. The login check shows the login state, the entitlement and the Runtime version. It warns when the loop reads a different login file than the Runtime. The update check reads the cached answer of the last `update --check` with its time, so it works offline. `--online` asks GitHub instead. The distribution check shows `pip`, `source` or `binary`. The runtime check reports the optional Simplicio Runtime. The operators check warns about a `simplicio-mapper` or `simplicio-dev-cli` on PATH when its version or build identity differs from the bundled one. It prints the exact fix command. An old standalone mapper makes tests fail with `mapper_provenance_missing`. The disk check compares the free space of the state folders with the floor of `squads` capacity (2 GiB). The setup check reads `~/.simplicio-loop/setup.json`. It warns when `setup` has not run. It also warns when a required tool, the GitHub login or the default agent CLI is open. The fix is `simplicio-loop setup`. `--json` prints one JSON document. Exit 0 unless a check is fail. A login file that exists but is unreadable, readable by others, or a symlink is fail. Then the exit code is 1. |
| `doctor login` | Run only the login check of `doctor all`. `--json` prints one JSON document. |
| `doctor mapper` | Check that the installed `simplicio_mapper` is the expected build (origin, state dir, source commit); each blocker names a `reason_code` and a `fix`. |
| `inspect` | Inspect MapperStore capabilities and storage routing. |
| `map` | Inspect or build map-service receipts. `map gc [--dry-run] [--keep N] [--max-age S] [--json]` lists or removes stale `baseline-build-*` scratch, orphan locks and old bases. It keeps anything that a lock, a process or a live worktree overlay holds. See `docs/CENTRAL_MAP.md`. |
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
| `handoff` | `handoff write` stores a `simplicio.agent-handoff/v1` document in `.simplicio-loop/orchestrator/handoff/<run>/<n>.json` (mode 0600). It masks secrets in the free text first. `handoff read --run R [--n N]` prints one document. `handoff check` takes `--input-tokens`, `--cache-read` and `--cache-write` of the last request, and `--added-file` for the text that the next request adds. It prints `ok`, `handoff` or `over` for the next request (exit 0, 3 or 4). The ceiling is the `agent_input_token_ceiling` key of `.simplicio-loop/loop.toml` on the default branch. The variable `SIMPLICIO_AGENT_INPUT_TOKEN_CEILING` wins. |

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
short excerpt of the file around a `find` that did not match), `verify`, `wall_s`. `ok` needs a dev-cli edit
receipt (`simplicio.dev-cli.edit-receipt/v1` with `applied: true`) for the apply: without one the status is
`blocked` with `reason_code: "no_apply_receipt"`. Each receipt is persisted under
`.simplicio-loop/orchestrator/runs/<run_id>/receipts/` and listed in `receipts` (`path`, `digest` = sha256 of
the file). Every document carries `run_id`, `prompt_version` and `prompt_sha256` (the plan prompt's version
and template digest) and `execution_report` (the `simplicio.execution-report/v1` record of the run). The
request prints the same `run_id`, and its apply command passes it as `--run-id`, so the request, the apply and
the verify stages land in one run the dashboard lists. Tokens and model calls are `null` (UNVERIFIED) unless the
provider returned usage. A missing plan (an
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
