# Local GGUF quant bench — Qwen2.5-Coder-1.5B-Instruct

Benchmarks bartowski GGUF quantizations of `Qwen2.5-Coder-1.5B-Instruct`,
served locally through **ollama** (OpenAI-compatible endpoint) against the
repo's own execution harness `bench/run_exec.py`.

- **Hardware:** Apple M1, 8 GB RAM (100% GPU / Metal).
- **Harness:** `bench/run_exec.py` — 6 self-contained cases, scored by running
  the model's `solution.py` against a hidden pytest suite. Single-shot per
  side (no verify/retry loop), so this measures the *prompt* effect only, not
  the verify-loop effect.
- **Cases:** `can_delete`, `email_editable`, `slugify`, `apply_discount`,
  `merge_intervals`, `validate_password`.

## Results

| Quant | file | RAM | without simplicio | with simplicio | throughput (agg) |
|---|---|---|---|---|---|
| Q5_K_M | 1.0 GB | 1.7 GB | 66% (4/6) | 66% (4/6) | ~63 tok/s |
| Q8_0   | 1.5 GB | ~2.2 GB | **83% (5/6)** | 66% (4/6) | ~42 tok/s |

Per-case (Q8_0): `can_delete` pass · `apply_discount` pass · `validate_password`
pass · `merge_intervals` fail→pass with contract · `email_editable` pass→fail ·
`slugify` pass→fail.

## Findings

- **Q8_0 wins on raw quality** (83% vs 66%); higher precision helps the 1.5B.
  Cost: ~33% slower and ~0.5 GB more RAM. Both fit in 8 GB on GPU.
- **The contract alone did not help** these 1.5B quants single-shot (Q8_0
  regressed 83%→66%, Q5_K_M flat). It tends to win the hard case
  (`merge_intervals`) and lose the easy ones — a small model gets tripped up by
  the longer structured prompt.
- **Divergence from the README 1.5B numbers (30%→92%)** is expected: those used
  full-precision transformers + the verify-loop. `run_exec.py` is single-shot,
  so the loop (the main source of simplicio's gain) is not exercised here.

## Reproduce

```bash
# 1. tooling (venv + simplicio editable + hf cli)
uv venv .venv --python 3.12
uv pip install -e . --python .venv/bin/python
uv pip install "huggingface_hub" pytest openai --python .venv/bin/python

# 2. download a quant
.venv/bin/hf download bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF \
  Qwen2.5-Coder-1.5B-Instruct-Q8_0.gguf --local-dir ./models

# 3. import into ollama (see models/Modelfile.q5km / models/Modelfile.q8)
ollama create qwen2.5-coder-1.5b-q8 -f models/Modelfile.q8

# 4. run the repo harness against the local model
BENCH_BASE_URL=http://localhost:11434/v1 BENCH_API_KEY=dummy \
  BENCH_MODELS=qwen2.5-coder-1.5b-q8 \
  .venv/bin/python bench/run_exec.py
```

> GGUF blobs (`models/*.gguf`) are gitignored — only the ollama Modelfiles and
> this doc are tracked.
