# 5-side comparison — v13 (baseline / cli / cli+sp / cli+ag / cli+sp+ag)

Date: **2026-05-30**

Five sides on **two metrics** (functional/PHPUnit + regex), three models.

## Sides

| key | label | description |
|---|---|---|
| `sem`  | baseline       | raw one-line goal. No simplicio anywhere. |
| `com`  | cli alone      | the simplicio-cli 6-layer task contract (role/stack, goal, target, criteria, constraints, output shape). |
| `sp`   | cli + sp       | simplicio-prompt v1.9 runtime wrapping the cli 6-layer as user-input-X. Composition. |
| `ag`   | cli + ag       | cli 6-layer as the seed of the verify-loop (PHPUnit tail / missing-pattern feedback over up to 3 attempts). |
| `spag` | cli + sp + ag  | **full stack:** sp-wrapped cli as the verify-loop seed. Composition + retry. |

## Benches

| bench | n | oracle |
|---|---|---|
| exec   | 12 | real `vendor/bin/phpunit` on `wesleysimplicio/sistema-sindico` |
| regex  | 10 | structural pattern match per `bench/cases_offline.json` |

## Models

- `meta-llama/llama-3.2-3b-instruct` (n=12)
- `google/gemma-3-4b-it` (n=12)
- `qwen/qwen-2.5-coder-32b-instruct` (n=12)

## Headline — pct per side, both metrics

| Model | metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |
|---|---|---|---|---|---|---|---|---|---|---|
| `llama-3.2-3b-instruct` | exec | 8% | 8% | 8% | 8% | 8% | **+0** | **+0** | **+0** | **+0** |
| `llama-3.2-3b-instruct` | regex | 32% | 69% | 67% | 88% | 76% | **+37** | **+35** | **+56** | **+44** |
| `gemma-3-4b-it` | exec | 33% | 66% | 50% | 66% | 41% | **+33** | **+17** | **+33** | **+8** |
| `gemma-3-4b-it` | regex | 42% | 92% | 88% | 92% | 92% | **+50** | **+46** | **+50** | **+50** |
| `qwen-2.5-coder-32b-instruct` | exec | 8% | 16% | 16% | 16% | 16% | **+8** | **+8** | **+8** | **+8** |
| `qwen-2.5-coder-32b-instruct` | regex | 34% | 44% | 38% | 82% | 80% | **+10** | **+4** | **+48** | **+46** |

## Verify-loop convergence (exec)

Average attempts consumed by the ag-based sides (1=passed first try; 3=ran loop to exhaustion).

| Model | cli+ag avg | cli+sp+ag avg |
|---|---|---|
| `llama-3.2-3b-instruct` | 2.83 | 2.83 |
| `gemma-3-4b-it` | 1.67 | 2.17 |
| `qwen-2.5-coder-32b-instruct` | 2.67 | 2.67 |

## Cost & latency (exec, per call avg)

Tokens/call and ms/call averaged across the 12 cases. ag-based sides sum across attempts.

| Model | side | tokens/call | ms/call |
|---|---|---|---|
| `llama-3.2-3b-instruct` | baseline | 1079 | 1757 |
| `llama-3.2-3b-instruct` | cli alone | 1273 | 1764 |
| `llama-3.2-3b-instruct` | cli + sp | 1976 | 822 |
| `llama-3.2-3b-instruct` | cli + ag | 3103 | 5224 |
| `llama-3.2-3b-instruct` | cli + sp + ag | 2828 | 2584 |
| `gemma-3-4b-it` | baseline | 1449 | 10010 |
| `gemma-3-4b-it` | cli alone | 1655 | 9575 |
| `gemma-3-4b-it` | cli + sp | 2655 | 11013 |
| `gemma-3-4b-it` | cli + ag | 3091 | 19180 |
| `gemma-3-4b-it` | cli + sp + ag | 4616 | 21105 |
| `qwen-2.5-coder-32b-instruct` | baseline | 1005 | 8580 |
| `qwen-2.5-coder-32b-instruct` | cli alone | 1215 | 8597 |
| `qwen-2.5-coder-32b-instruct` | cli + sp | 2268 | 8656 |
| `qwen-2.5-coder-32b-instruct` | cli + ag | 2463 | 25794 |
| `qwen-2.5-coder-32b-instruct` | cli + sp + ag | 3562 | 25986 |

## Per-task × model (exec, base / cli / cli+sp / cli+ag / cli+sp+ag)

Format per cell: `b/c/s/a/sa` where each char is `P` (pass) or `.` (fail).

| Task | llama-3.2-3b-instruct | gemma-3-4b-it | qwen-2.5-coder-32b-instruct |
|---|---|---|---|
| password_strength | ././././. | ./P/P/P/. | ././././. |
| password_require_symbol | ././././. | ././././. | ././././. |
| env_get_int | ././././. | ./P/P/P/P | ./P/P/P/P |
| env_get_bool | ././././. | ./P/./P/. | P/P/P/P/P |
| admin_only_allowed_roles | P/P/P/P/P | P/P/P/P/P | ././././. |
| rate_limit_bucket_key | ././././. | ./P/P/P/P | ././././. |
| base_repository_build_where_sql | ././././. | ././././. | ././././. |
| router_has | ././././. | P/P/P/P/P | ././././. |
| bugfix_password_policy_lowercase | ././././. | P/P/P/P/P | ././././. |
| password_assess | ././././. | P/P/./P/. | ././././. |
| base_repository_build_update_sql | ././././. | ././././. | ././././. |
| router_extract_params | ././././. | ././././. | ././././. |
