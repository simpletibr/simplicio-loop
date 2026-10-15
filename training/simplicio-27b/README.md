---
language:
- en
license: apache-2.0
base_model: Qwen/Qwen3.8-27B
tags:
- qwen
- unsloth
- lora
- code-generation
- simplicio-loop
- software-engineering
- surgical-diff
- agentic-coding
pipeline_tag: text-generation
---

<div align="center">

<p align="center">
  <a href="https://simpleti.com.br" target="_blank">
    <img src="https://raw.githubusercontent.com/simpletibr/simplicio-27b/main/assets/simplicio-logo.png" width="130" alt="SimpleTI Simplicio Logo">
  </a>
</p>

# ⚡ Simplicio 27B: Autonomous Software Engineering Model

<p align="center">
  <b>Built on Qwen3.8-27B & Fine-Tuned with the 50 Points of Simplicio-Loop</b><br>
  <i>Official simpleti.com.br Agentic Foundation Architecture</i>
</p>

<p align="center">
  <a href="https://github.com/simpletibr/simplicio-loop"><img src="https://img.shields.io/badge/GitHub-simplicio--loop-blue?logo=github" alt="GitHub"></a>
  <a href="https://huggingface.co/wesleysimplicio/Simplicio-27B"><img src="https://img.shields.io/badge/HuggingFace-Simplicio--27B-yellow?logo=huggingface" alt="Hugging Face"></a>
  <a href="https://simpleti.com.br"><img src="https://img.shields.io/badge/Official%20Site-simpleti.com.br-0ea5e9" alt="SimpleTI Official Site"></a>
  <a href="https://huggingface.co/Qwen/Qwen3.8-27B"><img src="https://img.shields.io/badge/Base%20Model-Qwen3.8--27B-purple" alt="Base Model"></a>
  <a href="https://colab.research.google.com/gist/wesleysimplicio/1f7de17399f64bb6f71895ab7401bd88"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-green.svg" alt="License"></a>
</p>

</div>

---

## Simplicio 27B Highlights

**Simplicio 27B** is a specialized, open-weights software engineering foundation model derived from **Qwen3.8-27B** and fine-tuned via **Unsloth (QLoRA 4-bit)** with the **50 Points of [Simplicio-Loop](https://github.com/simpletibr/simplicio-loop)** developed by Wesley Simplicio ([@simpletibr](https://github.com/simpletibr)).

Unlike standard conversational models that employ unbounded, verbose Chain-of-Thought (CoT), Simplicio 27B operates within an **enforced 5-phase recursive loop**:
- **Loop-Closed Software Engineering**: Replaces free-form reasoning with deterministic engineering phases: `<orient>`, `<plan>`, `<patch>`, `<validate>`, and `<deliver>`.
- **Surgical Diff Modification**: Enforces atomic search-and-replace chunk editing (`<<<< SEARCH / ==== / >>>> REPLACE`) instead of wasteful full-file regenerations, preserving original indentation, type signatures, and comments.
- **Strict Signature Introspection**: Inspects symbol graphs and type interfaces prior to modifying code; aims to reduce ghost function hallucinations (UNVERIFIED).
- **Failure-Guided Auto-Correction**: Analyzes compiler errors, test failures, and tracebacks directly in the validation phase; intended to reach green tests with fewer trial-and-error loops (UNVERIFIED).
- **Reasoning Token Discipline**: The training data prunes conversational verbosity. How many tokens this saves, and whether task resolution improves, has **not been measured** (UNVERIFIED).
- **Deterministic Delivery Verification**: The formal `simplicio_deliver(status="VERIFIED_GREEN")` contract requires a green test run before claiming completion. The model is trained to emit it; that is not a guarantee that it always does.

---

## Model Overview

- **Model Type**: Causal Language Model fine-tuned for Agentic Software Engineering
- **Base Architecture**: Qwen3.8-27B (Hybrid Gated DeltaNet + Gated Attention)
  - **Parameters**: ~27 Billion
  - **Hidden Dimension**: 5,120
  - **Layers**: 64
  - **Layout**: 16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))
  - **Linear Attention Heads (DeltaNet)**: 48 (V), 16 (QK)
  - **Attention Heads (Gated Attention)**: 24 (Q), 4 (KV)
