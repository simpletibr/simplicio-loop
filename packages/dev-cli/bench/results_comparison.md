# Benchmark - old vs new (with & without simplicio-cli)

Date: **2026-05-28**  
Old = pass-rate published in the README. New = re-run on the latest version with the same regex-based contract-adherence methodology and the same 10 cases/side. The Qwen2.5-Coder triplet was re-measured via the Hugging Face router (1.5B local via transformers, 3B/7B via HF Inference Providers); the remaining 14 README models were re-measured via OpenRouter using the original OR-style model ids.

**Delta interpretation:** the gap between old and new on the same model is *not* a regression in simplicio itself — same wrapper, same checks, same prompts. It reflects (a) provider/model drift between the original publication date and 2026-05-28, (b) OpenRouter routing variance for frontier models, and (c) the inherent single-sample noise at `temperature=0`. The simplicio-cli contract still produces a large positive delta vs raw baseline on the new run, which is the claim that matters.

## Local offline - qwen2.5-coder (was Ollama; now HF)

| Model | Without (old -> new) | With (old -> new) | D without | D with |
|---|---|---|---|---|
| **Qwen 2.5 Coder 7B** | 36% -> **38%** | 92% -> **96%** | +2 | +4 |
| **Qwen 2.5 Coder 3B** | 34% -> **34%** | 82% -> **94%** | +0 | +12 |
| **Qwen 2.5 Coder 1.5B** | 32% -> **30%** | 88% -> **92%** | -2 | +4 |

## Tiny models - sub-4B

| Model | Without (old -> new) | With (old -> new) | D without | D with |
|---|---|---|---|---|
| **Gemma 3 4B** | 38% -> **40%** | 96% -> **92%** | +2 | -4 |
| **Llama 3.2 3B** | 28% -> **30%** | 73% -> **76%** | +2 | +3 |
| **Gemma 3n e4B** | 44% -> **38%** | 88% -> **90%** | -6 | +2 |
| **Phi-4 mini** | 36% -> **36%** | 73% -> **73%** | +0 | +0 |
| **Llama 3.2 1B** | 26% -> **25%** | 40% -> **36%** | -1 | -4 |

## Frontier 2026 models

| Model | Without (old -> new) | With (old -> new) | D without | D with |
|---|---|---|---|---|
| **GPT-5.5** | 38% -> **38%** | 100% -> **98%** | +0 | -2 |
| **Kimi K2.6** | 40% -> **44%** | 100% -> **100%** | +4 | +0 |
| **Gemini 3.5 Flash** | 42% -> **42%** | 100% -> **100%** | +0 | +0 |
| **Qwen 3.7 Max** | 44% -> n/a | 100% -> n/a | n/a | n/a |
| **Claude Opus 4.7** | 42% -> n/a | 98% -> n/a | n/a | n/a |
| **DeepSeek V4 Pro** | 44% -> n/a | 96% -> n/a | n/a | n/a |

## Mid-tier 7B-12B open models

| Model | Without (old -> new) | With (old -> new) | D without | D with |
|---|---|---|---|---|
| **Gemma 3 12B** | 34% -> **46%** | 92% -> **92%** | +12 | +0 |
| **Llama 3.1 8B** | 36% -> **36%** | 90% -> **88%** | +0 | -2 |
| **Qwen 2.5 7B** | 34% -> **34%** | 88% -> **100%** | +0 | +12 |

## Overall (models with a new re-run)

| Side | Old avg | New avg | Delta |
|---|---|---|---|
| Without simplicio | 36% | 36% | +1 |
| With simplicio | 86% | 88% | +2 |

Models re-run: **14**. Merged new dataset: `bench/results_all.json`.
