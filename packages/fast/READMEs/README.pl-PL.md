# simplicio-fast

[English](../README.md) · **Polski**

Binarny, przyrostowy i mapowany w pamięci kontekst semantyczny dla agentów programistycznych.

Zwykłe pliki źródłowe tworzą pochodną pamięć `.sfast`, odczytywaną przez `mmap`. Niezmienione
pliki są ponownie używane dzięki SHA-256, a kod źródłowy pozostaje jedynym źródłem prawdy.

W POC obejmującym 500 plików i 1 500 symboli zapytanie było około 23 razy szybsze i zużyło
95,65% mniej CPU. To wynik pomiaru, a nie uniwersalna gwarancja.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

W oficjalnym przepływie agentów `simplicio-mapper` jest obowiązkowy i tworzy kanoniczny
ContextGraph. Zobacz [AGENTS.md](../AGENTS.md) i [pełny README](../README.md).
