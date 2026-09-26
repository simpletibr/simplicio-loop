# bench/llm_ab — LLM A/B benchmark: agent with vs without the simplicio-loop skill

For the canonical release matrix (tasks 1+4, sequential+batch, the one
`standard.sh`/`standard.py` command, metrics, results naming and the "run it
every release" policy), see [`STANDARD.md`](STANDARD.md).

Compares the SAME real agent harness — [OpenCode](https://github.com/sst/opencode)
(`opencode-ai` on npm), not a hand-rolled Python tool-calling loop — run
twice on the same dependent tasks (`--tasks`, default 2) and the same model
(issue #1325; the earlier version of this benchmark measured
`bench/llm_ab/agent.py`, a minimal OpenAI-style loop with one `bash` tool,
instead of a real agent):

- **normal** — OpenCode as installed, no skill available in the repo it is
  pointed at. It decides for itself which shell commands to run.
- **simplicio** — the SAME OpenCode CLI, but with
  `.claude/skills/simplicio-loop/` copied into that arm's repo (OpenCode
  scans a repo's `.claude/skills` by default, alongside its own native
  `.opencode/skills` — see `STANDARD.md` § OpenCode for how that was
  confirmed) and its user prompt prefixed with `/simplicio-loop `. It
  decides for itself whether and how to run
  `simplicio-loop orient`/`prepare`/`wave`/`verify` — this harness never
  scripts the wave flow directly; the skill does, through the model.

The only difference between the two arms is whether the skill directory is
present and the prompt prefix. Everything else — the OpenCode binary, its
model, its own internal tool-calling loop, the fixture, the acceptance
checker — is identical, so the comparison isolates the effect of the skill
itself.

## Task sets (`tasks.py`, `--tasks {1,2,4}`)

`--tasks` picks how many of the 4 dependent HTML tasks to run
(`tasks.task_set(n)`); each later task runs on the tree the previous one
left, for both arms identically:

1. **create** (`--tasks 1` and up) — `cadastro.html`: a pure HTML
   registration `<form id="cadastro">` with `name`/`email`/`password` fields
   and a submit control.
2. **edit** (`--tasks 2`, the default, and up) — depends on task 1: add
   `phone` and `password_confirm` fields to the same form, keeping the
   existing fields.
3. **create** (`--tasks 4` only) — `login.html`: a pure HTML login `<form
   id="login">` with `email`/`password` fields and a submit control.
4. **edit** (`--tasks 4` only) — depends on task 3: add a `remember`
   checkbox to the same form, and a `<a href="cadastro.html">` link to the
   signup page.

Acceptance is **harness-owned**, never asked of the model: each task
declares its own `checker` script (`tasks.py`'s `checker` field) —
`fixture/tests/check_cadastro.py --stage {1,2}` for tasks 1-2,
`fixture/tests/check_login.py --stage {1,2}` for tasks 3-4 — both parse the
target HTML with stdlib `html.parser` and assert the exact fields/attributes
for that stage. The harness runs the right one itself after each task to
decide `success`; the agent may also invoke it via its own bash commands to
self-check (tracked separately, see "check runs" below).

Because the task count changes what's being measured, results are never
compared across different `--tasks` values: the results filename carries the
count (`<date>-<shortsha>-t<N>.json`, see "Running it" below) and
`aggregate.load_history`/the report's history section only diff a run
against earlier runs with the SAME `-tN` suffix.

## The agent driver (`opencode_agent.py`)

`run_opencode(arm, prompt, repo_dir, config_dir=..., timeout=..., skill=bool)`
runs the real `opencode run --model openrouter/deepseek/deepseek-v4.1-flash
--format json --auto --dir <repo_dir> <prompt>` and parses its JSON event
stream (`parse_run_events`). `--auto` auto-approves bash/edit permissions
non-interactively; OpenCode drives its OWN multi-turn tool-calling loop
internally — this harness never talks to the LLM directly for either arm.
`skill=True` (the simplicio arm) copies `.claude/skills/simplicio-loop/`
into `repo_dir` and prefixes the prompt with `/simplicio-loop `; `skill=False`
(the normal arm) does neither. `config_dir` becomes OpenCode's own
`HOME`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME` for that invocation — a per-arm
scratch directory, never the real `~` (see `STANDARD.md` § OpenCode for why
that isolation is necessary). The subprocess `PATH` is the caller's
environment with the venv `bin/` holding
`simplicio-loop`/`simplicio-mapper`/`simplicio-dev-cli`/`simplicio-fast`
(`dirname(sys.executable)`) prepended, so the simplicio arm can actually
invoke those binaries from OpenCode's own bash tool. The OpenRouter key
reaches the child process ONLY via the `OPENROUTER_API_KEY` environment
variable — never on the command line.

One OpenCode `step-finish` event is one LLM call; every LLM call (tokens
input/output/reasoning/cached, OpenCode's own reported cost, latency) and
every `bash` tool event (command text, exit code, wall time when OpenCode
reports it, whether its first token is a `simplicio-*` binary, output size)
is recorded on the task's result, in the same shape the rest of the
pipeline (`aggregate.py`/`report.py`/`cost.py`) already consumes. See
"Real cost from OpenRouter" below for how the REPORTED cost is reconciled
against the real BILLED cost.

## Two fresh repos, sequential tasks, harness-owned commits

Each arm gets its own fresh seeded copy of `fixture/` (`checker.seed_repo`),
`git init` + an initial commit. Tasks run **sequentially in that same repo**:
after each task the harness commits (`git add -A && git commit`, skipped if
nothing changed) so task 2 starts from whatever task 1's agent actually left
on disk — for both arms, identically.

## Running it

```bash
# once, in this repo:
bash scripts/dev_install.sh && source .venv/bin/activate

# once, OUTSIDE this repo (OpenCode is a benchmark tool, not a package
# dependency -- never installed into this repo's own node_modules/venv):
npm install --prefix /path/to/opencode-install opencode-ai
export SIMPLICIO_BENCH_OPENCODE_BIN=/path/to/opencode-install/node_modules/.bin/opencode

# keys.env (never commit it): OR_KEY_NORMAL / OR_KEY_SIMPLICIO
export SIMPLICIO_BENCH_KEYS=/path/to/keys.env

python3 bench/llm_ab/run.py --arms normal,simplicio --tasks 2 \
  --out bench/llm_ab/results
```

Each release: re-run the command above (uses the Python/venv on `PATH` when
invoked, so run it from the venv you want measured — see `--python-bin` for
the checker's own interpreter), commit the new
`bench/llm_ab/results/<UTC-date>-<shortsha>-t<N>.json` (`N` is `--tasks`;
append-only history — never edit or delete an old one) and the regenerated
`REPORT.html`. `--skip-report` writes just the JSON (no matplotlib
dependency needed); render the report separately with a Python that has
matplotlib:

```bash
python3 bench/llm_ab/report.py --results bench/llm_ab/results/<file>.json \
  --out bench/llm_ab/REPORT.html
```

Useful flags: `--tasks {1,2,4}` (default 2, see "Task sets" above),
`--task-timeout` (default `opencode_agent.DEFAULT_RUN_TIMEOUT`, 900s: the
wall-clock cap for one `opencode run` invocation per task -- OpenCode
manages its own internal turn loop, so there is no separate
`--max-turns`/`--cmd-timeout` the way the retired Python loop had),
`--batch` (all tasks in ONE user prompt / one OpenCode session per arm
instead of one session per task -- acceptance is still checked per task by
the harness after the session; adds a `-batch` suffix to the results
filename).

## Per-call reasoning effort is not controllable (issue #1325)

The retired `agent.py` parsed `orient --brief`'s `effort` table
(`plan`/`execute`/`review`, `simplicio_loop/effort.py`) and
`simplicio-loop apply`'s `next_effort` field out of the simplicio arm's own
tool output and sent it as OpenRouter's `"reasoning": {"effort": ...}` on
the very next LLM call it made directly. OpenCode does not expose that
granularity: its own `--variant` flag (reasoning effort: `low`/`high`/...)
only applies to the WHOLE `opencode run` invocation, not to an individual
internal LLM step, and this benchmark's harness never calls the LLM
directly any more -- OpenCode does, internally. Every recorded `llm_call`
therefore carries `reasoning_effort: None` for both arms; `--variant` is not
set by this harness (both arms get OpenCode's own default), and
`aggregate.effort_counts`/`report.build_effort_table` are kept (not
dropped) because the resulting table is real, non-fabricated data that
documents this limitation (100% `default` for both arms) rather than
hiding it.

## What each metric means

- **turns** — how many internal LLM steps OpenCode itself took for one task
  (one `step-finish` event each) before it stopped, or `--task-timeout` was
  hit.
- **commands** — every `bash` tool event OpenCode emitted, in order, with
  exit code and wall time OpenCode itself reports on the event
  (`opencode_agent.parse_run_events`); `is_simplicio` flags a command whose
  first token starts with `simplicio-` (loop/mapper/dev-cli/fast). CPU/peak
  RSS per command are not measurable through the OpenCode CLI (OpenCode
  itself shells out to bash, not this harness) -- `measure.py`'s
  `RUSAGE_CHILDREN`/`VmHWM` measurement instead covers the WHOLE `opencode
  run` process for that task. Unlike the retired `agent.py` (whose single
  tool WAS bash), real OpenCode also ships native `edit`/`write`/etc. tools
  -- a task the model solves entirely through one of those (observed for
  simple create tasks on the normal arm) legitimately shows `n_commands: 0`
  even though the file was written; `commands` counts bash-tool use
  specifically (relevant to whether the simplicio arm actually invoked a
  `simplicio-*` binary), not every file mutation.
- **tokens/cost** — read straight from each OpenCode `step-finish` event's
  own `tokens`/`cost` fields (never estimated); see "Real cost from
  OpenRouter" below for the cache-aware breakdown built on
  top of these.
- **check runs** — how many times the agent itself invoked the harness
  checker (`check_cadastro.py`/`check_login.py`) via its own bash commands
  (`aggregate.py::check_run_count`) — a signal of whether it verified its
  own work, distinct from the harness's own post-task check that decides
  `success`.
- **verdict** — computed purely from the results dict
  (`verdict.py::compute_verdict`); no number in it is hardcoded.

## Real cost from OpenRouter (`cost.py`, `llm_client.py`)

Every `run.py` invocation fetches the LIVE, current price for `lc.MODEL`
(`deepseek/deepseek-v4.1-flash`) from the public
`GET https://openrouter.ai/api/v1/models` endpoint (no key needed) --
`llm_client.fetch_model_pricing()` / `cost.parse_pricing()` -- and stores it
under `results["meta"]["pricing"]` (`prompt`, `completion`,
`input_cache_read`, and `input_cache_write`/`internal_reasoning` when the
model publishes them, plus `fetched_at`). It is never hardcoded, so it
tracks OpenRouter's own price changes.

**Real BILLED cost (issue #1325):** `opencode_agent.run_opencode` reads
`GET https://openrouter.ai/api/v1/key`'s cumulative `data.usage` (USD) with
that arm's own key immediately before and after the `opencode run`
invocation, then polls the same endpoint (up to ~20s, every 2s --
`poll_billed_delta`) until the usage actually moves; the observed delta
becomes `totals["cost_usd"]` with `totals["cost_source"] =
"billed-delta"`. OpenRouter's usage ledger can lag past that window; when it
never moves, `totals["cost_usd"]` stays the SUM of OpenCode's own
per-step reported cost (`totals["cost_usd_opencode_reported"]`,
`cost_source = "opencode-reported"`) instead -- never a fabricated number,
and the report shows which source backs each figure.

`cost.cost_breakdown()` computes, per arm/task-kind
(`cost.cost_table()`, embedded in `results["cost_report"]` and rendered in
`REPORT.html`): `uncached_input_tokens * prompt_price +
cached_input_tokens * input_cache_read_price + output_tokens *
completion_price` (output already includes reasoning tokens, matching
OpenRouter's `usage.completion_tokens`), alongside OpenRouter's own reported
cost (`usage.cost`) for comparison, and the cache savings
(`cached_tokens * (prompt_price - input_cache_read_price)`) and cache hit %
(`cached_tokens / prompt_tokens`). `REPORT.html`'s "Preço por token" and
"Custo real" sections render `cost.pricing_table()`/`cost.cost_table()`
directly -- reported vs computed cost side by side, per arm and task kind.

## Files

- `tasks.py` — the task table (`TASKS` + `LOGIN_TASKS`, `kind`
  create/edit, `depends_on`, `checker`) and `task_set(n)` for `--tasks
  {1,2,4}`.
- `opencode_agent.py` — drives the real `opencode` CLI per task/arm
  (`run_opencode`), parses its JSON event stream (`parse_run_events`),
  aggregates totals (`summarize`) and reconciles the real billed cost
  (`fetch_key_usage_usd`, `poll_billed_delta`).
- `aggregate.py` — pure results aggregation (tokens, CPU/RAM, success,
  turns, command/check counts, history diffing/loading, task-count-aware).
- `cost.py` — pure OpenRouter pricing/generation-stats parsing and
  cache-aware cost breakdown (`parse_pricing`, `parse_generation_response`,
  `cost_breakdown`, `cost_table`, `pricing_table`); no network I/O.
- `verdict.py` — pure, data-driven verdict text.
- `checker.py` — subprocess wrapper around the harness-owned checker
  (`checker=` selects `check_cadastro.py`/`check_login.py`); also seeds a
  fresh fixture copy per arm.
- `llm_client.py` — stdlib OpenRouter client: `keys_path()`/`get_key()`
  (`SIMPLICIO_BENCH_KEYS`), `fetch_json`, `fetch_model_pricing` (pricing
  lookup, used regardless of which agent drives the benchmark).
- `measure.py` — wall/CPU/peak-RSS measurement helpers (used here to time
  the whole `opencode run` subprocess per task).
- `report.py` — REPORT.html builder (pt-BR, base64 matplotlib PNGs), incl.
  the pricing/cost tables.
- `run.py` — CLI entry point; picks the task set (`--tasks`), fetches
  pricing once, and drives both arms through `opencode_agent.run_opencode`.
- `fixture/` — the minimal seed repo (`README.md`, placeholder
  `cadastro.html`/`login.html`, `tests/check_cadastro.py`/`check_login.py`).
- `standard.py` / `standard.sh` — the ONE canonical benchmark matrix command
  (tasks 1+4, sequential+batch, both arms) for every release; see
  [`STANDARD.md`](STANDARD.md).
