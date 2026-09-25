# Bench v14 — Qwen 2.5 Coder 1.5B (GGUF Q5_K_M) — parcial 2/12

Date: **2026-05-31**
Status: **incompleto** (interrompido pelo operador em 2/12)

Smoke parcial do bench v14 com Qwen 1.5B Coder em quantização Q5_K_M
(via `llama-cpp-python`), pra medir comportamento de modelo coder *muito
pequeno* frente aos 5 lados (`baseline | cli | cli+sp | cli+ag | cli+sp+ag`).

## Setup

| param | valor |
|---|---|
| modelo | `Qwen/Qwen2.5-Coder-1.5B-Instruct` (GGUF Q5_K_M, ~1.1GB) |
| backend | `llama-cpp-python` (CPU, 8 threads) |
| ctx | 4096 |
| max tokens | 1024 |
| temp | 0.7 |
| BENCH_SP_TIERS | `4` (sp_fanout reduzido) |
| BENCH_AGENTS_MAX_ATTEMPTS | 3 |
| BENCH_PHPUNIT_TIMEOUT | 60s |

Variáveis: `STRUCTURED_OUTPUT=v1` ativo, prompt v1.9 runtime carregado de
`/tmp/prompt_check/prompts/agent-runtime-execution-prompt.md`.

## Resultados parciais (2/12 cases)

| # | case | baseline | cli | cli+sp | cli+ag | cli+sp+ag |
|---|---|---|---|---|---|---|
| 1 | password_strength       | fail | fail | fail (parse 0/4) | **PASS 1/3** | fail 3/3 |
| 2 | password_require_symbol | fail | fail | fail (parse 0/4) | fail 3/3       | fail 3/3 |

Wall-clock por case: **~55min** (CPU 8t). Loading inicial GGUF ~3s.

## Observações

1. **Schema v1 falha em 1.5B (parse=0/4 em 2 cases)**. Confirma a hipótese
   da fronteira inferior: Qwen 3B coder atinge 4/4 (smoke prévio), Qwen
   1.5B coder não consegue articular o JSON estruturado de 6 campos.
2. **cli+ag passa onde cli+sp falha** (case 1). Mesmo padrão observado em
   DeepSeek V4 Flash: agents > sp em modelos fracos pra capturar PHPUnit
   verde, porque o loop verify-fix do agent compensa o output bruto.
3. **cli+sp+ag não bate cli+ag puro** (case 1). O sp gasta a primeira
   passada e os agents acabam herdando o estado já tentado; quando cli+ag
   sozinho passa em 1/3, cli+sp+ag não converge em 3/3.
4. **N=4 no sp não é suficiente pra modal-vote** com modelo que não preenche
   schema (parse=0/4 → modal vazio).

## Limitações

- N=2 cases é estatística zero. Indicativo, não conclusivo.
- BENCH_SP_TIERS=4 (cortado por restrição de tempo CPU); produção usa 64+.
- Bench interrompido pelo operador em t≈2h pra evitar consumo prolongado.

## O que isso vale

Sinal pra documentar a curva de degradação por tamanho dentro da família
Qwen Coder:

| modelo | tamanho | parse_ok rate | cli+ag |
|---|---|---|---|
| Gemma-4B-it | 4B (general) | 0% (smoke prévio) | — |
| **Qwen 1.5B Coder** (GGUF Q5_K_M) | **1.5B** | **0% (0/8)** | **1/2 cases** |
| Qwen 3B Coder (fp32) | 3B | 100% (4/4 smoke) | — |
| DeepSeek V4 Flash | ~37B | 91% (12 cases) | 12/12 |

Curva: 1.5B é abaixo da fronteira pra schema v1. 3B atinge. Especialização
coder não compensa abaixo de ~3B.

## Próximos passos sugeridos

1. **Re-rodar com Qwen 3B Coder em GGUF Q5_K_M** (não em fp32). Deve atingir
   parse=~100% mantendo perf ~10× CPU fp32. Não foi tentado por falta de
   janela de execução nesta sessão.
2. **Bench v14 completo Qwen 1.5B GGUF** continua viável (~9h restantes),
   mas com baixíssimo retorno informacional já estabelecido pelos 2 cases.
3. **Suporte a Qwen 7B Coder GGUF Q5_K_M** pra completar a curva
   (1.5B → 3B → 7B → 32B/37B) no mesmo backend.

## Arquivos relevantes

- log do run: `/tmp/v14_qwen15b_gguf.log` (volátil, container ephemeral)
- workspace de execução: `/tmp/sindico_v14_qwen15b_gguf/` (volátil)
- JSON consolidado: **não gerado** (interrompido antes do save)
- backend GGUF no bench: `bench/run_offline.py` (commit `bea3d7c`)
