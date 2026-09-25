# simplicio-fast

[English](../README.md) · **Deutsch**

Binärer, inkrementeller und speicherabgebildeter semantischer Kontext für Software-Agenten.

Normale Quelldateien erzeugen einen abgeleiteten `.sfast`-Cache. Er wird über `mmap` gelesen;
unveränderte Dateien werden anhand von SHA-256 wiederverwendet. Der Quellcode bleibt die einzige
Wahrheitsquelle.

Im POC mit 500 Dateien und 1.500 Symbolen war die Abfrage etwa 23-mal schneller und benötigte
95,65 % weniger CPU. Dieses Messergebnis ist keine universelle Garantie.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

`simplicio-mapper` ist im offiziellen Agentenfluss verpflichtend und erzeugt weiterhin den
kanonischen ContextGraph. Siehe [AGENTS.md](../AGENTS.md) und [vollständiges README](../README.md).
