# bench/llm_ab — the standard benchmark matrix

This is the canonical benchmark standard for every `simplicio-loop` release.
Run it and commit the results with every release; do not invent a
differently-shaped ad hoc run instead.

## The one command

```bash
export SIMPLICIO_BENCH_KEYS=/path/to/keys.env   # OR_KEY_NORMAL / OR_KEY_SIMPLICIO, never committed
bash scripts/dev_install.sh && source .venv/bin/activate

# once, OUTSIDE this repo -- OpenCode is a benchmark tool, not a package dependency:
npm install --prefix /path/to/opencode-install opencode-ai
export SIMPLICIO_BENCH_OPENCODE_BIN=/path/to/opencode-install/node_modules/.bin/opencode

bash bench/llm_ab/standard.sh
# or, equivalently:
python3 bench/llm_ab/standard.py
# or, passing the keys file directly instead of exporting it:
python3 bench/llm_ab/standard.py --keys-file /path/to/keys.env
# re-render every REPORT-*.html + REPORT.html from existing results (no LLM calls, no keys):
python3 bench/llm_ab/standard.py --reports-only <short-sha>
```

**Cache is always part of the numbers.** Every cost reported anywhere is
the real billed cost (OpenRouter generation stats, cache discount
included), always shown next to the cache hit %, the same tokens'
no-cache cost at the list prompt rate, and the $ the cache saved, priced
from the run's own pricing snapshot. Never compare arms on raw token
counts or list-price cost alone: a larger but mostly cached prompt can
cost less than a smaller uncached one.

Outputs of every run (also from `--reports-only`):

- `REPORT.pdf` — **the report to share**: the summary plus every
  combination's full report (all tables and charts), one per page, printed
  with the Chromium that Playwright already ships (no extra dependency;
  override with `SIMPLICIO_BENCH_CHROMIUM`). A missing Chromium fails the
  run loudly, never silently.
- `REPORT.md` — the summary tables in Markdown.
- `REPORT.html` + `REPORT-<suffix>.html` — the same content as web pages.

`REPORT.html` opens with a summary table: each combination's total, plus
create-only and edit-only rows for the sequential runs. A batch run is one
agent session for every task, so its calls cannot be split per task; its
report says so and points at the sequential run of the same set.

Run it from the venv you want measured (it runs on whatever `python3`/venv is
on `PATH`, exactly like `run.py`). It never reads, prints, or hardcodes a raw
API key — see "Keys" below.

## OpenCode (issue #1325)

