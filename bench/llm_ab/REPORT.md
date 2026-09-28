# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `495a79e9` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | economia de custo cobrado com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 2 | 14.4 | $0.00225 | $0.00225 | 1 | 60.9% | $0.00499 | $0.00275 | 1/1 | 1 | 8.5 | $0.00193 | $0.00193 | 0 | ⚠ 0.0% (<80%) | $0.00193 | $0.00000 | $0.00031 (13.9%) |
| t1 · criação | 1/1 | 2 | 14.4 | $0.00225 | $0.00225 | 1 | 60.9% | $0.00499 | $0.00275 | 1/1 | 1 | 8.5 | $0.00193 | $0.00193 | 0 | ⚠ 0.0% (<80%) | $0.00193 | $0.00000 | $0.00031 (13.9%) |
| t4 · total | 4/4 | 13 | 88.4 | $0.00702 | $0.00663 | 4 | 86.2% | $0.03241 | $0.02578 | 4/4 | 4 | 25.9 | $0.00302 | $0.00302 | 0 | ⚠ 69.6% (<80%) | $0.00625 | $0.00324 | $0.00400 (57.0%) |
| t4 · criação | 2/2 | 4 | 34.7 | $0.00405 | $0.00129 | 2 | 96.0% | $0.00995 | $0.00866 | 2/2 | 4 | 25.9 | $0.00302 | $0.00302 | 0 | ⚠ 69.6% (<80%) | $0.00625 | $0.00324 | $0.00104 (25.6%) |
| t4 · edição | 2/2 | 9 | 53.7 | $0.00296 | $0.00534 | 2 | 82.0% | $0.02246 | $0.01712 | 2/2 | 0 | 0.0 | $0.00000 | $0.00000 | 0 | ⚠ 0.0% (<80%) | $0.00000 | $0.00000 | $0.00296 (100.0%) |

Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é 3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo calculado quando o uso nunca assenta dentro da janela (`cost_source = computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o campo (recalculado aqui a partir dos tokens armazenados, nunca editando o results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-28-495a79e9-t1.json`
- [t4](REPORT-t4.html) — `2026-09-28-495a79e9-t4.json`
