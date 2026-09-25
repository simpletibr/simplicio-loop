# Execution benchmark — simplicio-cli (real pytest, not regex)

Date: **2026-05-28**  
Models: `qwen2.5-coder:3b`  
Tasks: **6** self-contained Python functions.

Each task's generated `solution.py` is written next to a **hidden pytest suite** (never shown to the model, asserting true AND false states) and executed. **Pass = the code runs and every assertion holds.** Both sides emit the complete file — the only variable is whether the goal is wrapped in the simplicio contract.

## Headline

- **Without simplicio:** 4/6 (66%)
- **With simplicio:** 5/6 (83%)
- **Delta:** **+17 points**

## Per-model (pass = pytest green)

| Model | Without | With | Delta (pts) |
|---|---|---|---|
| `qwen2.5-coder:3b` | 4/6 (66%) | 5/6 (83%) | **+17** |

## Per-task x model (P = pass)

| Task | qwen2.5-coder:3b |
|---|---|
| can_delete (w/o,with) | P/P |
| email_editable (w/o,with) | P/P |
| slugify (w/o,with) | P/P |
| apply_discount (w/o,with) | P/P |
| merge_intervals (w/o,with) | ./. |
| validate_password (w/o,with) | ./P |

Raw counts above are real `pytest` exit codes. `results_exec.json` holds per-case pass/fail, tokens and latency.
