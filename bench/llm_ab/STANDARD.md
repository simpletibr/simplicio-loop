# bench/llm_ab — the standard benchmark matrix

This is the canonical benchmark standard for every `simplicio-loop` release.
Run it and commit the results with every release; do not invent a
differently-shaped ad hoc run instead.

## The one command

```bash
export SIMPLICIO_BENCH_KEYS=/path/to/keys.env   # OR_KEY_NORMAL / OR_KEY_SIMPLICIO, never committed
bash scripts/dev_install.sh && source .venv/bin/activate

bash bench/llm_ab/standard.sh
# or, equivalently:
python3 bench/llm_ab/standard.py
# or, passing the keys file directly instead of exporting it:
python3 bench/llm_ab/standard.py --keys-file /path/to/keys.env
```

Run it from the venv you want measured (it runs on whatever `python3`/venv is
on `PATH`, exactly like `run.py`). It never reads, prints, or hardcodes a raw
API key — see "Keys" below.

## What the matrix covers

The SAME agentic coding loop (`bench/llm_ab/agent.py`), run twice per
combination — once with no `simplicio-loop` skill (**normal**), once given
the skill and told to invoke it (**simplicio**) — across:

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
  from OpenRouter's `usage` block; never estimated.
- **Real OpenRouter cost, cache-aware** — live pricing fetch
  (`llm_client.fetch_model_pricing`) plus per-call generation stats
  (`fetch_generation_stats`), broken down by cache hit % and cache savings
  (`cost.py`; `README.md` § "Real cost from OpenRouter").
- **Savings % and $** — normal vs simplicio, per metric (`aggregate.savings`,
  rendered as the "Economia com simplicio" column).
- **Create-only / edit-only tables** — the same comparison table scoped to
  `kind == "create"` and `kind == "edit"` tasks only, same session
  (`report.build_arm_table_rows(arms, task_kind=...)`).
- **Effort per phase** — per-arm count of LLM calls at each reasoning-effort
  value (`default` / `low` / `medium` / `high`), from
  `aggregate.effort_counts` — shows whether the simplicio arm's calls
  actually landed at the plan-high/execute-low/review-medium hints emitted
  by `orient --brief`/`apply` (`simplicio_loop/effort.py`), vs the normal
  arm staying at `default` throughout since it never sees those hints.
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
