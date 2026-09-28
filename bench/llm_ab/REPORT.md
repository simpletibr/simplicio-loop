# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `146a6931` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | economia de custo cobrado com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 2 | 19.4 | $0.00262 | $0.00262 | 1 | 59.2% | $0.00532 | $0.00271 | 1/1 | 1 | 14.6 | $0.00363 | $0.00363 | 0 | ⚠ 0.0% (<80%) | $0.00363 | $0.00000 | $-0.00101 (-38.8%) |
| t1 · criação | 1/1 | 2 | 19.4 | $0.00262 | $0.00262 | 1 | 59.2% | $0.00532 | $0.00271 | 1/1 | 1 | 14.6 | $0.00363 | $0.00363 | 0 | ⚠ 0.0% (<80%) | $0.00363 | $0.00000 | $-0.00101 (-38.8%) |
| t4 · total | 4/4 | 12 | 95.3 | $0.00915 | $0.00653 | 4 | 84.7% | $0.02978 | $0.02326 | 4/4 | 4 | 15.0 | $0.00463 | $0.00463 | 0 | ⚠ 49.6% (<80%) | $0.00719 | $0.00256 | $0.00452 (49.4%) |
| t4 · criação | 2/2 | 4 | 30.9 | $0.00271 | $0.00450 | 2 | 60.1% | $0.00992 | $0.00542 | 2/2 | 4 | 15.0 | $0.00463 | $0.00463 | 0 | ⚠ 49.6% (<80%) | $0.00719 | $0.00256 | $-0.00192 (-70.8%) |
| t4 · edição | 2/2 | 8 | 64.4 | $0.00644 | $0.00202 | 2 | 96.6% | $0.01986 | $0.01784 | 2/2 | 0 | 0.0 | $0.00000 | $0.00000 | 0 | ⚠ 0.0% (<80%) | $0.00000 | $0.00000 | $0.00644 (100.0%) |

Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é 3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo calculado quando o uso nunca assenta dentro da janela (`cost_source = computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o campo (recalculado aqui a partir dos tokens armazenados, nunca editando o results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-28-146a6931-t1.json`
- [t4](REPORT-t4.html) — `2026-09-28-146a6931-t4.json`
