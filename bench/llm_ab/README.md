# bench/llm_ab — LLM A/B benchmark: agent with vs without the simplicio-loop skill

Compares the SAME agentic coding loop (`agent.py`) run twice on the same 2
dependent tasks and the same model:

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

## The 2 tasks (`tasks.py`)

1. **create** — `cadastro.html`: a pure HTML registration `<form
   id="cadastro">` with `name`/`email`/`password` fields and a submit
   control.
2. **edit** — depends on task 1, runs on the tree task 1 left: add `phone`
   and `password_confirm` fields to the same form, keeping the existing
   fields.

Acceptance is **harness-owned**, never asked of the model:
`fixture/tests/check_cadastro.py --stage {1,2}` parses `cadastro.html` with
stdlib `html.parser` and asserts the exact fields/attributes for that stage.
The harness runs it itself after each task to decide `success`; the agent
may also invoke it via its own bash commands to self-check (tracked
separately, see "check runs" below).

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

python3 bench/llm_ab/run.py --arms normal,simplicio \
  --out bench/llm_ab/results
```

Each release: re-run the command above (uses the Python/venv on `PATH` when
invoked, so run it from the venv you want measured — see `--python-bin` for
the checker's own interpreter), commit the new
`bench/llm_ab/results/<UTC-date>-<shortsha>.json` (append-only history —
never edit or delete an old one) and the regenerated `REPORT.html`.
`--skip-report` writes just the JSON (no matplotlib dependency needed);
render the report separately with a Python that has matplotlib:

```bash
python3 bench/llm_ab/report.py --results bench/llm_ab/results/<file>.json \
  --out bench/llm_ab/REPORT.html
```

Useful flags: `--max-turns` (default 30, caps LLM calls per task),
`--cmd-timeout` (default 180s, per bash-tool command).

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
  `prompt_tokens_details.cached_tokens`, `usage.cost`); never estimated.
- **check runs** — how many times the agent itself invoked
  `check_cadastro.py` via its own bash commands (`aggregate.py::
  check_run_count`) — a signal of whether it verified its own work, distinct
  from the harness's own post-task check that decides `success`.
- **verdict** — computed purely from the results dict
  (`verdict.py::compute_verdict`); no number in it is hardcoded.

## Files

- `tasks.py` — the 2-task table, `kind` (create/edit) and `depends_on`.
- `agent.py` — the shared tool-calling agent loop + its pure helpers
  (`truncate_tail`, `classify_command`, `parse_tool_calls`, `summarize`).
- `aggregate.py` — pure results aggregation (tokens, CPU/RAM, success,
  turns, command/check counts, history diffing/loading).
- `verdict.py` — pure, data-driven verdict text.
- `checker.py` — subprocess wrapper around the harness-owned checker; also
  seeds a fresh fixture copy per arm.
- `llm_client.py` — stdlib OpenRouter client (`SIMPLICIO_BENCH_KEYS`),
  optional OpenAI-style `tools` for tool-calling.
- `measure.py` — wall/CPU/peak-RSS measurement helpers.
- `report.py` — REPORT.html builder (pt-BR, base64 matplotlib PNGs).
- `run.py` — CLI entry point; builds the per-arm prompts (base prompt, or
  base prompt + SKILL.md text) and drives both arms through `agent.py`.
- `fixture/` — the minimal seed repo (`README.md`, placeholder
  `cadastro.html`, `tests/check_cadastro.py`).
