# 4-Quadrant Benchmark — agent × simplicio-cli matrix

> Isolates the contribution of two independent variables on code-generation
> quality: **prompt structure** (raw vs simplicio's 6-layer contract) and
> **execution model** (one-shot vs autonomous loop until DoD or max-iters).

---

## Why this exists

The original `bench/run_offline.py` answers one question:

> *Does wrapping a goal in simplicio's 6-layer contract make a single LLM
> call produce better code than the raw goal?*

Answer (from `bench/results.md`): yes, +39 to +58 points on tiny models.

But that's only half the story. Real-world agentic coding uses a **loop**
(ralph-loop, Claude Code `/ralph-loop`, Codex CLI `/goal`, Copilot
`--autopilot`). The loop can recover from a bad first call by reading
feedback and retrying.

So the open question becomes:

> *When you add a retry loop on top, does simplicio's prompt still
> matter? Or does the loop alone close the gap?*

The 4-quadrant matrix isolates both axes at once.

---

## The matrix

|                          | **no simplicio** (raw goal)         | **with simplicio** (6-layer contract) |
| ------------------------ | ----------------------------------- | ------------------------------------- |
| **no agent** (1 call)    | Q1 — baseline                       | Q2 — current bench                    |
| **with agent** (loop ≤N) | Q3 — loop only                      | Q4 — composition (full stack)         |

Four cells. Same model, same cases, same checks. Only the cell logic
changes.

### Q1 — no agent, no simplicio (baseline)

Send `goal` as a one-line prompt. Take whatever comes back. Score once.

```
prompt = goal
output = llm_call(prompt)
score(output, checks)
```

### Q2 — no agent, with simplicio (current bench)

Send `goal` wrapped in simplicio's 6-layer prompt
(`[GOAL] / [TARGET] / [CONTRACT] / [OUTPUT]`). Take whatever comes back.
Score once. This is what `bench/run_offline.py` already measures.

```
prompt = SIX_LAYER_TEMPLATE.format(goal, target, criteria, constraints)
output = llm_call(prompt)
score(output, checks)
```

### Q3 — with agent, no simplicio

Loop up to `MAX_ITERS` times. First call uses the raw goal. After each
call, score the output; if not all checks pass, append a structured
feedback message naming the missed checks and call again.

```
prompt = goal
for i in range(MAX_ITERS):
    output = llm_call(prompt)
    flags = score(output, checks)
    if all(flags):
        break
    prompt = goal + "\n\n" + format_feedback(checks, flags, output)
score(output, checks)  # final score = last iteration
```

### Q4 — with agent, with simplicio (composition)

Same loop as Q3, but the first call uses simplicio's 6-layer prompt. The
feedback message between iterations is identical (the loop logic
doesn't care which prompt seeded the cell).

```
prompt = SIX_LAYER_TEMPLATE.format(...)
for i in range(MAX_ITERS):
    output = llm_call(prompt)
    flags = score(output, checks)
    if all(flags):
        break
    prompt += "\n\n" + format_feedback(checks, flags, output)
score(output, checks)
```

This is the `.agents/simplicio-ralph.agent.md` composition pattern
(ralph-loop + simplicio-py task) measured end-to-end.

---

## Feedback shape (Q3 / Q4)

Between iterations, the harness appends a **structured feedback block**
to the same conversation. Same shape across both agent quadrants:

```
[FEEDBACK — iteration N]
Previous output failed these checks (regex names):
- check_1
- check_3
- check_5

Required corrections:
- Output a DIFF block (unified diff format).
- Mention the target file by name.
- Reference the criteria keyword: <kw>.

Return a corrected version following the OUTPUT shape rules.
```

The feedback is **deterministic and heuristic** — derived directly from
which regex checks failed. No LLM judges the LLM. Same rules in both
quadrants so the only variable is the seed prompt.

---

## Metrics captured (per cell, per case, per model)

| Metric              | What it measures                                                  |
| ------------------- | ----------------------------------------------------------------- |
| `pass`              | Did the final output (after loop, if any) satisfy all checks?     |
| `iterations`        | How many loop turns until first all-green (or `MAX_ITERS` if no). |
| `tokens_prompt`     | Sum across all iterations.                                        |
| `tokens_completion` | Sum across all iterations.                                        |
| `tokens_total`      | Sum.                                                              |
| `wall_clock_ms`     | Sum across all iterations.                                        |
| `has_diff_block`    | Final output contains a unified diff or fenced ` ```diff ` block. |
| `has_test_block`    | Final output contains a test stub.                                |
| `target_mentioned`  | Final output names the target file.                               |

Per quadrant aggregates: pass-rate (%), avg iterations, avg tokens per
cell, avg wall-clock per cell, structural-quality rates.

---

## What this matrix reveals

The 2×2 lets you decompose the *contribution* of each axis:

- **Prompt effect, no loop**: Q2 − Q1.
- **Prompt effect, with loop**: Q4 − Q3.
- **Loop effect, no simplicio**: Q3 − Q1.
- **Loop effect, with simplicio**: Q4 − Q2.
- **Composition gain over best single axis**: Q4 − max(Q2, Q3).

Hypotheses to falsify:

1. *"The loop alone closes the gap — simplicio is unnecessary once you
   loop."* Falsified if Q4 > Q3 by a meaningful margin.
2. *"Simplicio alone is enough — looping is overkill."* Falsified if
   Q4 > Q2 by a meaningful margin (especially on harder cases).
3. *"They're independent — gains stack linearly."* Falsified if Q4 ≈
   Q2 + (Q3 − Q1), supported if Q4 > Q2 + (Q3 − Q1) (synergy) or Q4 <
   Q2 + (Q3 − Q1) (diminishing returns).

---

## Cost model

Token and wall-clock cost rises with the number of iterations the agent
quadrants spend. With `MAX_ITERS = 3`:

- Q1 / Q2: exactly 1 call.
- Q3 / Q4: between 1 and 3 calls per case (avg depends on first-call
  success rate).

Report includes:

- Per-quadrant total tokens & wall-clock.
- Per-quadrant avg tokens-per-case (lets you compute cost-to-green).
- Token cost per *passing case* — divides total tokens by the number of
  cases that reached green. This is the metric that matters when
  comparing "spend more tokens looping" vs "spend more tokens on the
  6-layer wrap upfront".

---

## Outputs

| File                                     | What it is                                                     |
| ---------------------------------------- | -------------------------------------------------------------- |
| `bench/results_4quadrant.md`             | Markdown report with tables, deltas, hypothesis verdicts.       |
| `bench/results_4quadrant.pdf`            | PDF version (fpdf2).                                            |
| `bench/results_4quadrant.json`           | Raw aggregated data per model × quadrant × case.                |
| `bench/charts/4q_overall.svg`            | Grouped bar chart: Q1–Q4 pass-rate side by side.                |
| `bench/charts/4q_per_case.svg`           | Per-case 4-way pass-rate.                                       |
| `bench/charts/4q_cost.svg`               | Tokens per passing case, per quadrant.                          |
| `.simplicio/bench_4q/<model>/case_NN/`   | Raw output per quadrant per iteration (audit trail).            |

---

## How to reproduce

```bash
# 1. install bench extras (adds fpdf2 only — used for PDF report)
pip install -e ".[bench]"

# 2. set provider key
export OPENROUTER_API_KEY=sk-or-...

# 3. run (defaults: 1 cheap model, 5 cases, max_iters=3)
python3 bench/run_4quadrant.py

# 4. larger run (more models, all cases)
BENCH_MODELS="google/gemma-3-4b-it,meta-llama/llama-3.2-3b-instruct" \
  BENCH_MAX_ITERS=5 \
  BENCH_CASES_PATH=bench/cases_offline.json \
  python3 bench/run_4quadrant.py
```

Outputs land in `bench/results_4quadrant.{md,pdf,json}` + charts under
`bench/charts/`. Raw model outputs (one file per iteration per quadrant)
land under `.simplicio/bench_4q/<model>/case_NN/qK_iterN.txt` so the run
is auditable.

---

## Limitations (what this bench does NOT measure)

- **No real toolchain.** Output is scored by heuristics (regex against
  the model text), not by running `lint`, `pytest`, or `playwright` on
  the diff. Reason: keeps the bench offline-reproducible and stack-
  agnostic. A "real-tools" follow-up bench is open work — see
  `.specs/sprints/BACKLOG.md`.
- **Synthetic feedback.** The agent feedback is a deterministic
  derivation from which regex checks failed, not real lint/test
  output. This *underestimates* the gap between Q3 and Q4 in cases
  where simplicio's structural contract would have made the LLM emit
  the right shape on the first try (the feedback loop also pushes the
  raw side toward structure, narrowing the visible gap).
- **`MAX_ITERS` is a hard cap.** Cases that would converge in 4 calls
  but `MAX_ITERS=3` count as fails. The report shows the iteration
  histogram so this is visible.
- **Cost cap is fairness-only.** Real ralph-loop deployments can spend
  10+ iterations; this bench caps at 3–5 to keep the run cheap and
  comparable. The composition's real ceiling is higher than what
  appears here.
- **Single-model per run.** Cross-model comparison requires running
  the harness once per model (the existing pattern in
  `bench/run_offline.py`).
