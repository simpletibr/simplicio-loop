# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `9165efe04` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo cobrado | custo calculado | sinalizados | cache hit | custo sem cache | economia do cache | economia de custo cobrado com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 2 | 18.4 | $0.00000 | $0.00037 | 1 | 47.3% | $0.00062 | $0.00024 | 1/1 | 10 | 58.1 | $0.00691 | $0.00169 | 1 | 85.4% | $0.00603 | $0.00433 | $-0.00691 (n/a) |
| t1 · criação | 1/1 | 2 | 18.4 | $0.00000 | $0.00037 | 1 | 47.3% | $0.00062 | $0.00024 | 1/1 | 10 | 58.1 | $0.00691 | $0.00169 | 1 | 85.4% | $0.00603 | $0.00433 | $-0.00691 (n/a) |
| t1-batch · total | 1/1 | 6 | 27.0 | $0.00330 | $0.00080 | 1 | 72.6% | $0.00217 | $0.00137 | 1/1 | 10 | 47.7 | $0.00839 | $0.00182 | 1 | 81.7% | $0.00617 | $0.00435 | $-0.00509 (-154.3%) |
| t4 · total | 4/4 | 18 | 135.8 | $0.04566 | $0.00220 | 4 | 73.1% | $0.00612 | $0.00393 | 4/4 | 45 | 283.2 | $0.04128 | $0.00625 | 4 | 89.5% | $0.02546 | $0.01921 | $0.00438 (9.6%) |
| t4 · criação | 2/2 | 9 | 73.2 | $0.01904 | $0.00109 | 2 | 78.4% | $0.00343 | $0.00234 | 2/2 | 24 | 167.0 | $0.02704 | $0.00361 | 2 | 87.5% | $0.01408 | $0.01047 | $-0.00800 (-42.0%) |
| t4 · edição | 2/2 | 9 | 62.6 | $0.02662 | $0.00111 | 2 | 66.5% | $0.00269 | $0.00158 | 2/2 | 21 | 116.2 | $0.01424 | $0.00264 | 2 | 92.0% | $0.01138 | $0.00874 | $0.01238 (46.5%) |
| t4-batch · total | 4/4 | 6 | 111.5 | $0.00175 | $0.00088 | 1 | 81.0% | $0.00265 | $0.00177 | 4/4 | 20 | 135.2 | $0.01129 | $0.00288 | 1 | 92.7% | $0.01469 | $0.01181 | $-0.00954 (-543.8%) |

Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é 3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo calculado quando o uso nunca assenta dentro da janela (`cost_source = computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o campo (recalculado aqui a partir dos tokens armazenados, nunca editando o results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-27-f7f43e324-t1.json`
- [t1-batch](REPORT-t1-batch.html) — `2026-09-27-f7f43e324-t1-batch.json`
- [t4](REPORT-t4.html) — `2026-09-27-f7f43e324-t4.json`
- [t4-batch](REPORT-t4-batch.html) — `2026-09-27-f7f43e324-t4-batch.json`
