# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `f7f43e32` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | economia de custo cobrado com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1-batch · total | 1/1 | 2 | 44.0 | $0.00048 | $0.00039 | 1 | 47.9% | $0.00064 | $0.00025 | 1/1 | 12 | 89.9 | $0.01796 | ⚠ $0.00468 (<80%) | 1 | 43.7% | $0.00728 | $0.00260 | $-0.01748 (-3670.8%) |
| t4 · total | 4/4 | 12 | 194.8 | $0.01234 | $0.00206 | 3 | 53.4% | $0.00375 | $0.00168 | 4/4 | 45 | 360.0 | $0.03523 | $0.00649 | 4 | 90.3% | $0.02796 | $0.02146 | $-0.02290 (-185.6%) |
| t4 · criação | 2/2 | 4 | 94.8 | $0.00327 | $0.00108 | 1 | 23.5% | $0.00133 | $0.00024 | 2/2 | 26 | 184.6 | $0.02180 | $0.00363 | 2 | 91.8% | $0.01695 | $0.01332 | $-0.01853 (-566.5%) |
| t4 · edição | 2/2 | 8 | 100.0 | $0.00906 | $0.00098 | 2 | 68.0% | $0.00242 | $0.00144 | 2/2 | 19 | 175.4 | $0.01343 | $0.00287 | 2 | 88.0% | $0.01101 | $0.00814 | $-0.00437 (-48.2%) |
| t4-batch · total | 4/4 | 12 | 164.8 | $0.00171 | $0.00115 | 1 | 89.9% | $0.00564 | $0.00449 | 4/4 | 13 | 161.2 | $0.00682 | $0.00298 | 1 | 92.2% | $0.01066 | $0.00768 | $-0.00511 (-297.8%) |

Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é 3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo calculado quando o uso nunca assenta dentro da janela (`cost_source = computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o campo (recalculado aqui a partir dos tokens armazenados, nunca editando o results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1-batch](REPORT-t1-batch.html) — `2026-09-26-f7f43e32-t1-batch.json`
- [t4](REPORT-t4.html) — `2026-09-26-f7f43e32-t4.json`
- [t4-batch](REPORT-t4-batch.html) — `2026-09-26-f7f43e32-t4-batch.json`
