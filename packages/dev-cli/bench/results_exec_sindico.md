# Execution benchmark — real project, real tasks, real test suite

Date: **2026-05-31**  
Target project: [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico) — a real condominium-management system in pure PHP 8 (public on GitHub, PHPUnit 11)  
Models: `deepseek/deepseek-v4-flash`  
Tasks: **12** additive real-engineering changes across `src/Core/`, `src/Middleware/`, `src/Repositories/`, and routing.

## Methodology — what "pass" actually means

**This is NOT regex pattern-matching on model output. This is NOT a synthetic toy unit-test harness in isolation.** The benchmark runs against an actual published PHP project using the project's real PHPUnit suite (`vendor/bin/phpunit --configuration phpunit.xml.dist`).

For each task:

1. The model is asked for a real engineering change — add a new method to an existing production class (permission helper, env parser, rate-limit key builder, repository SQL builder, route introspection, etc.).
2. Its generated file replaces the original in a working copy of the real repo (with `composer install` deps already in place).
3. A **hidden PHPUnit test** (never shown to the model, asserting BOTH true and false states of the required behaviour) is dropped into `tests/unit/Core/Hidden/`.
4. The **ENTIRE production suite** runs — every pre-existing test of the real codebase plus the hidden one. The model's change must be **correct** (the new test passes) AND must **not break existing behaviour** (every prior test still passes).
5. **Pass = `phpunit` exit code 0** — the same green/red signal the project's CI would use to merge a PR.

All sides emit the complete file (identical output shape); the only variable is the wrapping prompt:

- **baseline**: raw goal + current file content
- **simplicio-cli**: the 6-layer task contract (role/stack, goal, target, criteria as testable states, constraints, output shape)
- **simplicio-cli + simplicio-prompt (composition)**: the Tuple-Space + Yool runtime template from simplicio-prompt wrapping the simplicio-cli 6-layer contract as user input X. Measures whether the runtime adds value ON TOP of an already-sharp 6-layer prompt — not whether sp alone beats raw goal.
- **simplicio-cli + agents (verify-loop)**: same 6-layer contract, but on failure the harness feeds the PHPUnit tail back as classified retry feedback (syntax/assertion/runtime/etc.) and re-prompts up to 3 attempts — the exact loop shipped in `simplicio task --verify` (`simplicio/pipeline.py`).

## Headline

- **Baseline:** 6/12 (50%)
- **simplicio-cli (6-layer):** 11/12 (91%) — **+41 pts vs baseline**
- **simplicio-cli + simplicio-prompt (composition):** 9/12 (75%) — **+25 pts vs baseline · -16 pts vs cli alone**
- **simplicio-cli + agents (verify-loop):** 12/12 (100%) — **+50 pts vs baseline · +9 pts vs cli alone**

## Per-model (pass = full PHPUnit suite green)

| Model | Baseline | cli alone | cli + sp | cli + ag | D cli | D (cli+sp) | D (cli+ag) |
|---|---|---|---|---|---|---|---|
| `deepseek/deepseek-v4-flash` | 6/12 (50%) | 11/12 (91%) | 9/12 (75%) | 12/12 (100%) | **+41** | **+25** | **+50** |

## Per-task × model (baseline / cli / cli+sp / cli+ag)

| Task | deepseek-v4-flash |
|---|---|
| password_strength | ./P/P/P(1) |
| password_require_symbol | P/P/P/P(1) |
| env_get_int | ./P/P/P(1) |
| env_get_bool | ./P/P/P(1) |
| admin_only_allowed_roles | P/P/P/P(1) |
| rate_limit_bucket_key | ./P/P/P(1) |
| base_repository_build_where_sql | P/P/P/P(1) |
| router_has | P/P/./P(1) |
| bugfix_password_policy_lowercase | ./P/./P(1) |
| password_assess | P/P/P/P(1) |
| base_repository_build_update_sql | ././P/P(1) |
| router_extract_params | P/P/./P(1) |

Format suffix `(N)` on cli+ag is the number of verify-loop attempts consumed (1–3). Lower is better; 1 means it passed on the first try, no feedback needed.

Raw counts above are real `vendor/bin/phpunit` exit codes against `sistema-sindico`. `results_exec_sindico.json` holds per-case pass/fail, tokens, latency and a phpunit tail for every side.
