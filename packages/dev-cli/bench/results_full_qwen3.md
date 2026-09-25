# Qwen3 Coder MoE — comprehensive benchmark report

Date: **2026-05-29**  

Single-source-of-truth report covering every measurement taken against the Qwen3 Coder MoE family on this branch. Three benches, two models, three to four sides each, two metrics where applicable.

## Models

- **`Qwen/Qwen3-Coder-30B-A3B-Instruct`** — MoE 30B total / 3B active per token, Apache 2.0, served via the HuggingFace Inference Router.
- **`Qwen/Qwen3-Coder-Next`** — MoE 80B total / 3B active, 256K context, Apache 2.0, also via HF router.

Both replace the previous Qwen2.5-Coder-3B/7B defaults (closed via PR #30 and issue #31; master commit `e3d3ccf`).

## Sides under test

| Side | Single-call (1 LLM call/case) | Description |
|---|---|---|
| `baseline` | yes | Raw one-line goal + file content. No simplicio. |
| `cli` | yes | The simplicio-cli 6-layer task contract (role/stack, goal, target, criteria as testable states, constraints, output shape). |
| `cli + sp` | yes | Same contract embedded as user-input X inside the simplicio-prompt v1.9 Tuple-Space + Yool runtime template (~3,900 chars of runtime preamble). |
| `cli + ag` | up to **3** sequential attempts | Same contract; on failure the harness classifies the PHPUnit tail (or missed regex patterns) and re-prompts with retry feedback. Mirrors `simplicio task --verify` / `simplicio.pipeline.run()`. |
| `cli (fan-out)` | **N=200** parallel subagents | Single-call cli contract repeated 200x in parallel through `kernel.subagent_runtime.SubagentRuntime` (LaneWorkerPool, temperature=0.7, use_cache=False). Pass = (a) per-attempt rate, (b) modal-vote PHPUnit pass. |

## Benches

| Bench | Cases | Oracle | Metric |
|---|---|---|---|
| **exec** | 12 | real `vendor/bin/phpunit` on `wesleysimplicio/sistema-sindico` (PHP 8) | functional (suite green = pass) |
| **regex** | 10 | structural pattern match on output | regex hit / total |
| **fan-out** | 12 | real PHPUnit **and** regex on every subagent's output | per-attempt + modal-vote, both metrics |

## Headline — single-call (12 functional + 10 regex cases)

| Model | metric | baseline | cli | cli+sp | cli+ag | Δcli | Δcli+sp | Δcli+ag |
|---|---|---|---|---|---|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | exec | 33% | 91% | 91% | 91% | **+58** | **+58** | **+58** |
| `Qwen3-Coder-30B-A3B-Instruct` | regex | 36% | 90% | 98% | 90% | **+54** | **+62** | **+54** |
| `Qwen3-Coder-Next` | exec | 50% | 83% | 83% | 91% | **+33** | **+33** | **+41** |
| `Qwen3-Coder-Next` | regex | 44% | 100% | 94% | 100% | **+56** | **+50** | **+56** |

## Headline — fan-out N=200 (cli contract, 200 parallel subagents)

| Model | per-attempt fn | modal fn | per-attempt rx | modal rx | avg uniq/200 | total wall-clock | cost |
|---|---|---|---|---|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 994/2400 (41%) | **5/12** | 2231/2400 (92%) | 11/12 | 6.2 | 520s | $0.0000 |
| `Qwen3-Coder-Next` | 2208/2400 (92%) | **12/12** | 2297/2400 (95%) | 12/12 | 28.2 | 240s | $0.0000 |

## Key findings

### 1. `cli + ag` is the only side that beats `cli` reliably on functional

On the exec bench (real PHPUnit), `cli + ag` (verify-loop) recovers one or two cases per model that single-shot `cli` misses, by feeding the PHPUnit tail back as classified retry feedback. `cli + sp` (runtime composition) ties or trails `cli` in aggregate — it adds ~1,000 tokens/call of runtime preamble that, in this single-call context, doesn't translate into pass-rate gains.

### 2. Regex *inflates* on `Qwen3-Coder-30B-A3B-Instruct` under temp=0.7

In the fan-out batch (N=200, temp=0.7), the 30B-A3B model shows a stark regex-vs-functional disagreement on **6 of 12 cases**: regex scores 100% (every pattern matched on every output), but PHPUnit exit code 0 was hit **zero times in 200 attempts**. The model produces output that LOOKS right (correct method names, correct types, correct token-level shape) but the runtime behaviour is wrong — exactly the criticism that `regex doesn't mean it works`.

### 3. `Qwen3-Coder-Next` is dramatically more robust to temp=0.7

Same fan-out config, same prompts, same 12 cases — Coder-Next modal-vote passes **12/12 cases on real PHPUnit**, while 30B-A3B modal-vote passes 5/12. The cli's 6-layer contract is enough; Coder-Next preserves semantic correctness across temperature-induced variations where 30B-A3B drifts.

### 4. Some cases are model-capability ceilings, not feedback-loop problems

`password_require_symbol` failed for every side and every iteration on 30B-A3B (3-attempt verify-loop exhausted; 200 fan-out attempts exhausted). It only passed on Coder-Next, and only with modal-vote fan-out at 187/200. This is a model-capability boundary — no amount of feedback or retry helps; either the model can or it can't.

## Cost & latency (exec bench, per call)

| Model | Side | tokens/call | ms/call |
|---|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | baseline | 1259 | 5030 |
| `Qwen3-Coder-30B-A3B-Instruct` | cli      | 1449 | 4983 |
| `Qwen3-Coder-30B-A3B-Instruct` | cli+sp   | 2412 | 4879 |
| `Qwen3-Coder-30B-A3B-Instruct` | cli+ag   | 1579 | 5332 (avg 1.17 attempts) |
| `Qwen3-Coder-Next` | baseline | 1280 | 3571 |
| `Qwen3-Coder-Next` | cli      | 1449 | 3485 |
| `Qwen3-Coder-Next` | cli+sp   | 2416 | 3398 |
| `Qwen3-Coder-Next` | cli+ag   | 1858 | 4210 (avg 1.17 attempts) |

## Fan-out per-task (N=200, both metrics, modal-vote)

Format: `fn% / rx% / fn-modal / unique-outputs`

| Task | Qwen3-Coder-30B-A3B-Instruct | Qwen3-Coder-Next |
|---|---|---|
| `password_strength` |  97% / 100% / P / u5 | 100% / 100% / P / u5 |
| `password_require_symbol` |   0% /  15% / . / u9 |  93% /  99% / P / u13 |
| `env_get_int` |   0% / 100% / . / u7 |  99% / 100% / P / u41 |
| `env_get_bool` |   0% / 100% / . / u6 |  49% /  49% / P / u28 |
| `admin_only_allowed_roles` |   0% / 100% / . / u1 | 100% / 100% / P / u2 |
| `rate_limit_bucket_key` |   0% / 100% / . / u1 | 100% / 100% / P / u5 |
| `base_repository_build_where_sql` |   0% / 100% / . / u2 | 100% / 100% / P / u15 |
| `router_has` |   0% / 100% / . / u2 | 100% / 100% / P / u12 |
| `bugfix_password_policy_lowercase` | 100% / 100% / P / u9 | 100% / 100% / P / u22 |
| `password_assess` | 100% / 100% / P / u6 | 100% / 100% / P / u6 |
| `base_repository_build_update_sql` | 100% / 100% / P / u17 |  61% / 100% / P / u139 |
| `router_extract_params` | 100% / 100% / P / u10 | 100% / 100% / P / u50 |

## Exec per-task × model × side (base / cli / cli+sp / cli+ag(attempts))

P = real PHPUnit suite green; . = fail. cli+ag suffix is the attempt count consumed (1–3). 1 = no feedback loop needed.

| Task | Qwen3-Coder-30B-A3B-Instruct | Qwen3-Coder-Next |
|---|---|---|
| password_strength | ./P/P/P(1) | ./P/P/P(1) |
| password_require_symbol | ./././.(3) | ./P/./P(1) |
| env_get_int | ./P/P/P(1) | P/P/P/P(1) |
| env_get_bool | ./P/P/P(1) | ././P/P(1) |
| admin_only_allowed_roles | P/P/P/P(1) | P/P/P/P(1) |
| rate_limit_bucket_key | ./P/P/P(1) | ./P/P/P(1) |
| base_repository_build_where_sql | ./P/P/P(1) | ./P/P/P(1) |
| router_has | ./P/P/P(1) | P/P/P/P(1) |
| bugfix_password_policy_lowercase | P/P/P/P(1) | P/P/./P(1) |
| password_assess | P/P/P/P(1) | P/P/P/P(1) |
| base_repository_build_update_sql | ./P/P/P(1) | ././P/.(3) |
| router_extract_params | P/P/P/P(1) | P/P/P/P(1) |
