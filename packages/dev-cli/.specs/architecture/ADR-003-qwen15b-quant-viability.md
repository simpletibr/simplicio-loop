# ADR-003 — Viabilidade do Qwen2.5-Coder-1.5B (por quantização) para schema v1

- **Status:** Proposed / Partial (veredito interino — pendente dados Q8_0/Q6_K/Q4_K_M)
- **Date:** 2026-05-31
- **Context da decisão:** issue #46, PR #47, bench v14
- **Supersedes:** —

## Contexto

O modelo local default do projeto (quando `SIMPLICIO_MODEL` não é setado) é
`Qwen2.5-Coder-1.5B-Instruct` em GGUF Q5_K_M. O bench v14 parcial (2/12) mostrou
`parse_ok = 0/8` no structured output v1 (6 campos JSON) com esse quant, sugerindo
que 1.5B está **abaixo da fronteira inferior** para seguir o schema v1.

A issue #46 levanta a dúvida legítima: essa falha é do **tamanho** (1.5B) ou da
**quantização agressiva** (Q5_K_M)? Q8_0 do mesmo modelo recupera 83% no codegen
Python single-shot (vs 66% do Q5_K_M, `RESULTS_LOCAL_GGUF.md`), o que mantém a
hipótese viva — mas noutro harness, sem medir o gate de `parse_ok`.

## Decisão (interina)

1. **Não promover 1.5B (qualquer quant) a default para tarefas complexas / schema
   v1** até existir smoke `parse_ok >= 2/4` em Q8_0. Dado atual (Q5_K_M = 0/8)
   não sustenta uso em tarefas que exigem output estruturado.
2. **Piso local medido = 3B** (Qwen2.5-Coder-3B atinge 4/4 no smoke schema v1).
   Para schema v1, 3B é o mínimo recomendado; 7B preferido.
3. **Manter 1.5B Q5_K_M como fallback offline zero-config**, porém documentar o
   teto: serve tarefas simples (1 função, sem schema), não tarefas full-stack.
4. **Gate de promoção:** a curva da issue #46 (Q8_0/Q6_K/Q4_K_M, smoke + bench)
   precisa rodar numa máquina CPU 8t+/GPU. Se Q8_0 atingir `parse_ok >= 75%`,
   este ADR é revisado por um novo ADR ("1.5B-Q8_0 viável para schema v1").

## Consequências

- **Positivas:** evita regressão silenciosa de qualidade ao usar o default local
  em tarefas que ele não aguenta; deixa o critério de promoção explícito e medível.
- **Negativas:** o default offline (1.5B) fica oficialmente "limitado"; usuários
  que querem tarefas complexas offline precisam baixar 3B/7B (mais RAM/disco).
- **Pendência rastreada:** issue #46 permanece aberta até os 3 quants prioritários
  terem smoke + bench salvos em `bench/results_v14_qwen15b_<quant>.json` e a tabela
  de `bench/results_v14_qwen15b_quant_curve.md` preenchida.

## Alternativas consideradas

- **Assumir 1.5B viável e setar como default geral:** rejeitado — sem evidência de
  `parse_ok` em quant alto; risco de quebrar tarefas com schema.
- **Remover 1.5B do projeto:** rejeitado — é ótimo fallback offline para tarefas
  simples e cabe em qualquer laptop (~1.7 GB RAM).
