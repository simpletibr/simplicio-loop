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

**simplicio-loop macht aus GitHub-Issues getestete PRs: Es kartiert das Repo, eine KI plant, ein deterministischer Editor wendet an, Tests prüfen, Squads reviewen.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="Animierter Ablauf in 8 Schritten: Issues, Intake, Generalkoordinator, Squads, Worker in der Sandbox, Squad-Review, Merge-Train, main und das Kanban Simplicio Live" width="100%" />
</p>

## Was es tut

Drei Operatoren: `simplicio-mapper` (Karte), das Planer-Modell (Plan), `simplicio-dev-cli` (deterministisches Anwenden).

- **Kartiert zuerst:** `simplicio-mapper` kartiert das Repo (Dateien, Symbole, Tests) zu einer Projektkarte, und der Planer bekommt nur den Ausschnitt, den er braucht.
- **Plant, schreibt nie:** Eine KI (ein Exec-CLI wie claude, codex, grok oder gemini) plant jede Änderung in einer Sandbox; nur das deterministische `dev-cli` bearbeitet Dateien.
- **Beweist, bevor es einen PR öffnet:** `turbo --apply - --verify` führt Ihre Tests aus, und vor dem Push läuft ein Secret-Scan.
- **Squads reviewen und mergen in Batches** (in Arbeit: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Heute hält der Watcher bei einem offenen PR an.

## Installation

Benötigt Python 3.11+, `git` und ein authentifiziertes `gh` für GitHub-Issues.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Verwendung

**In Claude Code oder VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Als 24/7-Watcher** (ein Dienst, der `simpletibr/simplicio-*`-Repos beobachtet und PRs öffnet):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **Opt-in pro Repo:** Legen Sie `.simplicio/loop.toml` mit `enabled = true` an.
- **Opt-in pro Issue:** das Label `loop:auto`, gesetzt von einem vertrauenswürdigen Autor (Owner, Member oder Collaborator).
- **Auto-Merge ist aus.** Der Watcher öffnet nur PRs; `SIMPLICIO_247_AUTO_MERGE=1` ist in Arbeit ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Details: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## So funktioniert es

**Die Worker-Schleife** (heute auf `main`): `simplicio-mapper` kartiert das Repo → der Planer (ein Exec-CLI, in der Sandbox) bekommt den Kartenausschnitt und schreibt einen Plan → `simplicio-dev-cli` wendet ihn an (`turbo --apply - --verify`) → Tests prüfen (zwei Fehlschläge eskalieren die Modellrolle) → Secret-Scan → PR. Squad-Review und Merge-Train sind in Arbeit ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Worker-Schleife: Planen in der Sandbox, Anwenden und Prüfen, ein Fehlschlag, Eskalation zur nächsten Modellrolle, Secret-Scan, PR, Squad-Review" width="920" />
</p>

**Der Merge-Train** (in Arbeit: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): freigegebene PRs werden einmal als Batch getestet; bei Rot wird per Bisektion der fehlerhafte PR gefunden und der Rest gemergt.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge-Train: 4 PRs einmal getestet, rot, die Bisektion isoliert C, dann werden A, B und D gemergt" width="920" />
</p>

**Die Squads** (in Arbeit: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): ein Generalkoordinator, ein Koordinator pro Squad, bis zu 4 Worker je Squad. Warum: [ein Koordinator gegen Squads](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads.gif" alt="Organigramm der Squads: ein Generalkoordinator, ein Koordinator pro Squad und bis zu 4 Worker je Squad" width="920" />
</p>


## Die 50 Erweiterungspunkte

Der 24/7-Servicepfad verdrahtet 11 der 50 (24 teilweise, 15 fehlen): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). Der Plan, den Rest zu verdrahten, ist [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## Mehr erfahren

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Alles andere: [docs/GUIDE.md](../docs/GUIDE.md)** (Skills, Runtimes, die Schleife, Token-Ersparnis, Sicherheit, Tests; auf Englisch)
