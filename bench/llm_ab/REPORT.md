# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `790061e2` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | economia de custo cobrado com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 2 | 17.5 | $0.00230 | $0.00230 | 1 | 60.0% | $0.00501 | $0.00271 | 1/1 | 1 | 2.3 | $0.00142 | $0.00142 | 0 | ⚠ 0.0% (<80%) | $0.00142 | $0.00000 | $0.00088 (38.1%) |
| t1 · criação | 1/1 | 2 | 17.5 | $0.00230 | $0.00230 | 1 | 60.0% | $0.00501 | $0.00271 | 1/1 | 1 | 2.3 | $0.00142 | $0.00142 | 0 | ⚠ 0.0% (<80%) | $0.00142 | $0.00000 | $0.00088 (38.1%) |
| t4 · total | 4/4 | 14 | 64.5 | $0.01199 | $0.01057 | 3 | 74.9% | $0.03462 | $0.02405 | 4/4 | 4 | 9.3 | $0.00237 | $0.00237 | 0 | ⚠ 74.8% (<80%) | $0.00609 | $0.00373 | $0.00962 (80.3%) |
| t4 · criação | 2/2 | 6 | 31.9 | $0.00606 | $0.00494 | 2 | 73.0% | $0.01487 | $0.00993 | 2/2 | 4 | 9.3 | $0.00237 | $0.00237 | 0 | ⚠ 74.8% (<80%) | $0.00609 | $0.00373 | $0.00369 (60.9%) |
| t4 · edição | 2/2 | 8 | 32.6 | $0.00593 | $0.00564 | 1 | 76.4% | $0.01975 | $0.01411 | 2/2 | 0 | 0.0 | $0.00000 | $0.00000 | 0 | ⚠ 0.0% (<80%) | $0.00000 | $0.00000 | $0.00593 (100.0%) |

Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é 3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo calculado quando o uso nunca assenta dentro da janela (`cost_source = computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o campo (recalculado aqui a partir dos tokens armazenados, nunca editando o results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-29-790061e2-t1.json`
- [t4](REPORT-t4.html) — `2026-09-29-790061e2-t4.json`
