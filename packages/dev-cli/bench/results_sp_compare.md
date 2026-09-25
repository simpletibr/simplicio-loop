# simplicio-prompt — with vs without (real PHPUnit on sistema-sindico)

Date: **2026-05-28**  
Target project: [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico) — real PHP 8 condominium system, public on GitHub  
simplicio-prompt version under test: **v1.7.0** (post mode-selection rewrite, ONE-SHOT template = 102 lines)  
Models: `google/gemma-3-4b-it`, `meta-llama/llama-3.1-8b-instruct`, `google/gemini-3.5-flash`

## Methodology — what "pass" actually means

**This is NOT regex pattern-matching. This is NOT a synthetic toy unit-test harness in isolation.** For each task the model is asked to add a real engineering change to an existing production class. Its generated file replaces the original in a working copy of the real repo; a **hidden PHPUnit test** (never shown to the model, asserting BOTH true and false states) is dropped into `tests/unit/Core/Hidden/`; the **entire production suite runs**. **Pass = `vendor/bin/phpunit` exit code 0** — the same green/red signal the project's CI uses.

Both compared sides emit the complete file (identical output shape). The only variable is the wrapping prompt:

- **WITHOUT simplicio-prompt** (baseline): raw goal + current file content
- **WITH simplicio-prompt**: the agent-runtime-execution-prompt template prepended as system context, with the task as user input X

For context, the simplicio-cli 6-layer task contract is shown on the right as a third reference column (it is the wrapper the dev-cli ships by default).

## Headline

- **WITHOUT simplicio-prompt** (baseline): 17/36 (47%)
- **WITH simplicio-prompt** (v1.7.0): 16/36 (44%) — **-3 pts vs baseline**
- *Context — simplicio-cli (6-layer):* 27/36 (75%) — *+28 pts vs baseline*

3 of 3 models contributed clean data (36 runs/side). 

## Per-model — WITH vs WITHOUT simplicio-prompt

| Model | WITHOUT (baseline) | WITH simplicio-prompt | Delta (pts) | *cli ref* |
|---|---|---|---|---|
| `google/gemma-3-4b-it` | 4/12 (33%) | 4/12 (33%) | **+0** | *8/12 (66%)* |
| `meta-llama/llama-3.1-8b-instruct` | 5/12 (41%) | 4/12 (33%) | **-8** | *7/12 (58%)* |
| `google/gemini-3.5-flash` | 8/12 (66%) | 8/12 (66%) | **+0** | *12/12 (100%)* |

## Per-task × model (WITHOUT / WITH simplicio-prompt)

| Task | gemma-3-4b-it | llama-3.1-8b-instruct | gemini-3.5-flash |
|---|---|---|---|
| password_strength | . / . | . / . | P / P |
| password_require_symbol | . / . | P / . | P / . |
| env_get_int | . / . | . / . | . / . |
| env_get_bool | . / . | . / . | . / . |
| admin_only_allowed_roles | P / P | P / P | P / P |
| rate_limit_bucket_key | . / . | . / . | . / P |
| base_repository_build_where_sql | . / . | . / . | . / . |
| router_has | P / P | P / P | P / P |
| bugfix_password_policy_lowercase | P / P | P / P | P / P |
| password_assess | P / P | P / P | P / P |
| base_repository_build_update_sql | . / . | . / . | P / P |
| router_extract_params | . / . | . / . | P / P |
## Interpretation

simplicio-prompt v1.7.0 is **net-neutral vs the raw baseline** on the models with clean data this round — no regression, no improvement. The earlier catastrophic regressions on this exact benchmark (Llama-3.1-8B 0/4 vs 2/4 baseline; Gemini Flash 1/4 vs 3/4 baseline) are resolved by the mode-selection rewrite (template split, `agent-runtime-execution-prompt.md` trimmed from 289 to 102 lines, code-focused persona, output-shape examples).

simplicio-prompt does NOT exceed the simplicio-cli 6-layer contract on one-shot code generation in this benchmark, and is not expected to: the two products solve different problems (sp = always-on agent runtime with subagent fan-out; cli = task-shaped contract for a single deliverable). Use cli for single-file code edits, sp for orchestrated multi-step work.

Data source: `/tmp/sp_validation_v3.json` (per-case PHPUnit pass/fail, tokens, latency, phpunit tail for every side). Reproduce with `BENCH_INCLUDE_SP=1 python3 bench/run_exec_sindico.py`.