- **Fine-Tuning Framework**: Unsloth QLoRA (4-bit Normal Float)
  - **Target Modules**: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`
  - **Rank (r)**: 32 | **Alpha**: 32 | **Dropout**: 0
  - **Gradient Checkpointing**: Unsloth Native
- **Context Length**: 4,096 tokens (native training window; extensible up to 262,144 tokens)
- **Training Trajectories**: Synthetic multi-language trajectories adhering to the 50 Points of Simplicio-Loop
- **Train/val split**: `python3 generate_dataset.py` de-duplicates candidates by normalised instruction text (lowercase, collapsed whitespace, stripped) and partitions the unique instructions into disjoint `data/*_train.jsonl` and `data/*_val.jsonl` with a seeded, hash-ordered split. [`data/SPLIT.json`](./data/SPLIT.json) records the seed, the counts and the sha256 of each file; `tests/test_training_split_disjoint.py` checks zero train/val overlap, zero overlap with the benchmark cases, matching digests, and that regenerating with the recorded seed reproduces the files byte for byte. The generator has only 5 hand-written scenarios and 8 templated domains, so the set is small (13 unique instructions); the earlier files repeated them 95 times and held every val instruction in train as well.

---

## Evaluation status

**No published evaluation yet (UNVERIFIED).**

This README used to carry a "Top 10" ranking table, tier-list charts and an "empirical A100 scorecard". None of those figures came from a run anyone can inspect: the scores for Simplicio 27B and for every rival model were literals typed into a script and a notebook, the notebooks ship without outputs, and no logs were published. The tables, the charts that repeated them and the script that printed them have been removed.

This project therefore makes **no claim** about how Simplicio 27B ranks against any other model, how many tokens it saves, or how often its patches pass tests.

What exists today:

- [`benchmark_simplicio_27b.py`](./benchmark_simplicio_27b.py) is a small smoke-evaluation harness. It prints only what it measures on the run you give it: SEARCH-chunk hit rate, `ast.parse` validity of the patched code, presence of the five phase tags and generated tokens per task. It does **not** run pytest and compares against no other model.
- The Colab notebooks hold sample cases and no stored outputs.
- `benchmarks/run_*.py` are scaffolds that list sample instances. No model inference or scoring is implemented in them.
- `tests/test_training_benchmark_overlap.py` in the main repository keeps every benchmark case disjoint from `data/*.jsonl`. The earlier `tax_id` case was also a train/val record, so it was removed.

A number will be published here only together with the raw logs, the commit, and the hardware and model identifiers that produced it.

### Cases in the smoke suite

| Test Case ID | Target File / Module | Engineering Task |
| :--- | :--- | :--- |
| `py_dict_key_error` | `token_extractor.py` | Safely extract roles using `.get()` to prevent `KeyError` on optional JWT claims |
| `py_zero_division` | `metrics.py` | Guard `total_visits == 0` returning `0.0` to eliminate `ZeroDivisionError` |
| `py_resource_leak` | `ledger_writer.py` | Refactor raw `open()` to `with open(...) as f:` context manager to prevent descriptor leak |
| `py_list_mutation` | `filter_queue.py` | Eliminate in-place list mutation bug using list comprehension `[t for t in queue if ...]` |

---

### Running the harness and scaffolds

From this directory:

```bash
# Smoke harness: import run_benchmark(model, tokenizer, TEST_CASES) in a GPU session (for example Colab)
python benchmark_simplicio_27b.py

# Scaffolds: list sample instances only, no model is run and no score is produced
python benchmarks/run_aider_benchmark.py
python benchmarks/run_swebench_eval.py
python benchmarks/run_livecodebench.py
python benchmarks/run_evalplus_humaneval.py
```

Or open the sample-case notebook in Google Colab on a GPU:
- [`Simplicio_27B_2026_Benchmarks_Colab.ipynb`](./Simplicio_27B_2026_Benchmarks_Colab.ipynb)
- [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/gist/wesleysimplicio/1f7de17399f64bb6f71895ab7401bd88)

---


## The 50 Points of Simplicio-Loop

<p align="center">
  <img src="https://raw.githubusercontent.com/simpletibr/simplicio-27b/main/assets/simplicio_loop_pipeline.svg" alt="The 50 Points of Simplicio-Loop Protocol Execution" width="100%">
</p>

Simplicio 27B internalizes the full 50-point specification codified across 5 strict execution stages:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        SIMPLICIO-LOOP PROTOCOL                         │
├───────────────┬───────────────┬───────────────┬────────────────┬───────┤
│    ORIENT     │     PLAN      │     PATCH     │    VALIDATE    │DELIVER│
│ (Points 1-10) │(Points 11-20) │(Points 21-30) │ (Points 31-40) │(41-50)│
└───────────────┴───────────────┴───────────────┴────────────────┴───────┘
```

### Phase I: State Orientation & Mapping (Points 1 to 10)
1. **Repository & Root Identification**: Zero-assumption detection of root workspace.
2. **Topological Symbol Mapping**: Pre-construction of dependency graph before editing.
3. **Type Signature Introspection**: Strict reading of signatures over raw dumps.
4. **Mutable State Isolation**: Clear separation between source, runtime caches, and state.
5. **Read Cost Audit**: Rejection of massive dumps when targeted symbol inspection suffices.
6. **Local Contract Verification**: Mandatory compliance with repo guidelines and schemas.
7. **Runtime & Dependency Detection**: Strict verification of compilers, runtimes, and active packages.
8. **Layered Architecture Analysis**: Decoupled understanding of UI, Core, Data, and Transport layers.
9. **Ambiguity Elimination**: Proactive resolution of unspecified requirements before action.
10. **Baseline Handle Snapshot**: Generation of a state hash/commit reference prior to modifications.

### Phase II: Atomic Decomposition & Planning (Points 11 to 20)
11. **Atomic Task Breakdown**: Subtask decomposition with unequivocal exit criteria.
12. **Specialized Tool Routing**: Explicit tool selection (`simplicio_edit` vs shell vs codegen).
13. **Linearized Execution Plan**: Strictly ordered steps to prevent cascading breakages.
14. **Fan-Out Barriers**: Hard isolation preventing simultaneous uncoupled file edits.
15. **Side-Effect Forecasting**: Pre-mapping of components affected by API changes.
16. **Ghost Assumption Ban**: Prohibition of calling non-existent symbols or packages.
17. **Constraint Hierarchy**: Strict ordering: Contract > Typing > Logic > Style.
18. **Formal Stopping Condition**: Unambiguous criteria defining loop termination.
19. **Strategic Rollback Handle**: Checkpoint restoration if consecutive failures occur.
20. **Action Rationale Logging**: Concise technical rationale preceding any destructive edit.

### Phase III: Surgical Diff Modification (Points 21 to 30)
21. **Diff/Chunk Editing**: Ban on rewriting entire files (>50 lines); use `<<<< SEARCH / ==== / >>>> REPLACE`.
22. **Adjacent Line Preservation**: Exact preservation of surrounding indentation and line breaks.
23. **Comment & Documentation Preservation**: Non-touched preservation of existing docs.
24. **Minimal Sufficient Generation**: Rejection of unrequested cosmetic code.
25. **Strict Signature Alignment**: Type compatibility with existing static systems.
26. **Non-Destructive Imports**: Guarding against namespace collisions and cyclic imports.
27. **Structured Code Generation**: Strict schema conformity without hallucinated fields.
28. **Config File Isolation**: Hard protection against blind edits to system-wide configs.
29. **Patch Idempotency**: Re-applying a patch yields deterministic, duplicate-free results.
30. **Syntactic AST Validation**: Pre-validation of parse trees prior to filesystem commit.

### Phase IV: Validation & Failure-Guided Recovery (Points 31 to 40)
31. **Automated Static Verification**: Immediate typecheck/linter execution post-patch.
32. **Targeted Unit Test Execution**: Focused execution of unit suites for the touched component.
33. **Surgical Error Reading**: Top-of-stack-trace focus, discarding log noise.
34. **Failure-Guided Refinement Loop**: Immediate targeted patch guided by compiler error messages.
35. **Infinite Loop Guard**: Immediate abort if identical error repeats twice without plan update.
36. **Anti-Placebo Testing**: Verification that tests failed prior to patch and pass cleanly after.
37. **Cross-Regression Testing**: Adjacent test suites executed to ensure zero lateral breakages.
38. **Sanitized Shell Handling**: Clean execution without buffer truncations.
39. **Silent Warning Inspection**: Elimination of deprecation and memory-leak warnings.
40. **Edge-Case Validation**: Testing against nulls, empty collections, and network timeouts.

### Phase V: Convergence, Efficiency & Delivery (Points 41 to 50)
41. **Token Pruning & Suppression**: Elimination of verbose conversational prose.
42. **Deterministic Convergence**: Formal output delivery (`simplicio_deliver(status="VERIFIED_GREEN")`).
43. **Explanatory Diff Summary**: Concise factual summary of applied diffs.
44. **Workspace Cleanup**: Automatic removal of test artifacts, temporary logs, and debug prints.
45. **Asymptotic Performance Audit**: Assurance that O(N) complexity was not degraded.
46. **Proven Token Economy**: Measurement of token savings vs. complexity resolved.
47. **Final Interface Validation**: Strict adherence to public CLI flags and HTTP contracts.
48. **Learning Persistence**: Recording repo-specific lessons for subsequent iterations.
49. **Zero-Hallucination Delivery**: Ban on stating "all tests pass" without green test execution proof.
50. **Simplicio Delivery Stamp**: Final production-ready seal (`SELO SIMPLICIO: COMMIT_READY`).

---

## Output Format

Simplicio 27B formats all reasoning and code generation within structured semantic tags:

```xml
<simplicio_loop>
  <orient>
    <!-- Points 1-10: State inspection, symbol graph, signature detection -->
  </orient>
  <plan>
    <!-- Points 11-20: Atomic decomposition, routing, side-effect forecast -->
  </plan>
  <patch>
    <<<< SEARCH
    // original code
    ====
    // surgical replacement
    >>>> REPLACE
    <!-- Points 21-30: Indentation preservation, AST validation -->
  </patch>
  <validate>
    <!-- Points 31-40: Linter, targeted tests, anti-placebo verification -->
  </validate>
  <deliver>
    <!-- Points 41-50: Token pruning, verified delivery, commit-ready seal -->
  </deliver>
</simplicio_loop>
```

---

## Quickstart & Usage

### 1. Inference with Hugging Face Transformers & PEFT

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base_model_id = "Qwen/Qwen3.8-27B"
lora_model_id = "wesleysimplicio/Simplicio-27B"

print("Loading tokenizer and base model...")
tokenizer = AutoTokenizer.from_pretrained(base_model_id)
base_model = AutoModelForCausalLM.from_pretrained(
    base_model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto"
)

print("Attaching Simplicio 27B LoRA adapters...")
model = PeftModel.from_pretrained(base_model, lora_model_id)

system_prompt = (
    "You are Simplicio 27B, trained to execute software development tasks "
    "strictly following the 50 points of the Simplicio-Loop: Orientation, Planning, "
    "Surgical Diff Patching, Validation, and Verified Delivery without hallucination."
)

prompt = f"""<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
Repository Context: simpletibr/api-gateway (Python 3.11, FastAPI, Pydantic v2)
Task: Fix 422 Unprocessable Entity when 'tax_id' is supplied with punctuation '123.456.789-00'.<|im_end|>
<|im_start|>assistant
"""

inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
outputs = model.generate(**inputs, max_new_tokens=512, temperature=0.2)
print(tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=False))
```

### 2. High-Throughput Serving with vLLM

Merge the LoRA adapters into a single 16-bit checkpoint:
```bash
python -c "
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base = AutoModelForCausalLM.from_pretrained('Qwen/Qwen3.8-27B')
model = PeftModel.from_pretrained(base, 'wesleysimplicio/Simplicio-27B')
merged = model.merge_and_unload()
merged.save_pretrained('./simplicio-27b-merged')
"
```

Serve with vLLM:
```bash
vllm serve ./simplicio-27b-merged     --tensor-parallel-size 1     --max-model-len 4096     --gpu-memory-utilization 0.90
```

---

## Training Details

- **Google Colab Notebook**: Available via 1-click execution in Google Colab Pro ([`Simplicio_27B_Training_Colab.ipynb`](https://colab.research.google.com/gist/wesleysimplicio/1f7de17399f64bb6f71895ab7401bd88)).
- **Hardware**: Single NVIDIA A100-SXM4 (40GB VRAM) on Google Cloud.
- **Batch Size**: 1 (Gradient Accumulation Steps: 8, effective batch size: 8).
- **Optimizer**: AdamW 8-bit (`learning_rate = 2e-4`, Cosine learning rate scheduler).
- **Quantization**: 4-bit Normal Float (NF4) with Double Quantization via Unsloth.

---

## 📚 Citation & Framework Reference

If you utilize **Simplicio 27B** or the **Simplicio-Loop** framework in your research, agentic tools, or evaluation benchmarks, please cite both the official framework repository and the model weights:

```bibtex
@software{simplicio_loop_2026,
  author = {Wesley Simplicio},
  title = {Simplicio-Loop: Deterministic Agentic Engineering Framework and Simplicio 27B Model},
  year = {2026},
  publisher = {GitHub and Hugging Face},
  url = {https://github.com/simpletibr/simplicio-loop},
  howpublished = {\url{https://huggingface.co/wesleysimplicio/Simplicio-27B}}
}
```

### 🔗 Official Repositories & Resources
- **Simplicio-Loop Core Framework**: [https://github.com/simpletibr/simplicio-loop](https://github.com/simpletibr/simplicio-loop)
- **Hugging Face Model & LoRA Weights**: [https://huggingface.co/wesleysimplicio/Simplicio-27B](https://huggingface.co/wesleysimplicio/Simplicio-27B)
- **Author**: Wesley Simplicio ([@simpletibr](https://github.com/simpletibr))
- **Base Architecture**: Qwen Team ([Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B))
- **Kernel & Training Optimization**: [Unsloth AI](https://github.com/unslothai/unsloth)
