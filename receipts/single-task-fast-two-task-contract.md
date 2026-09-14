# `single-task-fast` ordered two-task contract receipt

- Source: `https://github.com/wesleysimplicio/simplicio-loop.git`
- Base: `main` at `f464ed8820de6e3864ab8aacc8f599957073ef71`
- Owned checkout: `/projetos/ai/benchmark-checkers-openrouter-real-20260912/loop-main-luna`
- Branch: `codex/two-task-single-task-fast`
- Implementation commit: `a2188fd8ac8c35f4dd9928ae35683827ec7974fc`
- Pull request: `https://github.com/wesleysimplicio/simplicio-loop/pull/1255`

## Red evidence before the fix

- Exact benchmark Markdown task file through the old command: exit `2`,
  `status=BLOCKED`, `reason_code=invalid_task_file` (the old JSON-only
  boundary rejected it before dispatch).
- Equivalent two-task JSON collection through the old command: exit `2`,
  `status=ESCALATED`, `route=full-pipeline`,
  `reason_code=task_count_not_one`. The old dispatcher returned before any
  task operation, so neither task executed.

## Green/provider-free evidence after the fix

- Focused contract probe: passed with an injected collection runner; both tasks
  were topologically ordered creation then edit, and the fake invoked Mapper,
  Fast, provider, and deterministic Dev CLI once per task.
- Evidence gate probe: passed; a `COMPLETED` result missing per-task evidence
  became `BLOCKED/per_task_evidence_missing`.
- One-task compatibility probe: passed; the one-task input remained on
  `route=single-task-fast` and did not invoke the two-task provider boundary.
- Public help probe: passed; help names the JSON one-task and exactly-two-task
  Markdown contracts, required Fast preparation, and the default OpenRouter
  provider route.
- Exact benchmark Markdown after the fix: exit `2` with explicit
  `BLOCKED/fast_operation_failed` because this checkout has no `simplicio-fast`;
  it did not claim completion.
- `python3 -m py_compile` and `git diff --check`: passed.
- `python3 scripts/check.py`: exit `1`, with the repository’s exact blocker
  `pytest_unavailable`; no pytest module or executable is installed here.
- `simplicio runtime map --repo . --for-llm markdown`: blocked by the managed
  environment’s read-only `/root/.simplicio` path; `simplicio memory` returned
  no results.

Changed files are limited to Loop source (`cli_impl.py`, `intake_planner.py`,
`runner.py`, `task_contract.py`), the focused contract test, this receipt, and
the README/CLI command documentation. Mapper, Fast, Dev CLI, Runtime,
benchmark fixtures, support harnesses, and historical receipts were not
modified.

All diagnostic/test subprocesses were run with
`OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENAI_API_KEY`, and
`ANTHROPIC_API_KEY` unset. No provider network call was made:
`provider_called=false`.

This receipt records contract and regression evidence only; it makes no
benchmark-performance or benchmark-completion claim.
