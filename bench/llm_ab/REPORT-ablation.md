# Ablation benchmark — 7 arms (issue #1337)

Modelo: `deepseek/deepseek-v4.1-flash` · braços: normal, mapper, mapper-fast, devcli, mapper-devcli, fast-devcli, simplicio

## t1

- **Menor custo:** `normal` ($0.00396 calculado, $0.00000 cobrado, 1/1 ok)
- **Mais rápido:** `normal` (22.3s, 1/1 ok)

### Total

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|
| normal | 1/1 | 7 | 22.3 | $0.00396 | $0.00000 | 85.6% | 63689 | 54528 | 741 |
| mapper | 1/1 | 7 | 42.4 | $0.00579 | $0.00497 | 85.8% | 80113 | 68736 | 1635 |
| mapper-fast | 1/1 | 11 | 170.2 | $0.00927 | $0.00188 | 88.9% | 169648 | 150784 | 2259 |
| simplicio | 1/1 | 13 | 43.3 | $0.00954 | $0.00545 | 91.9% | 188207 | 173056 | 3294 |
| fast-devcli | 1/1 | 10 | 38.4 | $0.00966 | $0.00519 | 89.3% | 146706 | 131072 | 3487 |
| devcli | 1/1 | 18 | 48.6 | $0.01650 | $0.01323 | 92.6% | 406460 | 376320 | 4333 |
| mapper-devcli | 1/1 | 15 | 51.0 | $0.01685 | $0.00821 | 89.4% | 323159 | 288896 | 4034 |

