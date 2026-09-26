# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `openrouter/deepseek/deepseek-v4.1-flash` · commit: `c36db59ee` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo real | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo real | cache hit | custo sem cache | economia do cache | economia de custo real com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 2 | 18.1 | $0.00263 | 60.9% | $0.00487 | $0.00271 | 1/1 | 7 | 20.4 | $0.00601 | 80.2% | $0.03176 | $0.02341 | $-0.00337 (-128.0%) |
| t1 · criação | 1/1 | 2 | 18.1 | $0.00263 | 60.9% | $0.00487 | $0.00271 | 1/1 | 7 | 20.4 | $0.00601 | 80.2% | $0.03176 | $0.02341 | $-0.00337 (-128.0%) |
| t1-batch · total | 1/1 | 2 | 21.1 | $0.00048 | 60.7% | $0.00492 | $0.00271 | 1/1 | 8 | 35.9 | $0.00502 | 84.8% | $0.03751 | $0.02965 | $-0.00455 (-954.9%) |
| t4 · total | 4/4 | 14 | 58.5 | $0.00633 | 86.7% | $0.03474 | $0.02789 | 4/4 | 28 | 148.3 | $0.01969 | 82.0% | $0.12780 | $0.09589 | $-0.01336 (-211.0%) |
| t4 · criação | 2/2 | 6 | 29.1 | $0.00510 | 72.8% | $0.01536 | $0.01020 | 2/2 | 14 | 61.8 | $0.00824 | 82.0% | $0.06388 | $0.04817 | $-0.00313 (-61.4%) |
| t4 · edição | 2/2 | 8 | 29.4 | $0.00123 | 97.5% | $0.01937 | $0.01769 | 2/2 | 14 | 86.5 | $0.01145 | 81.9% | $0.06392 | $0.04772 | $-0.01022 (-832.1%) |
| t4-batch · total | 4/4 | 6 | 66.3 | $0.00096 | 80.8% | $0.02038 | $0.01505 | 4/4 | 10 | 46.0 | $0.00606 | 85.7% | $0.06455 | $0.05001 | $-0.00510 (-531.3%) |

Custo real = cobrado pelo OpenRouter (desconto de cache incluído). Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-26-c36db59ee-t1.json`
- [t1-batch](REPORT-t1-batch.html) — `2026-09-26-c36db59ee-t1-batch.json`
- [t4](REPORT-t4.html) — `2026-09-26-c36db59ee-t4.json`
- [t4-batch](REPORT-t4-batch.html) — `2026-09-26-c36db59ee-t4-batch.json`
