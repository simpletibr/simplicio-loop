# simplicio-mapper

> Trasforma un repository in contesto delimitato, interrogabile e affidabile per persone e agenti IA.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README canonico e tutte le lingue](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Un repository trasformato in contesto delimitato e basato su evidenze" width="100%"></p>

`simplicio-mapper` trasforma una codebase in artefatti versionati in `.simplicio/`: architettura, simboli, flussi, regole, test e pacchetti di contesto guidati dal compito. È il motore di mappatura dell’ecosistema Simplicio: conoscenza abbastanza compatta da ispezionare e abbastanza esplicita da verificare.

## Avvio rapido

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "traccia il flusso di autenticazione" --token-budget 1200 --json
```

## Cosa lo distingue

- **Recupero delimitato:** `handoff` e `orient` espongono rilevanza, copertura, budget di token, penalità e fedeltà invece di riversare silenziosamente l’intero repository nel prompt.
- **Contesto aggiornato ai cambiamenti:** `sync`, `history`, `diff` e `delta` mantengono il ContextGraph tra modifiche e sessioni.
- **Contratti di evidenza:** schemi pubblici, validazione, tag di confidenza, ricevute comportamentali e certificati distinguono fatti misurati da affermazioni non supportate.
- **Output pratici:** mappe, documentazione d’architettura, inventari di endpoint e schermate, flussi, regole di business, survey di onboarding e query al grafo.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Il pacchetto Python è il motore canonico. Il pacchetto npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) è uno starter complementare.

Consulta il [sito della documentazione](https://wesleysimplicio.github.io/simplicio-mapper/), i [contratti](../contracts/), la [guida di integrazione](../SIMPLICIO_INTEGRATION.md) e la [release v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Licenza [MIT](../LICENSE).
