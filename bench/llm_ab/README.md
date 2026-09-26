# bench/llm_ab — LLM A/B benchmark: agent with vs without the simplicio-loop skill

For the canonical release matrix (tasks 1+4, sequential+batch, the one
`standard.sh`/`standard.py` command, metrics, results naming and the "run it
every release" policy), see [`STANDARD.md`](STANDARD.md).

Compares the SAME agentic coding loop (`agent.py`) run twice on the same
dependent tasks (`--tasks`, default 2) and the same model:

- **normal** — the agent gets a plain system prompt and the task text. It
  decides for itself which shell commands to run.
- **simplicio** — the agent gets the SAME system prompt, plus the full
  `.claude/skills/simplicio-loop/SKILL.md` text appended, and its user
  prompt is prefixed with `/simplicio-loop `. It decides for itself whether
  and how to run `simplicio-loop orient`/`prepare`/`wave`/`verify` — this
  harness never scripts the wave flow directly; the skill does, through the
  model.

The only difference between the two arms is the prompt. Everything else —
the tool-calling loop, the single `bash` tool, the fixture, the acceptance
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

## The agent loop (`agent.py`)

`run_agent(arm, system_prompt, user_prompt, repo_dir, max_turns, cmd_timeout)`
is an OpenAI-style tool-calling loop with exactly ONE tool, `bash`
(`{"command": str}`), run as `bash -lc <command>` in `repo_dir`. Each turn:
ask the model for the next step; if it replies with `tool_calls`, run every
requested command and feed back its combined stdout/stderr (truncated to
the **last 8000 characters**) as a `tool` message; stop when the model
replies with no `tool_calls` (it says it's done) or `max_turns` is reached
(default 30). The subprocess `PATH` is the caller's environment with the
venv `bin/` holding `simplicio-loop`/`simplicio-mapper`/`simplicio-dev-cli`/
`simplicio-fast` (`dirname(sys.executable)`) prepended, so the simplicio arm
can actually invoke those binaries from its bash tool.

Every LLM call (tokens prompt/completion/reasoning/cached, cost, latency)
and every command (text, exit code, wall/CPU time, whether its first token
is a `simplicio-*` binary, output size) is recorded on the task's result.

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
`--max-turns` (default 30, caps LLM calls per task), `--cmd-timeout`
(default 180s, per bash-tool command), `--batch` (all tasks in ONE user
prompt / one agent session per arm instead of one session per task --
acceptance is still checked per task by the harness after the session; adds
a `-batch` suffix to the results filename), `--effort-policy {hints,none}`
(default `hints`: honor the most recent `effort`/`next_effort` hint parsed
from a simplicio tool output for the next LLM call's reasoning effort; see
"Per-phase reasoning effort" below).

## Per-phase reasoning effort (issue #1310 follow-up)

`simplicio_loop/effort.py` gives `orient --brief` an `effort` table
(`plan`/`execute`/`review`) and `simplicio-loop apply`'s result a
`next_effort` field. With `--effort-policy hints` (the default), `agent.py`
parses the most recent such hint out of the simplicio arm's own tool output
(`agent.parse_effort_hint`) and sends it as OpenRouter's
`"reasoning": {"effort": ...}` on the NEXT LLM call
(`llm_client.chat(..., reasoning_effort=...)`) -- until a hint is seen, no
`reasoning` field is sent at all (the model's own default). The normal arm
never runs a command that prints such a hint, so it naturally stays at
`default` for the whole run -- no per-arm branching in `agent.py` itself.
`--effort-policy none` disables this for the A/B control. Every LLM call
records its own `reasoning_effort` (`None`/`"low"`/`"medium"`/`"high"`);
`aggregate.effort_counts` and `report.build_effort_table` show the per-arm
distribution.

## What each metric means

- **turns** — how many LLM calls the agent needed for one task before
  replying with no more tool calls (or hitting `--max-turns`).
- **commands** — every bash-tool command the agent ran, in order, with exit
  code and wall/CPU time (`measure.py`: `RUSAGE_CHILDREN` deltas,
  `/proc/<pid>/status` `VmHWM` polling for peak RSS); `is_simplicio` flags a
  command whose first token starts with `simplicio-` (loop/mapper/dev-cli/
  fast).
- **tokens/cost** — read straight from the OpenRouter response's `usage`
  block (`prompt_tokens`, `completion_tokens`,
  `completion_tokens_details.reasoning_tokens`,
  `prompt_tokens_details.cached_tokens`, `usage.cost`); never estimated. See
  "Real cost from OpenRouter" below for the cache-aware breakdown built on
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

For every ok LLM call whose response carried an `id`, after the arm finishes
the harness also fetches
`GET https://openrouter.ai/api/v1/generation?id=<id>` with that arm's own
key (`llm_client.fetch_generation_stats`) for the native (provider-side)
token counts and OpenRouter's own reported cost/cache-discount figures,
stored as `call["generation_stats"]`. Generation stats can lag the chat
response by a few seconds, so a 404 is retried once after 1s; if it's still
unavailable the call simply carries `{"available": False}` -- never a
fabricated number.

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
- `agent.py` — the shared tool-calling agent loop + its pure helpers
  (`truncate_tail`, `classify_command`, `parse_tool_calls`, `summarize`).
- `aggregate.py` — pure results aggregation (tokens, CPU/RAM, success,
  turns, command/check counts, history diffing/loading, task-count-aware).
- `cost.py` — pure OpenRouter pricing/generation-stats parsing and
  cache-aware cost breakdown (`parse_pricing`, `parse_generation_response`,
  `cost_breakdown`, `cost_table`, `pricing_table`); no network I/O.
- `verdict.py` — pure, data-driven verdict text.
- `checker.py` — subprocess wrapper around the harness-owned checker
  (`checker=` selects `check_cadastro.py`/`check_login.py`); also seeds a
  fresh fixture copy per arm.
- `llm_client.py` — stdlib OpenRouter client (`SIMPLICIO_BENCH_KEYS`),
  optional OpenAI-style `tools` for tool-calling, plus the real-cost fetch
  helpers (`fetch_model_pricing`, `fetch_generation_stats`).
- `measure.py` — wall/CPU/peak-RSS measurement helpers.
- `report.py` — REPORT.html builder (pt-BR, base64 matplotlib PNGs), incl.
  the pricing/cost tables.
- `run.py` — CLI entry point; builds the per-arm prompts (base prompt, or
  base prompt + SKILL.md text), picks the task set (`--tasks`), fetches
  pricing once, and drives both arms through `agent.py`.
- `fixture/` — the minimal seed repo (`README.md`, placeholder
  `cadastro.html`/`login.html`, `tests/check_cadastro.py`/`check_login.py`).
- `standard.py` / `standard.sh` — the ONE canonical benchmark matrix command
  (tasks 1+4, sequential+batch, both arms) for every release; see
  [`STANDARD.md`](STANDARD.md).
