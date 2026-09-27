# Ablation benchmark — 5 arms (issue #1337)

Modelo: `deepseek/deepseek-v4.1-flash` · braços: normal, mapper, devcli, mapper-devcli, simplicio

## t1

- **Menor custo:** `normal` ($0.00015 calculado, $0.00000 cobrado, 1/1 ok)
- **Mais rápido:** `normal` (19.7s, 1/1 ok)

### Total

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|
| normal | 1/1 | 2 | 19.7 | $0.00015 | $0.00000 | 95.8% | 15234 | 14592 | 393 |
| mapper | 1/1 | 7 | 43.9 | $0.00106 | $0.00672 | 76.7% | 73104 | 56064 | 1409 |
| simplicio | 1/1 | 10 | 61.3 | $0.00147 | $0.00440 | 90.7% | 148630 | 134784 | 2924 |
| mapper-devcli | 1/1 | 12 | 73.3 | $0.00233 | $0.01312 | 88.3% | 244385 | 215808 | 3857 |
| devcli | 1/1 | 26 | 96.5 | $0.00328 | $0.01032 | 93.9% | 532103 | 499840 | 5684 |

## t4

- **Menor custo:** `normal` ($0.00180 calculado, $0.00840 cobrado, 4/4 ok)
- **Mais rápido:** `normal` (118.5s, 4/4 ok)
- ⚠ `mapper` falhou 1/4 tarefa(s)

### Total

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|
| normal | 4/4 | 16 | 118.5 | $0.00180 | $0.00840 | 73.4% | 131264 | 96384 | 1680 |
| mapper | 3/4 | 26 | 184.4 | $0.00470 | $0.02770 | 71.2% | 279722 | 199296 | 5809 |
| simplicio | 4/4 | 46 | 207.0 | $0.00688 | $0.03112 | 88.1% | 653458 | 576000 | 12374 |
| devcli | 4/4 | 60 | 344.0 | $0.00811 | $0.02893 | 90.3% | 971764 | 877184 | 13534 |
| mapper-devcli | 4/4 | 58 | 404.5 | $0.00973 | $0.03610 | 90.6% | 1262096 | 1143936 | 15352 |

### Criação (create)

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|
| normal | 2/2 | 8 | 70.5 | $0.00123 | $0.00475 | 63.0% | 69726 | 43904 | 984 |
| mapper | 2/2 | 14 | 114.2 | $0.00250 | $0.01241 | 74.1% | 154531 | 114560 | 3390 |
| simplicio | 2/2 | 25 | 118.8 | $0.00385 | $0.01532 | 89.0% | 360219 | 320512 | 7362 |
| mapper-devcli | 2/2 | 24 | 129.1 | $0.00398 | $0.01197 | 88.0% | 430503 | 379008 | 6218 |
| devcli | 2/2 | 27 | 105.5 | $0.00404 | $0.01555 | 88.6% | 435505 | 385664 | 6581 |

### Edição (edit)

| arm | ok/n | turns | wall (s) | custo calculado | custo cobrado | cache hit | tokens prompt | tokens cache | tokens completion |
|---|---|---|---|---|---|---|---|---|---|
| normal | 2/2 | 8 | 48.1 | $0.00057 | $0.00365 | 85.3% | 61538 | 52480 | 696 |
| mapper | 1/2 | 12 | 70.2 | $0.00220 | $0.01530 | 67.7% | 125191 | 84736 | 2419 |
| simplicio | 2/2 | 21 | 88.2 | $0.00303 | $0.01580 | 87.1% | 293239 | 255488 | 5012 |
| devcli | 2/2 | 33 | 238.6 | $0.00407 | $0.01338 | 91.7% | 536259 | 491520 | 6953 |
| mapper-devcli | 2/2 | 34 | 275.3 | $0.00575 | $0.02413 | 92.0% | 831593 | 764928 | 9134 |

