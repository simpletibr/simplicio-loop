# bench/llm_ab — LLM A/B benchmark: normal agent vs simplicio-loop

Compares a plain LLM-writes-files agent against the `simplicio-loop` flow
(orient → prepare → per-task edit-plan → tick → verify), on the same 2
dependent tasks against the same model, two ways: with Mapper-only context
(`simplicio-files`) and with Mapper+Fast context (`simplicio-fast`).

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
It is the *Independent verifier* and every declared quality-lane command
(Unit/Integration/System/Regression/Benchmark) in the `simplicio-loop`
task file — the same one command per stage, so the lanes stay cheap. No
`Coverage verifier:` line is declared: this fixture has no Python
application code to instrument, so the coverage lane is honestly left
**not applicable** (`quality-matrix.json`'s `coverage.measured` stays
`null`) rather than faked with a hardcoded percentage.

## The 3 arms

- **normal** — plain agent: full file tree + full file contents sent every
  turn, the model replies with complete file contents
  (`{"files":[{"path","content"}]}`), the harness writes them and runs the
  checker. Up to 3 attempts per task, one conversation per task.
- **simplicio-files** — `simplicio-loop orient --json` **without** its
  `fast` block (Mapper-only survey) plus the CURRENT on-disk content of
  `cadastro.html` (the host reads the target before writing `find`/`replace`
  text, per SKILL.md). The model replies with a mechanical edit plan
  (`{"operations":[{"path","find","replace"}]}`), consumed by
  `simplicio-dev-cli` through `simplicio-loop tick`.
- **simplicio-fast** — the same flow, but the orient JSON handed to the
  model **keeps** its `fast` block (`fast.understanding`, `fast.plan`) and
  the harness sends **no separate raw file dump** — only whatever content
  Mapper's own survey already embedded in orient's `targets.files`. This is
  a real, measured trade-off: if Mapper's ranking does not surface the
  target file's content, the model has less ground truth for `find` text
  than the `simplicio-files` arm, and that shows up honestly in its
  success/attempt numbers.

Both `simplicio-*` arms run their two tasks inside **one shared
`simplicio-loop` run**: a single `prepare` compiles `tasks.md` (two task
blocks, `System:`-delimited) into a 2-task run, then `tick <run_id>
--task-index 1` and `tick <run_id> --task-index 2` apply each task in order
against the tree the previous one left. Mapper/Fast run state (generation
ids, cache) is therefore shared across both tasks — see the cache table
below.

## Mapper target-corridor assumption (read this before changing the fixture)

`simplicio-loop`'s Mapper-derived target corridor (`runner.py
_extract_repo_file_hints`) only accepts a **root-level** (no `/`) file
mention as an authorized target when that file **already exists** in the
repo; a path containing `/` is accepted even if it does not exist yet
(`to_create`), but a bare filename like `cadastro.html` is not. Verified
empirically against this exact fixture (see PR description / worker report
for the transcript). Consequently `fixture/cadastro.html` ships as a
one-line HTML-comment placeholder (`<!-- SIMPLICIO-PLACEHOLDER: cadastro.html
not implemented yet. -->`), exactly like the established
`SIMPLICIO-PLACEHOLDER` pattern for Python files in earlier revisions of
this harness — task 1's edit plan targets that exact placeholder line as
`find` and replaces it with the full page, the same "create via find on a
placeholder" trick `simplicio-dev-cli` already documents for genuinely new
files. Each task's `tasks.md` block also declares `Target: ./cadastro.html`
and mentions `./cadastro.html` (path-shaped) in its body, which is
redundant with the placeholder file but keeps the corridor unambiguous.

## Mapper/Fast cache table (cold vs warm orient)

Each `simplicio-*` arm calls `simplicio-loop orient --json` once **cold**
(right after seeding the repo, before `prepare`), then once **warm** per
task (before that task's LLM call). `cache.py::is_cache_hit` compares each
call's Mapper generation
(`.fast.ingest.fast_receipt.mapper.generation`) and Fast generation
(`.fast.generation`) against the immediately preceding call — a hit means
the survey was reused rather than rebuilt. REPORT.html's "Cache do orient"
table reports every call's status, wall/CPU time, and hit/miss.

## Running it

```bash
# once, in this repo:
bash scripts/dev_install.sh && source .venv/bin/activate

# keys.env (never commit it): OR_KEY_NORMAL / OR_KEY_SIMPLICIO_FILES / OR_KEY_SIMPLICIO_FAST
export SIMPLICIO_BENCH_KEYS=/path/to/keys.env

python3 bench/llm_ab/run.py --arms normal,simplicio-files,simplicio-fast \
  --out bench/llm_ab/results
```

Each release: re-run the command above (uses the `simplicio-loop` currently
on `PATH`, so run it against the venv you want measured), commit the new
`bench/llm_ab/results/<UTC-date>-<shortsha>.json` (append-only history —
never edit or delete an old one) and the regenerated `REPORT.html`.
`--skip-report` writes just the JSON (no matplotlib dependency needed);
render the report separately with a Python that has matplotlib:

```bash
python3 bench/llm_ab/report.py --results bench/llm_ab/results/<file>.json \
  --out bench/llm_ab/REPORT.html
```

## What each metric means

- **wall/CPU/peak RSS** — measured per LLM call and per `simplicio-loop`
  subprocess call (`measure.py`: `RUSAGE_SELF`/`RUSAGE_CHILDREN` deltas,
  `/proc/<pid>/status` `VmHWM` polling for peak RSS).
- **tokens/cost** — read straight from the OpenRouter response's `usage`
  block (`prompt_tokens`, `completion_tokens`,
  `completion_tokens_details.reasoning_tokens`,
  `prompt_tokens_details.cached_tokens`, `usage.cost`); never estimated.
- **context bytes sent** — `len()` of the exact prompt text sent that
  attempt (orient JSON string + any raw file dump).
- **check runs** — how many times `check_cadastro.py` actually executed
  (`aggregate.py::check_run_count`), one per attempt that got far enough to
  write a file / apply a plan.
- **verdict** — computed purely from the results dict
  (`verdict.py::compute_verdict`); no number in it is hardcoded.

## Files

- `tasks.py` — the 2-task table, `kind` (create/edit) and `depends_on`.
- `cache.py` — pure Mapper/Fast generation extraction + cache-hit check.
- `aggregate.py` — pure results aggregation (tokens, CPU/RAM, success,
  check-run counts, history diffing/loading).
- `verdict.py` — pure, data-driven verdict text.
- `checker.py` — subprocess wrapper around the harness-owned checker; also
  seeds a fresh fixture copy per arm.
- `llm_client.py` — stdlib OpenRouter client (`SIMPLICIO_BENCH_KEYS`).
- `measure.py` — wall/CPU/peak-RSS measurement helpers.
- `orient.py` — `simplicio-loop orient` wrapper + cache-record builder.
- `runner_normal.py` / `runner_loop.py` — the 3 arms' drivers.
- `report.py` — REPORT.html builder (pt-BR, base64 matplotlib PNGs).
- `run.py` — CLI entry point.
- `fixture/` — the minimal seed repo (`README.md`, placeholder
  `cadastro.html`, `tests/check_cadastro.py`).
