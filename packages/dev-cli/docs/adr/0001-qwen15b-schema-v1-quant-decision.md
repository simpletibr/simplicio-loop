# ADR 0001: Qwen2.5-Coder 1.5B GGUF Is Not Viable For Schema V1

Date: 2026-05-31

## Status

Accepted.

## Context

Issue #46 asks whether Qwen2.5-Coder-1.5B-Instruct can satisfy the schema-v1
structured-output contract when less aggressive GGUF quantizations are used.
The original minimum required smoke points were Q8_0, Q6_K, and Q4_K_M from
`bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF`. After expansion (commit
`7ddc935`), the manifest now covers the full bartowski quant table from the
Grok screenshot: **8 quants total — Q4_0, Q4_K_S, Q4_K_M, Q5_K_M, Q5_K_L,
Q6_K, Q6_K_L, Q8_0**.

The go/no-go protocol is `bench/smoke_schema_v1.py --calls 4`. A quant only
deserves the expensive full v14 bench when `parse_ok >= 2/4`.

## Decision

Qwen2.5-Coder-1.5B-Instruct GGUF is not viable for schema-v1 on the tested
CPU smoke protocol — **regardless of quantization**.

All 8 quants from the bartowski table failed:

| quant | size | parse_ok | artifact contract | go/no-go |
| --- | --- | ---: | ---: | --- |
| Q8_0   | 1.65 GB | 0/4 | varies | fail |
| Q6_K_L | 1.33 GB | 0/4 | varies | fail |
| Q6_K   | 1.27 GB | 0/4 | varies | fail |
| Q5_K_L | 1.18 GB | 0/4 | varies | fail |
| Q5_K_M | 1.13 GB | 0/4 | 1/4 | fail |
| Q4_K_M | 0.99 GB | 0/4 | varies | fail |
| Q4_K_S | 0.94 GB | 0/4 | 4/4 | fail |
| Q4_0   | ~0.96 GB | 0/4 | 3/4 | fail |

Key insight: `artifact_contract` (heuristic check that the produced PHP
contains `isStrong`, `function`, `12`, `violations`, `PasswordPolicy`)
**passes in several quants** even though `parse_ok` is always 0/4. The model
*can* write correct PHP — it just refuses to wrap it in the JSON schema.
That is, **the bottleneck is the model size (1.5B is below the
instruction-following boundary for structured JSON output), not the weight
precision**. Q8_0 (highest quality) and Q4_K_S (most aggressive) both fail
identically on schema honor.

Because every quant from Q4_0 to Q8_0 failed, the expensive 12-case v14 bench
is intentionally not run for these quants. The result is a definitive
negative viability decision, not missing bench evidence.

## Evidence

- `bench/results_v14_qwen15b_q8_0_smoke_schema_v1.json`
- `bench/results_v14_qwen15b_q6_k_smoke_schema_v1.json`
- `bench/results_v14_qwen15b_q4_k_m_smoke_schema_v1.json`
- `bench/results_v14_qwen15b_quant_curve.json`
- `bench/results_v14_qwen15b_quant_curve.md`
- `bench/results_v14_qwen15b_quant_curve.pdf`

## Consequences

- Use 3B-class or larger local coder models as the practical lower bound for
  schema-v1 work until a different 1.5B model or prompt protocol proves
  otherwise.
- Do not spend CPU time on the full v14 bench for these 1.5B quants under the
  current smoke protocol.
- Keep future model-family tests separate from this Qwen2.5-Coder-1.5B result.
