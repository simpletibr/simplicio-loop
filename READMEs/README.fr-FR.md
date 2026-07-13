# simplicio-mapper

> Transformez un dépôt en contexte borné, interrogeable et fiable pour les humains et les agents d’IA.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README canonique et toutes les langues](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Un dépôt devenant un contexte borné étayé par des preuves" width="100%"></p>

`simplicio-mapper` transforme une base de code en artefacts versionnés dans `.simplicio/` : architecture, symboles, flux, règles, tests et paquets de contexte adaptés à une tâche. C’est le moteur de cartographie de l’écosystème Simplicio, conçu pour rendre la connaissance d’un dépôt assez compacte pour être inspectée et assez explicite pour être auditée.

## Démarrage rapide

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "retracer le flux d’authentification" --token-budget 1200 --json
```

## Ce qui change

- **Recherche bornée :** `handoff` et `orient` exposent pertinence, couverture, budget de tokens, pénalités et fidélité au lieu d’envoyer silencieusement tout le dépôt dans un prompt.
- **Contexte sensible aux changements :** `sync`, `history`, `diff` et `delta` maintiennent le ContextGraph entre changements et sessions.
- **Contrats de preuve :** schémas publics, validation, étiquettes de confiance, reçus comportementaux et certificats distinguent les faits mesurés des affirmations non étayées.
- **Sorties utiles :** cartes du projet, documentation d’architecture, inventaires d’endpoints et d’écrans, flux, règles métier, enquête d’onboarding et requêtes de graphe.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Le paquet Python est le moteur canonique. [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) pour npm est un starter complémentaire.

Voir le [site de documentation](https://wesleysimplicio.github.io/simplicio-mapper/), les [contrats](../contracts/), le [guide d’intégration](../SIMPLICIO_INTEGRATION.md) et la [release v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Licence [MIT](../LICENSE).
