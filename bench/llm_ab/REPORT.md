# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `c36db59ee` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | economia de custo cobrado com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 2 | 18.1 | $0.00263 | $0.00216 | 1 | 60.9% | $0.00487 | $0.00271 | 1/1 | 7 | 20.4 | $0.00601 | $0.00836 | 1 | 80.2% | $0.03176 | $0.02341 | $-0.00337 (-128.0%) |
| t1 · criação | 1/1 | 2 | 18.1 | $0.00263 | $0.00216 | 1 | 60.9% | $0.00487 | $0.00271 | 1/1 | 7 | 20.4 | $0.00601 | $0.00836 | 1 | 80.2% | $0.03176 | $0.02341 | $-0.00337 (-128.0%) |
| t1-batch · total | 1/1 | 2 | 21.1 | $0.00048 | $0.00221 | 1 | 60.7% | $0.00492 | $0.00271 | 1/1 | 8 | 35.9 | $0.00502 | $0.00786 | 1 | 84.8% | $0.03751 | $0.02965 | $-0.00455 (-954.9%) |
| t4 · total | 4/4 | 14 | 58.5 | $0.00633 | $0.00685 | 3 | 86.7% | $0.03474 | $0.02789 | 4/4 | 28 | 148.3 | $0.01969 | $0.03191 | 3 | 82.0% | $0.12780 | $0.09589 | $-0.01336 (-211.0%) |
| t4 · criação | 2/2 | 6 | 29.1 | $0.00510 | $0.00517 | 2 | 72.8% | $0.01536 | $0.01020 | 2/2 | 14 | 61.8 | $0.00824 | $0.01571 | 2 | 82.0% | $0.06388 | $0.04817 | $-0.00313 (-61.4%) |
| t4 · edição | 2/2 | 8 | 29.4 | $0.00123 | $0.00169 | 1 | 97.5% | $0.01937 | $0.01769 | 2/2 | 14 | 86.5 | $0.01145 | $0.01621 | 1 | 81.9% | $0.06392 | $0.04772 | $-0.01022 (-832.1%) |
| t4-batch · total | 4/4 | 6 | 66.3 | $0.00096 | $0.00532 | 1 | 80.8% | $0.02038 | $0.01505 | 4/4 | 10 | 46.0 | $0.00606 | $0.01454 | 1 | 85.7% | $0.06455 | $0.05001 | $-0.00510 (-531.3%) |

Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é 3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo calculado quando o uso nunca assenta dentro da janela (`cost_source = computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o campo (recalculado aqui a partir dos tokens armazenados, nunca editando o results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-26-c36db59ee-t1.json`
- [t1-batch](REPORT-t1-batch.html) — `2026-09-26-c36db59ee-t1-batch.json`
- [t4](REPORT-t4.html) — `2026-09-26-c36db59ee-t4.json`
- [t4-batch](REPORT-t4-batch.html) — `2026-09-26-c36db59ee-t4-batch.json`
