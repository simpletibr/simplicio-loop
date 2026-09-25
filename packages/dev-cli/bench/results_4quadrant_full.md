# Benchmark 4-quadrant - agent x simplicio matrix

Date: **2026-05-26**  
Models: `google/gemma-3-4b-it`, `meta-llama/llama-3.2-3b-instruct`, `qwen/qwen-2.5-7b-instruct`, `anthropic/claude-3.5-haiku`  
Cases: **10**, max_iters: **5**  
Base: `https://openrouter.ai/api/v1`

Methodology: [docs/benchmark-4quadrant.md](../docs/benchmark-4quadrant.md).

## Quadrants

| Cell | Prompt | Execution |
|---|---|---|
| **Q1** | raw goal | 1-shot (baseline) |
| **Q2** | simplicio 6-layer | 1-shot (current bench) |
| **Q3** | raw goal | loop with feedback (`MAX_ITERS`) |
| **Q4** | simplicio 6-layer | loop with feedback (composition) |

## Headline (aggregate over all models x cases)

| Quadrant | Pass rate | Avg iters | Tokens / pass | Wall-clock / pass |
|---|---|---|---|---|
| **Q1** (no agent, no simplicio) | 0/40 (0%) | 1.00 | 29,522 | 1,016,220 ms |
| **Q2** (no agent, with simplicio) | 22/40 (55%) | 1.00 | 991 | 23,551 ms |
| **Q3** (with agent, no simplicio) | 19/40 (47%) | 3.92 | 4,978 | 107,562 ms |
| **Q4** (with agent, with simplicio) | 28/40 (70%) | 2.60 | 1,563 | 30,584 ms |

![4q overall](charts/4q_overall.svg)

## Contribution decomposition (points)

| Delta | Formula | Value |
|---|---|---|
| Prompt effect, no loop | Q2 - Q1 | **+55 pts** |
| Loop effect, no simplicio | Q3 - Q1 | **+47 pts** |
| Prompt effect inside loop | Q4 - Q3 | **+23 pts** |
| Loop effect with simplicio | Q4 - Q2 | **+15 pts** |
| Composition gain over best single axis | Q4 - max(Q2, Q3) | **+15 pts** |
| Synergy vs linear stacking | Q4 - (Q1 + (Q2-Q1) + (Q3-Q1)) | **-32 pts** |

## Hypothesis verdicts

Threshold for rejection: |delta| >= 5 points.

1. *Loop alone closes the gap (simplicio unnecessary once you loop).* Q4 - Q3 = **+23 pts**. **REJECTED**.
2. *Simplicio alone is enough (loop is overkill).* Q4 - Q2 = **+15 pts**. **REJECTED**.
3. *Gains stack linearly (no synergy).* Q4 - linear = **-32 pts**. **REJECTED**.

## Cost - token & wall-clock budget

| Quadrant | Total tokens | Total wall-clock | Tokens / passing case | ms / passing case |
|---|---|---|---|---|
| Q1 | 29,522 | 1016.2s | 29,522 | 1,016,220 |
| Q2 | 21,817 | 518.1s | 991 | 23,551 |
| Q3 | 94,599 | 2043.7s | 4,978 | 107,562 |
| Q4 | 43,791 | 856.4s | 1,563 | 30,584 |

## Structural quality (rate across all runs)

| Quadrant | DIFF block | TEST block | target file mentioned |
|---|---|---|---|
| Q1 | 0% | 65% | 2% |
| Q2 | 75% | 65% | 77% |
| Q3 | 47% | 70% | 57% |
| Q4 | 75% | 72% | 77% |

## Per-model x quadrant

| Model | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| `google/gemma-3-4b-it` | 0/10 (0%) | 7/10 (70%) | 4/10 (40%) | 8/10 (80%) |
| `meta-llama/llama-3.2-3b-instruct` | 0/10 (0%) | 5/10 (50%) | 4/10 (40%) | 6/10 (60%) |
| `qwen/qwen-2.5-7b-instruct` | 0/10 (0%) | 6/10 (60%) | 8/10 (80%) | 10/10 (100%) |
| `anthropic/claude-3.5-haiku` | 0/10 (0%) | 4/10 (40%) | 3/10 (30%) | 4/10 (40%) |

## Per-case x quadrant (avg across models)

| # | Stack | Goal | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|---|
| 1 | `angular` | Hide the Delete button when the current user is no | 0/4 | 3/4 | 2/4 | 3/4 |
| 2 | `angular` | Disable the email field unless the profile role is | 0/4 | 3/4 | 2/4 | 4/4 |
| 3 | `angular` | Only show the audit log link for users with role ' | 0/4 | 3/4 | 2/4 | 3/4 |
| 4 | `angular` | Show 'Approve' button only when the order status i | 0/4 | 4/4 | 3/4 | 4/4 |
| 5 | `react` | Render the export menu item only for users in the  | 0/4 | 1/4 | 3/4 | 2/4 |
| 6 | `react` | Disable the 'Save Draft' button while the form is  | 0/4 | 3/4 | 1/4 | 3/4 |
| 7 | `react` | Show a 'No results' empty state when the search re | 0/4 | 2/4 | 2/4 | 3/4 |
| 8 | `dotnet` | Require the 'CanApprove' policy on the Approve end | 0/4 | 1/4 | 1/4 | 3/4 |
| 9 | `dotnet` | Restrict the GET /reports endpoint so only users i | 0/4 | 2/4 | 2/4 | 2/4 |
| 10 | `angular` | Show a warning banner if the user has unsaved chan | 0/4 | 0/4 | 1/4 | 1/4 |

![4q per case](charts/4q_per_case.svg)

![4q cost](charts/4q_cost.svg)

## How to reproduce

```bash
pip install -e ".[bench]"
OPENROUTER_API_KEY=...
BENCH_MODELS="google/gemma-3-4b-it,meta-llama/llama-3.2-3b-instruct,qwen/qwen-2.5-7b-instruct,anthropic/claude-3.5-haiku" \
  BENCH_MAX_ITERS=5 \
  python3 bench/run_4quadrant.py
```

Raw model outputs (one file per iteration per quadrant) live under `.simplicio/bench_4q/<model>/case_NN/q*_iter*.txt`.
