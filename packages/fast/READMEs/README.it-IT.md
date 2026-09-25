# simplicio-fast

[English](../README.md) · **Italiano**

Contesto semantico binario, incrementale e mappato in memoria per agenti software.

I normali file sorgente producono una cache derivata `.sfast`, letta tramite `mmap`. I file
immutati vengono riutilizzati con SHA-256 e il sorgente rimane l'unica fonte di verità.

Nella POC con 500 file e 1.500 simboli, la query è risultata circa 23 volte più veloce con il
95,65% di CPU in meno. È un risultato misurato, non una garanzia universale.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

`simplicio-mapper` è obbligatorio nel flusso ufficiale degli agenti e mantiene il ContextGraph
canonico. Vedere [AGENTS.md](../AGENTS.md) e il [README completo](../README.md).
