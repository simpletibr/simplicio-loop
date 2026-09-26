# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)

Modelo: `deepseek/deepseek-v4.1-flash` · commit: `8b206caae` · braços: normal, simplicio

## Resumo (normal vs simplicio)

| combinação | normal ok | turnos | tempo (s) | custo real | cache hit | custo sem cache | economia do cache | simplicio ok | turnos | tempo (s) | custo real | cache hit | custo sem cache | economia do cache | economia de custo real com simplicio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t1 · total | 1/1 | 6 | 25.3 | $0.00237 | 52.0% | $0.00400 | $0.00163 | 1/1 | 8 | 46.0 | $0.00440 | 58.0% | $0.00873 | $0.00433 | $-0.00203 (-85.5%) |
| t1 · criação | 1/1 | 6 | 25.3 | $0.00237 | 52.0% | $0.00400 | $0.00163 | 1/1 | 8 | 46.0 | $0.00440 | 58.0% | $0.00873 | $0.00433 | $-0.00203 (-85.5%) |
| t1-batch · total | 1/1 | 5 | 38.5 | $0.00039 | 59.9% | $0.00131 | $0.00063 | 1/1 | 8 | 39.8 | $0.00352 | 75.5% | $0.00994 | $0.00641 | $-0.00313 (-796.7%) |
| t4 · total | 4/4 | 22 | 46.9 | $0.00413 | 64.5% | $0.01944 | $0.00963 | 4/4 | 32 | 136.6 | $0.01298 | 75.9% | $0.08137 | $0.05208 | $-0.00885 (-214.2%) |
| t4 · criação | 2/2 | 10 | 25.1 | $0.00175 | 71.0% | $0.00864 | $0.00433 | 2/2 | 16 | 77.3 | $0.00731 | 76.1% | $0.04429 | $0.02773 | $-0.00556 (-317.5%) |
| t4 · edição | 2/2 | 12 | 21.7 | $0.00238 | 60.0% | $0.01080 | $0.00531 | 2/2 | 16 | 59.3 | $0.00567 | 75.7% | $0.03709 | $0.02435 | $-0.00329 (-138.2%) |
| t4-batch · total | 4/4 | 6 | 13.1 | $0.00153 | 48.0% | $0.00561 | $0.00203 | 4/4 | 13 | 74.9 | $0.00726 | 80.1% | $0.05538 | $0.03872 | $-0.00573 (-375.2%) |

Custo real = cobrado pelo OpenRouter (desconto de cache incluído). Custo sem cache = os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço de cache read da própria execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de criação/edição; veja a execução sequencial do mesmo conjunto.

## Relatórios por combinação

- [t1](REPORT-t1.html) — `2026-09-26-8b206caae-t1.json`
- [t1-batch](REPORT-t1-batch.html) — `2026-09-26-8b206caae-t1-batch.json`
- [t4](REPORT-t4.html) — `2026-09-26-8b206caae-t4.json`
- [t4-batch](REPORT-t4-batch.html) — `2026-09-26-8b206caae-t4-batch.json`
