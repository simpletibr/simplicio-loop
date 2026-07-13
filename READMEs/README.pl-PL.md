# simplicio-mapper

> Zamień repozytorium w ograniczony, możliwy do zapytania i godny zaufania kontekst dla ludzi oraz agentów AI.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[Kanoniczny README i wszystkie języki](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Repozytorium przekształcone w ograniczony kontekst oparty na dowodach" width="100%"></p>

`simplicio-mapper` zamienia bazę kodu w wersjonowane artefakty w `.simplicio/`: architekturę, symbole, przepływy, reguły, testy i pakiety kontekstu zależne od zadania. To silnik mapowania ekosystemu Simplicio — wiedza o repozytorium jest wystarczająco mała do inspekcji i wystarczająco jawna do audytu.

## Szybki start

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "prześledź przepływ uwierzytelniania" --token-budget 1200 --json
```

## Co go wyróżnia

- **Ograniczone wyszukiwanie:** `handoff` i `orient` pokazują trafność, pokrycie, budżet tokenów, kary i wierność zamiast po cichu wkładać całe repozytorium do promptu.
- **Kontekst świadomy zmian:** `sync`, `history`, `diff` i `delta` utrzymują ContextGraph między zmianami i sesjami.
- **Kontrakty dowodowe:** publiczne schematy, walidacja, etykiety pewności, potwierdzenia behawioralne i certyfikaty oddzielają zmierzone fakty od nieudokumentowanych twierdzeń.
- **Praktyczne wyniki:** mapy projektu, dokumentacja architektury, inwentarze endpointów i ekranów, przepływy, reguły biznesowe, ankiety onboardingowe i zapytania do grafu.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Pakiet Python jest kanonicznym silnikiem. Pakiet npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) jest uzupełniającym starterem.

Zobacz [stronę dokumentacji](https://wesleysimplicio.github.io/simplicio-mapper/), [kontrakty](../contracts/), [przewodnik integracji](../SIMPLICIO_INTEGRATION.md) oraz [release v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Licencja [MIT](../LICENSE).
