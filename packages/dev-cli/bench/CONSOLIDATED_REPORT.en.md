# Consolidated Benchmark Report (English summary) — simplicio-cli

> English companion to `bench/CONSOLIDATED_REPORT.md` (the full report is in pt-BR).
> Contains only: executive summary, master model table, and the preliminary
> default-model recommendation.
>
> **Honesty rule (strictly applied):** only numbers that appear verbatim in the source
> files are reported. Missing values are marked `n/d` (not available). Nothing is
> estimated or extrapolated; design-only estimates are flagged. Every figure cites its
> source file. Consolidation date: 2026-05-31.

---

## Executive summary

- **Measured headline uplift = +58pt (regex).** On the regex 156-check suite, Qwen2.5-Coder-7B goes **38% → 96%** with the 6-layer contract (`README.md` line 117, `bench/results_comparison.md`).
- **Causal decomposition (4-quadrant, aggregate, n=40):** the 6-layer prompt alone (Q2−Q1) is worth **+55pt**; the loop alone (Q3−Q1) **+47pt**; together (Q4) reach **70%** pass-rate. All three hypotheses ("loop alone is enough", "simplicio alone is enough", "gains add linearly") were **REJECTED**. Source: `bench/results_4quadrant_full.md`.
- **Highest pass-rate with real execution (PHPUnit) = 100%**: `Qwen3-Coder-Next` (cli+ag and modal-vote fan-out 12/12) and `deepseek/deepseek-v4-flash` (cli+ag and cli+sp+ag, 12/12). Sources: `bench/results_full_qwen3.md`, `bench/results_v14_interim.md`, `bench/results_exec_sindico.md`, `bench/results_fanout.md`.
- **`cli+ag` (verify-loop) is the only side that reliably beats `cli` alone on functional.** `cli+sp` (simplicio-prompt composition) ties or trails `cli` in single-call. Sources: `bench/results_full_qwen3.md`, `bench/results_4side_qwen3.md`.
- **regex inflates vs functional**: in fan-out N=200 at temp=0.7, `Qwen3-Coder-30B-A3B-Instruct` scores regex 100% and PHPUnit 0% on **6 of 12 cases**; aggregate of both models is regex 94% vs functional 66% (gap **+28pt**). Numeric proof that "regex doesn't mean it runs". Sources: `bench/results_fanout.md`, `bench/results_4side_qwen3.md`.
- **simplicio-prompt (sp) alone does NOT beat the cli contract** in one-shot generation — in one run it was net-negative (**47% baseline → 44% with sp, −3pt**; cli ref 75%). Source: `bench/results_sp_compare.md`.
- **Tiny family: the contract multiplies a capable model, it doesn't create capability.** On the real sindico suite, Gemma-3-4B goes 0%→75% (+75pt) but Llama-3.2-1B and Gemma-3n-e4B stay 0%/0% (can't emit parseable PHP). Source: `README.md` lines 52-61.
- **Schema v1 (structured output) has a size frontier:** Qwen2.5-Coder-3B does **4/4 (100%) parse_ok**, DeepSeek-V4-Flash **3/4 (75%)**, but Gemma-4B and Qwen-1.5B do **0%**. Coder specialization helps but doesn't compensate below ~3B. Sources: `bench/results_sp_schema_validation.md`, `bench/results_v14_qwen15b_gguf_partial.md`.
- **Deterministic levers (fixers/recipes/codegen/cache) cut LLM calls** with no pass-rate loss: modeled local path **19 → 6 calls (−68.42%)**; release proof **210 → 0 (−100%)**. Sources: `bench/results_llm_reduction_summary.md`, `bench/results_static_fixers.md`, `bench/results_scratch_codegen.md`.
- **Scratch mode passes the live gate:** **75/75 e2e green** across 5 stacks (go-gin, php-laravel, py-fastapi, rust-axum, ts-nextjs), zero cost, deterministic codegen (executor 100% vs LLM baseline 55.56%). Only "not release-ready" for lack of SkillOpt human approval. Sources: `bench/results_scratch_live_gate.md`, `bench/results_scratch_codegen.md`.
- **Rust hot-path (`simplicio-core`) validates the prompt:** 5/5 parity, **8.47x** faster than Python, and the Rust-assembled prompt drives `qwen2.5-coder:3b` to **5/6 (83%)** on real exec. Source: `bench/results_rust_qwen.md`.
- **1.5B GGUF quantization curve (issue #46) is partial:** Q5_K_M = **66% (4/6)** and Q8_0 = **83% (5/6)** via ollama (run_exec, single-shot); Q5_K_M = partial **2/12** via llama-cpp-python (sindico). Q6_K and Q4_K_M **not run**. Sources: `bench/RESULTS_LOCAL_GGUF.md`, `bench/results_v14_qwen15b_gguf_partial.md`.

---

## Master model table

Best measured pass-rate per model across any versioned bench, with suite/side noted.
`(regex)` = cheap structural proxy (proven to inflate); `(exec)` = real execution
(PHPUnit/pytest). Every cell cites its source.

| Model | size/quant | backend | best pass-rate seen | suite/side | source |
|---|---|---|---|---|---|
| Qwen2.5-Coder-1.5B | 1.5B | HF local transformers | 92% (with) | regex 156-check | results_comparison |
| Qwen2.5-Coder-1.5B (GGUF Q5_K_M) | 1.5B / Q5_K_M | ollama (M1) | 66% (4/6) | exec Python single-shot | RESULTS_LOCAL_GGUF |
| Qwen2.5-Coder-1.5B (GGUF Q5_K_M) | 1.5B / Q5_K_M | llama-cpp-python | partial 2/12 (cli+ag passed 1 of 2 run) | exec sindico (partial) | results_v14_qwen15b_gguf_partial |
| Qwen2.5-Coder-1.5B (GGUF Q8_0) | 1.5B / Q8_0 | ollama (M1) | **83% (5/6, without)** | exec Python single-shot | RESULTS_LOCAL_GGUF |
| Qwen2.5-Coder-3B | 3B | HF Inference / local | 94% (with, regex) | regex 156-check | results_comparison |
| qwen2.5-coder:3b | 3B | Ollama | 83% (5/6, with) | exec Python single-shot | results_rust_qwen / results_exec |
| Qwen2.5-Coder-3B | 3B | transformers CPU | 100% parse_ok (schema v1, not a pass-rate) | schema smoke | results_sp_schema_validation |
| Qwen2.5-Coder-7B | 7B | HF Inference | **96% (with)** | regex 156-check | results_comparison / README |
| Qwen2.5-Coder-7B | 7B | Ollama | 92% (with) | regex 156-check | README (local offline) |
| Qwen2.5-Coder-32B | 32B | OpenRouter | 80% (cli+sp+ag, regex); 16% (all sides, exec) | regex / exec sindico | results_v13_5side |
| Qwen2.5-7B (general) | 7B | OpenRouter | 100% (with regex; Q4); 25% (exec sindico, README run) | regex / 4-quadrant / exec | results_comparison / results_4quadrant_full / README |
| Qwen3-Coder-30B-A3B-Instruct | 30B MoE / 3B active | HF router | 91% (cli/cli+sp/cli+ag, exec); 98% (cli+sp, regex) | exec + regex | results_full_qwen3 / results_4side_qwen3 |
| Qwen3-Coder-Next | 80B MoE / 3B active | HF router | **100% (cli, regex); 91% (cli+ag, exec); 12/12 modal fan-out** | exec + regex + fan-out | results_full_qwen3 / results_fanout |
| Llama-3.2-1B | 1B | OpenRouter | 0% (both sides, exec); 40%→36% (regex) | exec sindico / regex | README / results_comparison |
| Llama-3.2-3B | 3B | OpenRouter | 88% (cli+ag, regex); 8% (all sides, exec) | regex / exec sindico | results_v13_5side |
| Llama-3.1-8B | 8B | OpenRouter | 100% (with, exec sindico README run); 88% (with, regex) | exec / regex | README / results_comparison |
| Gemma-3-4b-it | 4B | OpenRouter | 96% (with, regex); 75% (with, exec sindico README run) | regex / exec | README / results_v13_5side |
| Gemma-3-4b-it | 4B | — | 0/16 parse_ok (schema v1) | schema smoke | results_sp_schema_validation |
| Gemma-3-12B | 12B | OpenRouter | 92% (with, regex); 75% (with, exec) | regex / exec | results_comparison / README |
| Gemma-3n-e4B | 4B MoE | OpenRouter | 90% (with, regex); 0% (exec) | regex / exec | results_comparison / README |
| Phi-4 mini | mini | OpenRouter | 73% (with, regex) | regex | results_comparison |
| anthropic/claude-3.5-haiku | — | OpenRouter | 40% (Q4) | 4-quadrant | results_4quadrant_full |
| Claude Opus 4.7 | — | OpenRouter | 98% (with, regex — "old", n/a on re-run) | regex | results_comparison / README |
| GPT-5.5 | — | OpenRouter | 100%→98% (with, regex) | regex | results_comparison / README |
| Kimi K2.6 | — | OpenRouter | 100% (with, regex) | regex | results_comparison / README |
| Gemini 3.5 Flash | — | OpenRouter | 100% (with regex; with exec README run); 66% (exec sp-compare) | regex / exec | results_comparison / README / results_sp_compare |
| Qwen 3.7 Max | — | OpenRouter | 100% (with, regex — "old", n/a on re-run) | regex | README |
| deepseek/deepseek-v4-flash | ~37B (proprietary) | OpenRouter | **100% (cli+ag & cli+sp+ag, exec); 91% (cli, exec)** | exec sindico (12 cases) | results_exec_sindico / results_v14_interim |
| deepseek/deepseek-v4-flash | ~37B | OpenRouter | 3/4 parse_ok (schema v1) | schema smoke | results_sp_schema_validation |
| DeepSeek V4 Pro | — | OpenRouter | 96% (with, regex — "old", n/a on re-run) | regex | README |

> **Notes:**
> - **DeepSeek IS present** (V4-Flash and V4-Pro).
> - There are **two "Qwen 7B"**: **Qwen2.5-Coder-7B** (coder, best 96% regex) and **Qwen2.5-7B** (general, best 100% regex / 100% Q4 but only 25% exec sindico in the README run). Do not conflate.
> - The same model swings widely between regex (proxy) and exec (real): Llama-3.2-3B 88% regex vs 8% exec; Qwen2.5-Coder-32B 80% regex vs 16% exec. Exec is the honest number.
> - **Only `Qwen3-Coder-Next` and `deepseek-v4-flash` reach the functional ceiling (100% / 12-of-12)** via cli+ag or modal-vote.

---

## Preliminary default-model recommendation

Based strictly on measured pass-rates, prioritizing **real exec (PHPUnit/pytest)** over
**regex (proxy)** because the data itself shows regex inflating.

- **Overall default (best measured real-execution quality):** a tie at the ceiling between
  **`Qwen3-Coder-Next`** (HF router) and **`deepseek/deepseek-v4-flash`** (OpenRouter) — both
  **12/12 (100%) on exec sindico** via `cli+ag` (DeepSeek) or modal-vote fan-out (Coder-Next 12/12; cli+ag single-call 91%). Sources: `results_exec_sindico.md`, `results_full_qwen3.md`, `results_fanout.md`, `results_v14_interim.md`.
  - **`Qwen3-Coder-Next`** is the most temperature-robust (modal-vote 12/12 at temp=0.7 vs 5/12 for the 30B-A3B) and is open (Apache-2.0) via HF router; **`deepseek-v4-flash`** hits 100% already at `cli+ag` single-call (no 200 subagents needed), cheaper in calls. Pick Coder-Next for robustness/openness, DeepSeek-V4-Flash for cost-per-call.
  - Caveat: `Qwen3-Coder-30B-A3B-Instruct` looks great on regex (98%) but **inflates** — only 5/12 functional modal-vote. Don't decide on its regex number.

- **Recommended LOCAL/offline default: `Qwen2.5-Coder-7B`.** Best local coder with a high, consistent number: **96% regex via HF Inference** and **92% regex via Ollama** (`README.md`, `results_comparison.md`); it's the default the README/CHANGELOG document for serious local use. No versioned exec sindico for the 7B coder, so 96% is **regex** — treat as optimistic ceiling.
  - Lighter local alternative: **`Qwen2.5-Coder-3B`** (94% regex; 83%/5-of-6 exec Python single-shot via Ollama in `results_rust_qwen.md`; 100% schema-v1 parse_ok).
  - Minimal offline default (CHANGELOG 0.5.0): the product already falls back to **`Qwen2.5-Coder-1.5B-Instruct-Q5_K_M` GGUF** when nothing is configured. Honestly, that 1.5B GGUF measures only **66% (4/6) single-shot** (`RESULTS_LOCAL_GGUF.md`) and **0% schema parse_ok**; fine for trivial offline tasks, fragile otherwise. The README's ~88% for the 1.5B is the full-precision transformers + verify-loop run, NOT the GGUF single-shot.

**Caveats for complex full-stack ("sindico") tasks:**
- The headline 96% (7B) is regex. On **real exec sindico, mid-size models collapse**: Qwen2.5-Coder-32B = **16%**, Llama-3.2-3B = **8%**, and hard cases fail even with 3 attempts and 200 subagents (model-capability ceiling). Sources: `results_v13_5side.md`, `results_full_qwen3.md`.
- For sindico/production, **only `Qwen3-Coder-Next` and `deepseek-v4-flash` closed 12/12.** Smaller models need `cli+ag` (the lever that recovers the most cases) and/or modal-vote fan-out.
- **Always use `cli+ag`** (verify-loop): on functional it's the only side that reliably beats `cli`. `cli+sp` (composition) does NOT help single-call and can regress (gemma exec 66%→50% with sp in `results_v13_5side.md`).
- For mechanical tasks (CRUD/route/schema in scratch mode), prefer the **deterministic codegen** (executor 100% vs LLM 55.56%, ~95% faster, zero calls) over LLM generation. Source: `results_scratch_codegen.md`.
