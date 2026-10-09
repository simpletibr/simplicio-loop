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

**simplicio-loop maakt van GitHub-issues geteste PR's: het brengt de repo in kaart, een AI plant, een deterministische editor past toe, tests verifiëren, squads reviewen.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="Geanimeerde flow in 8 stappen: issues, intake, algemeen coördinator, squads, workers (mapper, plan, dev-cli), squad-review, merge train, main en het Simplicio Live-kanban" width="920" />
</p>

## Wat het doet

Drie operators: `simplicio-mapper` (kaart), het planner-model (plan), `simplicio-dev-cli` (deterministisch toepassen).

- **Eerst in kaart brengen:** `simplicio-mapper` brengt de repo (bestanden, symbolen, tests) in kaart als projectkaart, en de planner krijgt alleen het stuk dat hij nodig heeft.
- **Plant, schrijft nooit:** een AI (een exec-CLI zoals claude, codex, grok of gemini) plant elke wijziging in een sandbox; alleen de deterministische `dev-cli` bewerkt bestanden.
- **Bewijst voordat het een PR opent:** `turbo --apply - --verify` draait je tests, en vóór de push draait een secret-scan.
- **Squads reviewen en mergen in batches** (in uitvoering: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Vandaag stopt de watcher bij een open PR.

## Installatie

Vereist Python 3.11+, `git` en een geauthenticeerde `gh` voor GitHub-issues.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Gebruik

**In Claude Code of VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Als 24/7-watcher** (een service die `simpletibr/simplicio-*`-repo's in de gaten houdt en PR's opent):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **Opt-in per repo:** voeg `.simplicio/loop.toml` toe met `enabled = true`.
- **Opt-in per issue:** het label `loop:auto`, gezet door een vertrouwde auteur (owner, member of collaborator).
- **Auto-merge staat uit.** De watcher opent alleen PR's; `SIMPLICIO_247_AUTO_MERGE=1` is in uitvoering ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Details: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## Hoe het werkt

**De worker-loop** (vandaag op `main`): `simplicio-mapper` brengt de repo in kaart → de planner (een exec-CLI, in de sandbox) krijgt het kaartstuk en schrijft een plan → `simplicio-dev-cli` past het toe (`turbo --apply - --verify`) → tests verifiëren (twee mislukkingen verhogen de modelrol) → secret-scan → PR. Squad-review en de merge train zijn in uitvoering ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Worker-loop: mapper brengt de repo in kaart, plannen in de sandbox, toepassen en verifiëren, een mislukking, escalatie naar de volgende modelrol, secret-scan, PR, squad-review" width="920" />
</p>

**De merge train** (in uitvoering: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): goedgekeurde PR's worden één keer als batch getest; bij rood zoekt bisectie de foute PR op en wordt de rest gemerged.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train: 4 PR's één keer getest, rood, bisectie isoleert C, daarna worden A, B en D gemerged" width="920" />
</p>

**De squads** (in uitvoering: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): een algemeen coördinator, een coördinator per squad, tot 4 workers per squad. Waarom: [één coördinator tegenover squads](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads-cartoon.webp" alt="Organigram van de squads: een algemeen coördinator, een coördinator per squad en tot 4 workers per squad" width="920" />
</p>

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="De hele flow: issues, intake, algemeen coördinator, squads, workers in de sandbox, dev-cli, squad-goedkeuring, merge train, main en het Simplicio Live-kanban" width="920" />
</p>

## De 50 extensiepunten

Het 24/7-servicepad koppelt 11 van de 50 (24 gedeeltelijk, 15 ontbreken): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). Het plan om de rest te koppelen is [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## Meer weten

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Al het andere: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, de loop, tokenbesparing, veiligheid, tests; in het Engels)
