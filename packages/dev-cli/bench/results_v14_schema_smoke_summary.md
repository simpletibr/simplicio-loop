# Schema Smoke Summary

incremental schema-smoke artifact summary; this does not replace the required Qwen2.5-Coder-1.5B GGUF quant curve

## Summary

- input files: 5
- go/no-go passes: 2
- go/no-go failures: 3
- Qwen 1.5B smokes: 3
- required quant smokes present: Q8_0=True, Q6_K=True, Q4_K_M=True
- required quant smokes passed: Q8_0=False, Q6_K=False, Q4_K_M=False
- missing quant smokes: none
- failed required quant smokes: Q8_0, Q6_K, Q4_K_M
- Qwen 1.5B quant curve complete: True
- release ready: False

## Rows

| source | model | quant | parse ok | calls | go/no-go |
| --- | --- | --- | ---: | ---: | --- |
| `bench/results_sp_schema_smoke_deepseek.json` | deepseek/deepseek-v4-flash | unknown | 3 | 4 | True |
| `bench/results_sp_schema_smoke_qwen3b.json` | Qwen/Qwen2.5-Coder-3B-Instruct | unknown | 4 | 4 | True |
| `bench/results_v14_qwen15b_q4_k_m_smoke_schema_v1.json` | C:\Users\wesley.simplicio\Pictures\m\tmp\models\qwen25-coder-15b-gguf\Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf | Q4_K_M | 0 | 4 | False |
| `bench/results_v14_qwen15b_q6_k_smoke_schema_v1.json` | C:\Users\wesley.simplicio\Pictures\m\tmp\models\qwen25-coder-15b-gguf\Qwen2.5-Coder-1.5B-Instruct-Q6_K.gguf | Q6_K | 0 | 4 | False |
| `bench/results_v14_qwen15b_q8_0_smoke_schema_v1.json` | C:\Users\wesley.simplicio\Pictures\m\tmp\models\qwen25-coder-15b-gguf\Qwen2.5-Coder-1.5B-Instruct-Q8_0.gguf | Q8_0 | 0 | 4 | False |

## Missing Release Evidence

- none
