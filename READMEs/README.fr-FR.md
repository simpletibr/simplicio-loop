# 🔁 simplicio-loop

<p align="center">
  <a href="../docs/REPOSITORY_GOVERNANCE.md"><img src="https://img.shields.io/badge/CI-local%20gate%20is%20authoritative-888888" alt="Validation status: the local scripts/check.py gate is authoritative; GitHub Actions is not required evidence"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/simpletibr/simplicio-loop?style=social" alt="Stars"></a>
  <a href="../docs/EXTENSION_POINTS_SERVICE.md"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://discord.gg/wM6tr7xVb"><img src="https://img.shields.io/badge/Discord-Join%20Simplicio-5865F2?logo=discord&logoColor=white" alt="Join the Simplicio Discord"></a>
</p>

<p align="center">
  <a href="../README.md">🇬🇧 English</a> |
  <a href="README.pt-BR.md">🇧🇷 Português</a> |
  <a href="README.es-ES.md">🇪🇸 Español</a> |
  <a href="README.fr-FR.md">🇫🇷 Français</a> |
  <a href="README.de-DE.md">🇩🇪 Deutsch</a> |
  <a href="README.it-IT.md">🇮🇹 Italiano</a> |
  <a href="README.ja-JP.md">🇯🇵 日本語</a> |
  <a href="README.ko-KR.md">🇰🇷 한국어</a> |
  <a href="README.zh-CN.md">🇨🇳 简体中文</a> |
  <a href="README.ru-RU.md">🇷🇺 Русский</a> |
  <a href="README.pl-PL.md">🇵🇱 Polski</a> |
  <a href="README.tr-TR.md">🇹🇷 Türkçe</a> |
  <a href="README.nl-NL.md">🇳🇱 Nederlands</a> |
  <a href="README.hi-IN.md">🇮🇳 हिन्दी</a> |
  <a href="README.ar-SA.md">🇸🇦 العربية</a>
</p>

**simplicio-loop transforme les issues GitHub en PRs testées : il cartographie le dépôt, une IA planifie, un éditeur déterministe applique, les tests vérifient et les squads relisent.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="Flux animé en 8 étapes : issues, intake, coordinateur général, squads, workers en sandbox, revue du squad, merge train, main et le kanban Simplicio Live" width="100%" />
</p>

## Ce qu'il fait

Trois opérateurs : `simplicio-mapper` (carte), le modèle planificateur (plan), `simplicio-dev-cli` (application déterministe).

- **Cartographie d'abord :** `simplicio-mapper` cartographie le dépôt (fichiers, symboles, tests) en une carte du projet, et le planificateur ne reçoit que la tranche dont il a besoin.
- **Planifie, n'écrit jamais :** une IA (un CLI exec comme claude, codex, grok ou gemini) planifie chaque changement dans un sandbox ; seul le `dev-cli` déterministe modifie les fichiers.
- **Prouve avant d'ouvrir la PR :** `turbo --apply - --verify` lance vos tests, et une analyse des secrets tourne avant le push.
- **Les squads relisent et font le merge par lots** (en cours : [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Aujourd'hui, le watcher s'arrête à la PR ouverte.

## Installation

Nécessite Python 3.11+, `git` et un `gh` authentifié pour les issues GitHub.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Utilisation

**Dans Claude Code ou VS Code :**

```text
/simplicio-loop finish all the open issues
```

**En watcher 24/7** (un service qui surveille les dépôts `simpletibr/simplicio-*` et ouvre des PRs) :

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **Opt-in par dépôt :** ajoutez `.simplicio/loop.toml` avec `enabled = true`.
- **Opt-in par issue :** le label `loop:auto`, posé par un auteur de confiance (owner, member ou collaborator).
- **L'auto-merge est désactivé.** Le watcher ouvre seulement des PRs ; `SIMPLICIO_247_AUTO_MERGE=1` est en cours ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Détails : [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## Comment ça marche

**La boucle du worker** (sur `main` aujourd'hui) : `simplicio-mapper` cartographie le dépôt → le planificateur (un CLI exec, dans le sandbox) reçoit la tranche de la carte et écrit un plan → `simplicio-dev-cli` l'applique (`turbo --apply - --verify`) → les tests vérifient (deux échecs font monter le rôle du modèle) → analyse des secrets → PR. La revue du squad et le merge train sont en cours ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Boucle du worker : planification dans le sandbox, application et vérification, un échec, montée au rôle de modèle suivant, analyse des secrets, PR, revue du squad" width="920" />
</p>

**Le merge train** (en cours : [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)) : les PRs approuvées sont testées une fois en lot ; en cas d'échec, il fait une bissection jusqu'à la PR fautive et fusionne les autres.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train : 4 PRs testées une fois, rouge, la bissection isole C, puis A, B et D sont fusionnées" width="920" />
</p>

**Les squads** (en cours : [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)) : un coordinateur général, un coordinateur par squad, jusqu'à 4 workers chacun. Pourquoi : [un coordinateur contre des squads](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads.gif" alt="Organigramme des squads : un coordinateur général, un coordinateur par squad et jusqu'à 4 workers chacun" width="920" />
</p>


## Les 50 points d'extension

Le chemin du service 24/7 en branche 11 sur 50 (24 partiels, 15 absents) : [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). Le plan pour brancher le reste est la [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## En savoir plus

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Tout le reste : [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, la boucle, économie de tokens, sécurité, tests ; en anglais)
