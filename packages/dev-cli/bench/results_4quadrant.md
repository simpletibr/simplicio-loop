# Benchmark 4-quadrant — agent x simplicio matrix (focused run)

Date: **2026-05-26**  
Models: `google/gemma-3-4b-it`  
Cases: **5**, max_iters: **3**  
Base: `https://openrouter.ai/api/v1`

Methodology: [docs/benchmark-4quadrant.md](../docs/benchmark-4quadrant.md).
Wider replication across 3 models × 10 cases:
[results_4quadrant_wide.md](results_4quadrant_wide.md).

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
| **Q1** (no agent, no simplicio) | 0/5 (0%) | 1.00 | 4,683 | 236,148 ms |
| **Q2** (no agent, with simplicio) | 3/5 (60%) | 1.00 | 800 | 20,796 ms |
| **Q3** (with agent, no simplicio) | 2/5 (40%) | 3.00 | 3,135 | 109,283 ms |
| **Q4** (with agent, with simplicio) | 4/5 (80%) | 1.80 | 1,018 | 20,498 ms |

![4q overall](charts/4q_overall.svg)

## Contribution decomposition (points)

| Delta | Formula | Value |
|---|---|---|
| Prompt effect, no loop | Q2 - Q1 | **+60 pts** |
| Loop effect, no simplicio | Q3 - Q1 | **+40 pts** |
| Prompt effect inside loop | Q4 - Q3 | **+40 pts** |
| Loop effect with simplicio | Q4 - Q2 | **+20 pts** |
| Composition gain over best single axis | Q4 - max(Q2, Q3) | **+20 pts** |
| Synergy vs linear stacking | Q4 - (Q1 + (Q2-Q1) + (Q3-Q1)) | **-20 pts** |

## Hypothesis verdicts

Threshold for rejection: |delta| >= 5 points.

1. *Loop alone closes the gap (simplicio unnecessary once you loop).* Q4 - Q3 = **+40 pts**. **REJECTED**.
2. *Simplicio alone is enough (loop is overkill).* Q4 - Q2 = **+20 pts**. **REJECTED**.
3. *Gains stack linearly (no synergy).* Q4 - linear = **-20 pts**. **REJECTED**.

## Cost — token & wall-clock budget

| Quadrant | Total tokens | Total wall-clock | Tokens / passing case | ms / passing case |
|---|---|---|---|---|
| Q1 | 4,683 | 236.1s | 4,683 | 236,148 |
| Q2 | 2,400 | 62.4s | 800 | 20,796 |
| Q3 | 6,270 | 218.6s | 3,135 | 109,283 |
| Q4 | 4,072 | 82.0s | 1,018 | 20,498 |

## Structural quality (rate across all runs)

| Quadrant | DIFF block | TEST block | target file mentioned |
|---|---|---|---|
| Q1 | 0% | 60% | 0% |
| Q2 | 80% | 80% | 80% |
| Q3 | 20% | 80% | 60% |
| Q4 | 80% | 80% | 80% |

## Per-model x quadrant

| Model | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| `google/gemma-3-4b-it` | 0/5 (0%) | 3/5 (60%) | 2/5 (40%) | 4/5 (80%) |

## Per-case x quadrant (avg across models)

| # | Stack | Goal | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|---|
| 1 | `angular` | Hide the Delete button when the current user is no | 0/1 | 1/1 | 0/1 | 1/1 |
| 2 | `angular` | Disable the email field unless the profile role is | 0/1 | 1/1 | 1/1 | 1/1 |
| 3 | `angular` | Only show the audit log link for users with role ' | 0/1 | 1/1 | 1/1 | 0/1 |
| 4 | `angular` | Show 'Approve' button only when the order status i | 0/1 | 0/1 | 0/1 | 1/1 |
| 5 | `react` | Render the export menu item only for users in the  | 0/1 | 0/1 | 0/1 | 1/1 |

![4q per case](charts/4q_per_case.svg)

![4q cost](charts/4q_cost.svg)

## How to reproduce

```bash
pip install -e ".[bench]"
OPENROUTER_API_KEY=...
BENCH_MODELS="google/gemma-3-4b-it" \
  BENCH_MAX_ITERS=3 \
  python3 bench/run_4quadrant.py
```

Raw model outputs (one file per iteration per quadrant) live under `.simplicio/bench_4q/<model>/case_NN/q*_iter*.txt`.
