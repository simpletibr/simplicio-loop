# v14 INTERIM — bench funcional (PHPUnit) 3 models × 12 cases × 5 sides

Snapshot: **2026-05-31 01:56:07**

Bench rodando em background, dados parciais dos logs. Modelos com `-> baseline...` fecharam; os outros ainda rodam.

## Configuração

| model | backend | tiers sp |
|---|---|---|
| `deepseek/deepseek-v4-flash` | OpenRouter API | 64 → 100 |
| `local:Qwen/Qwen2.5-Coder-3B-Instruct` | transformers CPU fp32 | 4 (single cycle) |
| `local:Qwen/Qwen2.5-Coder-1.5B-Instruct` | transformers CPU fp32 | 4 (single cycle) |

**Bench**: 12 cases reais sindico, PHPUnit como oracle. Schema v1 ativo em todos os lados sp.

## Status por modelo

### `deepseek-v4-flash`

**STATUS: FECHADO** (12/12 cases)

| Side | Passed | Rate | Δ vs baseline |
|---|---|---|---|
| baseline | 6/12 | 50% | — |
| cli | 11/12 | 91% | **+41** |
| cli+sp | 9/12 | 75% | **+25** |
| cli+ag | 12/12 | 100% | **+50** |
| cli+sp+ag | 12/12 | 100% | **+50** |

| Case | base | cli | cli+sp (parse) | cli+ag | cli+sp+ag |
|---|---|---|---|---|---|
| password_strength | . | P |  PASS [N=64 u=62 modal=2 parse=59/64] | P(1/3) | P(1/3) |
| password_require_symbol | P | P |  PASS [N=64 u=60 modal=3 parse=57/64] | P(1/3) | P(1/3) |
| env_get_int | . | P |  PASS [N=64 u=57 modal=3 parse=59/64] | P(1/3) | P(1/3) |
| env_get_bool | . | P |  PASS [N=64 u=55 modal=4 parse=55/64] | P(1/3) | P(1/3) |
| admin_only_allowed_roles | P | P |  PASS [N=64 u=39 modal=8 parse=61/64] | P(1/3) | P(1/3) |
| rate_limit_bucket_key | . | P |  PASS [N=64 u=30 modal=18 parse=58/64] | P(1/3) | P(1/3) |
| base_repository_build_where_sql | P | P |  PASS [N=100 u=73 modal=9 parse=82/100] | P(1/3) | P(1/3) |
| router_has | P | P |  fail | P(1/3) | P(1/3) |
| bugfix_password_policy_lowercase | . | P |  fail | P(1/3) | P(1/3) |
| password_assess | P | P |  PASS [N=64 u=62 modal=3 parse=56/64] | P(1/3) | P(1/3) |
| base_repository_build_update_sql | . | . |  PASS [N=64 u=59 modal=4 parse=52/64] | P(1/3) | P(1/3) |
| router_extract_params | P | P |  fail | P(1/3) | P(1/3) |

### `local:Qwen/Qwen2.5-Coder-3B-Instruct`

**STATUS: EM ANDAMENTO** (0/12 cases)

## Achados notáveis

_Quando o batch terminar, completo o relatório com PDF final + grand totals_

- **DeepSeek V4 Flash** honra schema v1 em média **81%** dos N=64 subagents (552 parse_ok de 712 totais)
- DeepSeek + cli+sp: **9/12 cases passam** (parou cycle 1 em todos, sem precisar escalar pra N=100)
