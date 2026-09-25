# simplicio-fast

[English](../README.md) · **Nederlands**

Binaire, incrementele en memory-mapped semantische context voor softwareagents.

Normale bronbestanden leveren een afgeleide `.sfast`-cache die via `mmap` wordt gelezen.
Ongewijzigde bestanden worden met SHA-256 hergebruikt; de broncode blijft de enige waarheid.

In de POC met 500 bestanden en 1.500 symbolen was de query ongeveer 23 keer sneller en gebruikte
deze 95,65% minder CPU. Dit is een gemeten resultaat, geen universele garantie.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

In de officiële agentflow is `simplicio-mapper` verplicht en blijft het de producent van de
canonieke ContextGraph. Zie [AGENTS.md](../AGENTS.md) en de [volledige README](../README.md).
