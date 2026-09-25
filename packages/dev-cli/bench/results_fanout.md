# Fan-out benchmark — regex vs functional, 4 models × N ∈ {64, 200, 600}

Date: **2026-05-29**  
Engine: `kernel.subagent_runtime.SubagentRuntime` from simplicio-prompt v1.7.0 (PyPI) · `use_cache=False` (every subagent is an independent provider call) · `temperature=0.7` (induces real per-call variance).  
Target project: [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico) — real PHP 8 condominium system on GitHub.  
Models: `Qwen/Qwen3-Coder-30B-A3B-Instruct`, `Qwen/Qwen3-Coder-Next`  
N values: **200**  
Tasks: **12** real engineering changes across `src/Core/`, `src/Middleware/`, `src/Repositories/`, and routing (includes one bug-fix task that scores against the existing `PasswordPolicyTest`, not a new hidden test).

## Methodology

For each (model, task, N), the simplicio-prompt **kernel** launches N real parallel LLM calls on the same prompt (simplicio-cli 6-layer wrap of the task). Every returned solution is scored TWO ways:

1. **Functional (real PHPUnit)** — write the solution to the target file in a working copy of sistema-sindico, install the hidden test for the case (or just keep the existing suite for the bug-fix task), run `vendor/bin/phpunit --configuration phpunit.xml.dist`. Pass = exit code 0.
2. **Regex (cheap structural proxy)** — match a small set of patterns against the solution text (method declared? right keywords? uses the expected APIs?). Per-task patterns in `sindico_cases.REGEX_CHECKS_BY_TASK`.

**The point of carrying both metrics**: where they AGREE, regex is a reasonable cheap proxy; where they DISAGREE (especially regex-PASS while phpunit-FAIL), regex is misleading and the criticism that 'regex doesn't mean the code works' is correct.

## Headline — per (model, N) aggregate across tasks

| Model | N | fn per-attempt | rx per-attempt | fn modal | rx modal | Tokens | Cost | Avg s |
|---|---|---|---|---|---|---|---|---|
| `Qwen/Qwen3-Coder-30B-A3B-Instruct` | **200** | 994/2400 (41%) | 2231/2400 (92%) | 5/12 | 11/12 | 3,498,441 | $0.0000 | 43.3s |
| `Qwen/Qwen3-Coder-Next` | **200** | 2208/2400 (92%) | 2297/2400 (95%) | 12/12 | 12/12 | 3,495,987 | $0.0000 | 20.0s |

## Per N (aggregate across all models)

| N | fn per-attempt | rx per-attempt | fn-vs-rx gap | fn modal | rx modal |
|---|---|---|---|---|---|
| **200** | 3202/4800 (66%) | 4528/4800 (94%) | **+28** | 17/24 | 23/24 |

## Regex-vs-functional disagreement (per task, averaged across models × N)

When the regex score is much higher than phpunit (positive gap), regex is a **false positive** — the code looks right but doesn't actually pass. When phpunit is higher, regex misses real wins.

| Task | fn per-attempt | rx per-attempt | gap (rx − fn) |
|---|---|---|---|
| `password_strength` | 98% | 100% | **+2** |
| `password_require_symbol` | 46% | 57% | **+11** |
| `env_get_int` | 49% | 100% | **+51** ⚠️ regex inflates |
| `env_get_bool` | 24% | 74% | **+50** ⚠️ regex inflates |
| `admin_only_allowed_roles` | 50% | 100% | **+50** ⚠️ regex inflates |
| `rate_limit_bucket_key` | 50% | 100% | **+50** ⚠️ regex inflates |
| `base_repository_build_where_sql` | 50% | 100% | **+50** ⚠️ regex inflates |
| `router_has` | 50% | 100% | **+50** ⚠️ regex inflates |
| `bugfix_password_policy_lowercase` | 100% | 100% | **+0** |
| `password_assess` | 100% | 100% | **+0** |
| `base_repository_build_update_sql` | 80% | 100% | **+20** ⚠️ regex inflates |
| `router_extract_params` | 100% | 100% | **+0** |

## Per-task × model × N detail

Format: `fn% / rx% / fn-modal-pass`. P = phpunit modal PASS, . = fail.

### `password_strength`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |  97% / 100% / P |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `password_require_symbol`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% /  15% / . |
| `Qwen3-Coder-Next` |  93% /  99% / P |

### `env_get_int`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% / 100% / . |
| `Qwen3-Coder-Next` |  99% / 100% / P |

### `env_get_bool`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% / 100% / . |
| `Qwen3-Coder-Next` |  49% /  49% / P |

### `admin_only_allowed_roles`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% / 100% / . |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `rate_limit_bucket_key`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% / 100% / . |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `base_repository_build_where_sql`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% / 100% / . |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `router_has`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` |   0% / 100% / . |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `bugfix_password_policy_lowercase`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 100% / 100% / P |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `password_assess`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 100% / 100% / P |
| `Qwen3-Coder-Next` | 100% / 100% / P |

### `base_repository_build_update_sql`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 100% / 100% / P |
| `Qwen3-Coder-Next` |  61% / 100% / P |

### `router_extract_params`

| Model \\ N | 200 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 100% / 100% / P |
| `Qwen3-Coder-Next` | 100% / 100% / P |
