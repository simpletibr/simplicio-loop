# Benchmark — simplicio-cli (offline harness)

Date: **2026-05-30**  
Models: `meta-llama/llama-3.2-3b-instruct`, `google/gemma-3-4b-it`, `qwen/qwen-2.5-coder-32b-instruct`  
Cases: **10** across stacks: `angular`, `dotnet`, `react`  
Base: `https://openrouter.ai/api/v1`

Each check is a deterministic regex against the model output 
(target-file mention, DIFF block, TEST block, contract-state words). 
Same model on both sides — only the prompt structure changes. The 
*without* run is the raw one-line goal; the *with* run wraps the 
same goal in simplicio's 6-layer contract.

## Headline

- **Without simplicio:** 57/156 (36%)
- **With simplicio:** 107/156 (68%)
- **Delta:** **+32 points** (+88% relative)

![pass rate by model](charts/overall.svg)

![gain in points](charts/delta.svg)

## Per-model breakdown

| Model | Cases | Without | With | Delta (pts) | Relative gain |
|---|---|---|---|---|---|
| `meta-llama/llama-3.2-3b-instruct` | 10 | 17/52 (32%) | 36/52 (69%) | **+37** | +112% |
| `google/gemma-3-4b-it` | 10 | 22/52 (42%) | 48/52 (92%) | **+50** | +118% |
| `qwen/qwen-2.5-coder-32b-instruct` | 10 | 18/52 (34%) | 23/52 (44%) | **+10** | +28% |

## Per-case (averaged across models)

![per case](charts/by_case.svg)

| # | Stack | Task | Without | With | Δ |
|---|---|---|---|---|---|
| 1 | `angular` | Hide the Delete button when the current user is not an admin | 40% | 73% | **+33** |
| 2 | `angular` | Disable the email field unless the profile role is editor. | 33% | 60% | **+27** |
| 3 | `angular` | Only show the audit log link for users with role 'auditor'. | 20% | 80% | **+60** |
| 4 | `angular` | Show 'Approve' button only when the order status is 'pending | 33% | 67% | **+33** |
| 5 | `react` | Render the export menu item only for users in the 'analytics | 40% | 73% | **+33** |
| 6 | `react` | Disable the 'Save Draft' button while the form is invalid OR | 56% | 72% | **+17** |
| 7 | `react` | Show a 'No results' empty state when the search returns zero | 33% | 80% | **+47** |
| 8 | `dotnet` | Require the 'CanApprove' policy on the Approve endpoint of t | 40% | 73% | **+33** |
| 9 | `dotnet` | Restrict the GET /reports endpoint so only users in the Mana | 27% | 53% | **+27** |
| 10 | `angular` | Show a warning banner if the user has unsaved changes and tr | 40% | 53% | **+13** |

## Per-stack

![per stack](charts/by_stack.svg)

| Stack | Without | With | Δ |
|---|---|---|---|
| `angular` | 33% | 67% | **+33** |
| `dotnet` | 33% | 63% | **+30** |
| `react` | 44% | 75% | **+31** |

## Output-quality signals (rate across all runs)

Beyond pass-rate, the same outputs are scored on structural quality. 
Each row = % of runs (cases × models) where the signal is present.

| Signal | Without simplicio | With simplicio |
|---|---|---|
| DIFF block present | 0% (0/30) | 90% (27/30) |
| TEST block present | 80% (24/30) | 53% (16/30) |
| target file mentioned | 0% (0/30) | 100% (30/30) |
| avg criteria-keywords hit / run | 9.1 | 5.7 |
| avg output length (chars) | 3861 | 2782 |

## Cost — tokens & wall-clock (measured, per run)

Reported straight from the provider's `usage` field and `time.perf_counter()`. 
*Per-run* = one model call (one case, one side). With simplicio uses more input 
tokens (the 6-layer wrap) and fewer output tokens (model stops guessing earlier).

| Model | Side | Avg prompt tok | Avg completion tok | Avg total tok | Avg latency |
|---|---|---|---|---|---|
| `meta-llama/llama-3.2-3b-instruct` | without | 52 | 509 | 561 | 2005 ms |
| `meta-llama/llama-3.2-3b-instruct` | with    | 247 | 1229 | 1477 | 4630 ms |
| `google/gemma-3-4b-it` | without | 25 | 1716 | 1742 | 22980 ms |
| `google/gemma-3-4b-it` | with    | 225 | 1206 | 1432 | 19669 ms |
| `qwen/qwen-2.5-coder-32b-instruct` | without | 39 | 632 | 672 | 17483 ms |
| `qwen/qwen-2.5-coder-32b-instruct` | with    | 245 | 68 | 314 | 2522 ms |

**Aggregate over the full bench** (30 runs per side):

- without simplicio: 29,758 tokens total · 424.7s wall-clock · 991 tok/run · 14156 ms/run
- with simplicio:    32,239 tokens total · 268.2s wall-clock · 1074 tok/run · 8940 ms/run
- token delta:       +2,481 (+8%)
- time delta:        -156.5s (-37%)

## How to reproduce

```bash
BENCH_BASE_URL="https://openrouter.ai/api/v1" \
  BENCH_API_KEY=… \
  BENCH_MODELS="meta-llama/llama-3.2-3b-instruct,google/gemma-3-4b-it,qwen/qwen-2.5-coder-32b-instruct" \
  python3 bench/run_offline.py
```

Models prefixed `local:` run on CPU via `transformers` (downloaded from the 
Hugging Face Hub); all others go through the OpenAI-compatible endpoint at 
`BENCH_BASE_URL`. Cap local generation length with `BENCH_LOCAL_MAX_TOKENS`.

Raw model outputs are saved under `.simplicio/bench_runs/<model>/case_NN/{sem,com}.txt` 
so you can audit what the LLM actually produced on each side. Charts are 
SVG under `bench/charts/`; raw aggregated data under `bench/results.json`.