Both arms run the real [OpenCode](https://github.com/sst/opencode) agent
(`opencode-ai` on npm), not a hand-rolled Python tool-calling loop (the
retired `bench/llm_ab/agent.py`). Confirmed by inspecting the installed
`opencode` binary and probing real, cheap (fractions of a cent) runs before
wiring the harness to it:

- **Model selection, non-interactive:** `opencode run --model
  openrouter/deepseek/deepseek-v4.1-flash --format json --auto --dir
  <repo>`. The OpenRouter API key reaches OpenCode ONLY via the
  `OPENROUTER_API_KEY` environment variable of the child process — never a
  config file, never a CLI argument (no `providers login` step needed for a
  key-based provider OpenCode already knows about). `--auto` auto-approves
  bash/edit permissions non-interactively (there is no human to click
  "allow"); `--format json` streams one JSON event per line, with no
  interleaved log lines when `--print-logs` is omitted (the default).
- **Isolation:** `HOME`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME` for the child
  process are pointed at a per-arm scratch directory
  (`opencode_agent.build_env`), never the real `~`. This was NOT optional:
  probing `scripts/install_lib.py`'s `copy_skills_opencode`/
  `merge_opencode_mcp` showed they read `HOME` directly (ignoring
  `--target`), so running the installer — or letting OpenCode itself write
  its session/snapshot db — without overriding `HOME` writes into the real
  home directory.
- **Skill install, the OpenCode way:** running the full
  `scripts/install_lib.py opencode --skip-operators --target <repo>`
  installer against each arm's throwaway fixture repo works non-interactively
  (confirmed by running it), but it also installs git pre-commit/pre-push
  hooks, all 7 skills (not just simplicio-loop), and MCP registration into
  that disposable repo — side effects with no purpose for a benchmark task
  repo and a real risk of breaking the harness's own `git commit` calls (a
  secret-scan pre-commit hook running against a bare fixture repo). Instead,
  `opencode_agent.install_skill` copies ONLY `.claude/skills/simplicio-loop/`
  into the arm's repo — confirmed (via `strings` on the installed `opencode`
  binary) to be a location OpenCode scans by default for skills, alongside
  its own native `.opencode/skills/` (`OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`
  is the documented opt-out, meaning the scan is on by default).
- **Per-call reasoning effort is not controllable.** OpenCode's `--variant`
  flag only picks a reasoning effort for the WHOLE `opencode run`
  invocation, not for an individual internal LLM step the way the retired
  `agent.py`'s `effort_policy="hints"` did (parsing `orient --brief`'s
  `plan`/`execute`/`review` hints and re-sending them per call). This
  harness does not set `--variant` (both arms get OpenCode's own default),
  so `report.py`'s effort table shows 100% `default` for both arms — kept,
  not dropped, because it is real data documenting the limitation rather
  than fabricated or hidden.
- **Cold start:** the FIRST `opencode run` invocation against a fresh
  `config_dir` can take minutes (building its local index/session db);
  later invocations against the same `config_dir` are fast (seconds). This
  is why `--task-timeout` defaults to
  `opencode_agent.DEFAULT_RUN_TIMEOUT` (900s) rather than the retired
  harness's 180s per-command cap.

## What the matrix covers

The SAME real agent (OpenCode), run twice per combination — once with no
`simplicio-loop` skill available in the repo (**normal**), once with the
skill installed and the prompt prefixed with `/simplicio-loop `
(**simplicio**) — across:

| Dimension | Values | Why |
|---|---|---|
| Task set (`--tasks`) | `1` (create only), `4` (2 create + 2 edit, dependent) | isolates create-only work from a longer dependent chain; see `bench/llm_ab/README.md` § Task sets |
| Session shape | sequential (`run_arm`, one agent session per task) vs `--batch` (`run_arm_batch`, all tasks in ONE session) | measures whether batching tasks into one conversation changes cost/turns/effort distribution; acceptance is still checked per task by the harness after the session either way |
| Arms | `normal`, `simplicio` | same agent, only the skill differs (see `README.md` § top) |
| Model | `deepseek/deepseek-v4.1-flash` (`llm_client.MODEL`, the harness default) | fixed across the whole matrix so runs are comparable |

That is 4 combinations: `t1`, `t1-batch`, `t4`, `t4-batch` — each `standard.py`
run writes one `results/<date>-<shortsha>-t<N>[-batch].json` and one
`REPORT-<suffix>.html` per combination, plus one combined `REPORT.html` index
linking all four (`standard.build_index`).

`--tasks 2` (create+edit on `cadastro.html` only, the harness's own default)
is intentionally NOT part of the standard matrix — `--tasks 4` already covers
that same dependent create→edit shape and extends it with a second page, so
`t4` is strictly more informative for the same session-shape/arm dimensions.

## Metrics (every REPORT-<suffix>.html renders these, see `report.py`)

- **Turns / commands** — LLM calls and bash-tool commands per task (or per
  batch session), including how many were `simplicio-*` binaries
  (`README.md` § "What each metric means").
- **Wall / CPU** — total wall-clock and `RUSAGE_CHILDREN`-measured CPU time,
  peak RSS.
- **Tokens** — prompt (cached vs uncached), completion, reasoning, straight
  from each OpenCode `step-finish` event's own `tokens` block; never
  estimated.
- **Real OpenRouter cost, cache-aware** — live pricing fetch
  (`llm_client.fetch_model_pricing`) plus the real BILLED cost from an
  OpenRouter key-usage delta (`opencode_agent.fetch_key_usage_usd`/
  `poll_billed_delta`, falling back to OpenCode's own reported cost when the
  ledger doesn't move within the poll window — `totals["cost_source"]`
  says which), broken down by cache hit % and cache savings (`cost.py`;
  `README.md` § "Real cost from OpenRouter").
- **Savings % and $** — normal vs simplicio, per metric (`aggregate.savings`,
  rendered as the "Economia com simplicio" column).
- **Create-only / edit-only tables** — the same comparison table scoped to
  `kind == "create"` and `kind == "edit"` tasks only, same session
  (`report.build_arm_table_rows(arms, task_kind=...)`).
- **Effort per phase** — per-arm count of LLM calls at each reasoning-effort
  value (`default` / `low` / `medium` / `high`), from
  `aggregate.effort_counts`. Since issue #1325 moved both arms onto the real
  OpenCode CLI, this is expected to show 100% `default` for both arms (see
  "OpenCode" above) — kept as real, documenting data rather than dropped.
- **Quality / success** — per-task `success` (the harness-owned checker's
  verdict, never the model's own claim) and the free-text `verdict.py`
  summary.

## Results naming and history rule

`results/<UTC-date>-<shortsha>-t<N>[-batch].json` — append-only, never
edited or deleted. **Only compare runs with the SAME suffix** (`-t1`,
`-t1-batch`, `-t4`, `-t4-batch`): a different task count or a different
session shape (sequential vs batch) measures something different, so
`aggregate.load_history`/each report's "Histórico" section only diffs a run
against earlier runs sharing its exact suffix (`run.result_filename`,
`aggregate.load_history`'s `task_count` filter).

## Run it for every release

Re-run `bash bench/llm_ab/standard.sh` (or `python3 bench/llm_ab/standard.py`)
for every release, and commit:

- the 4 new `bench/llm_ab/results/<date>-<shortsha>-t<N>[-batch].json` files
  (append-only — never edit or delete an older one),
- the 4 regenerated `bench/llm_ab/REPORT-<suffix>.html` files, and
- the regenerated `bench/llm_ab/REPORT.html` index.

## Keys

Never commit a keys file. `standard.py`/`standard.sh` reuse `llm_client.py`'s
existing mechanism unchanged: `SIMPLICIO_BENCH_KEYS` must point at a
`keys.env` file containing

```
OR_KEY_NORMAL=sk-or-...
OR_KEY_SIMPLICIO=sk-or-...
```

(one key per arm, so an OpenRouter dashboard can attribute spend per arm
without mixing usage — see `README.md` § "Running it"). Either export
`SIMPLICIO_BENCH_KEYS` before running the standard command, or pass
`--keys-file /path/to/keys.env` and it is set for that invocation only.
