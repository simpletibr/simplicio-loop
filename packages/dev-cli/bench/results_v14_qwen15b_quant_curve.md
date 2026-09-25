# Qwen 1.5B Quant Curve

final Qwen2.5-Coder-1.5B GGUF quant curve assembled from manifest-declared schema-v1 smoke artifacts

## Summary

- release ready: True
- quant curve complete: True
- decision: not viable for schema-v1: required quant smokes failed; skip full bench unless the smoke protocol changes
- required quant smokes present: Q8_0=True, Q6_K_L=True, Q6_K=True, Q5_K_L=True, Q5_K_M=True, Q4_K_M=True, Q4_K_S=True, Q4_0=True
- required quant smokes passed: Q8_0=False, Q6_K_L=False, Q6_K=False, Q5_K_L=False, Q5_K_M=False, Q4_K_M=False, Q4_K_S=False, Q4_0=False
- missing quant smokes: none
- failed required quant smokes: Q8_0, Q6_K_L, Q6_K, Q5_K_L, Q5_K_M, Q4_K_M, Q4_K_S, Q4_0

## Rows

| quant | smoke JSON | calls | parse ok | parse failed | pass | sha256 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Q8_0 | `bench/results_v14_qwen15b_q8_0_smoke_schema_v1.json` | 4 | 0 | 4 | False | `4a176c086aec` |
| Q6_K_L | `bench/results_v14_qwen15b_q6_k_l_smoke_schema_v1.json` | 4 | 0 | 4 | False | `efa9d711b657` |
| Q6_K | `bench/results_v14_qwen15b_q6_k_smoke_schema_v1.json` | 4 | 0 | 4 | False | `b3a82688952a` |
| Q5_K_L | `bench/results_v14_qwen15b_q5_k_l_smoke_schema_v1.json` | 4 | 0 | 4 | False | `2a02ab8a1a7d` |
| Q5_K_M | `bench/results_v14_qwen15b_q5_k_m_smoke_schema_v1.json` | 4 | 0 | 4 | False | `5c9a31a81983` |
| Q4_K_M | `bench/results_v14_qwen15b_q4_k_m_smoke_schema_v1.json` | 4 | 0 | 4 | False | `db94ce4579a8` |
| Q4_K_S | `bench/results_v14_qwen15b_q4_k_s_smoke_schema_v1.json` | 4 | 0 | 4 | False | `f45eb47e02b1` |
| Q4_0 | `bench/results_v14_qwen15b_q4_0_smoke_schema_v1.json` | 4 | 0 | 4 | False | `d1b524a55da6` |
