# Ablation benchmark — 5 arms (issue #1337)

Modelo: `deepseek/deepseek-v4.1-flash` · braços: normal, mapper, devcli, mapper-devcli, simplicio

## t1

- **Menor custo:** `normal` ($0.00030 calculado, $0.00048 cobrado, 1/1 ok)
- **Mais rápido:** `normal` (48.0s, 1/1 ok)

### Total

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | custo sem cache | economia do cache | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | 1/1 | 2 | 48.0 | $0.00030 | $0.00048 | 60.8% | $0.00062 | $0.00031 | 15153 | 9216 | 302 |
| mapper | 1/1 | 7 | 60.0 | $0.00080 | $0.00521 | 85.9% | $0.00292 | $0.00212 | 72602 | 62336 | 1292 |
| mapper-devcli | 1/1 | 12 | 102.8 | $0.00233 | $0.01397 | 88.5% | $0.01040 | $0.00807 | 268186 | 237440 | 3489 |
| simplicio | 1/1 | 13 | 134.1 | $0.00300 | $0.01119 | 81.8% | $0.00886 | $0.00585 | 210576 | 172160 | 5129 |
| devcli | 1/1 | 33 | 323.2 | $0.01389 | $0.07648 | 71.6% | $0.03760 | $0.02371 | 973885 | 697472 | 12115 |

## t4

- **Menor custo:** `normal` ($0.00172 calculado, $0.00914 cobrado, 4/4 ok)
- **Mais rápido:** `normal` (208.1s, 4/4 ok)

### Total

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | custo sem cache | economia do cache | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | 4/4 | 11 | 208.1 | $0.00172 | $0.00914 | 59.4% | $0.00344 | $0.00172 | 85137 | 50560 | 1586 |
| mapper | 4/4 | 27 | 296.4 | $0.00385 | $0.01294 | 82.2% | $0.01236 | $0.00852 | 304746 | 250496 | 5849 |
| simplicio | 4/4 | 44 | 406.1 | $0.00739 | $0.04429 | 87.2% | $0.02674 | $0.01936 | 652661 | 569344 | 13448 |
| devcli | 4/4 | 71 | 1345.9 | $0.01237 | $0.02344 | 90.6% | $0.05380 | $0.04143 | 1345236 | 1218432 | 23162 |
| mapper-devcli | 4/4 | 59 | 644.7 | $0.01267 | $0.10650 | 85.0% | $0.05316 | $0.04049 | 1400865 | 1190784 | 14240 |

### Criação (create)

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | custo sem cache | economia do cache | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | 2/2 | 4 | 100.1 | $0.00094 | $0.00207 | 35.7% | $0.00131 | $0.00037 | 30515 | 10880 | 850 |
| mapper | 2/2 | 12 | 128.6 | $0.00188 | $0.00660 | 76.3% | $0.00543 | $0.00355 | 136812 | 104320 | 2196 |
| simplicio | 2/2 | 23 | 193.4 | $0.00376 | $0.02565 | 89.3% | $0.01411 | $0.01035 | 340745 | 304384 | 7517 |
| devcli | 2/2 | 25 | 276.9 | $0.00389 | $0.00924 | 89.2% | $0.01492 | $0.01103 | 363813 | 324480 | 7538 |
| mapper-devcli | 2/2 | 29 | 329.2 | $0.00736 | $0.06393 | 80.1% | $0.02639 | $0.01903 | 698691 | 559616 | 6663 |

### Edição (edit)

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | custo sem cache | economia do cache | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | 2/2 | 7 | 108.1 | $0.00078 | $0.00707 | 72.6% | $0.00213 | $0.00135 | 54622 | 39680 | 736 |
| mapper | 2/2 | 15 | 167.7 | $0.00197 | $0.00634 | 87.0% | $0.00694 | $0.00497 | 167934 | 146176 | 3653 |
| simplicio | 2/2 | 21 | 212.7 | $0.00363 | $0.01865 | 84.9% | $0.01264 | $0.00901 | 311916 | 264960 | 5931 |
| mapper-devcli | 2/2 | 30 | 315.6 | $0.00531 | $0.04256 | 89.9% | $0.02677 | $0.02146 | 702174 | 631168 | 7577 |
| devcli | 2/2 | 46 | 1068.9 | $0.00849 | $0.01420 | 91.1% | $0.03888 | $0.03039 | 981423 | 893952 | 15624 |

