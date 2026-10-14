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
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="Animierter Ablauf in 8 Schritten: Issues, Intake, Generalkoordinator, Squads, Worker in der Sandbox, Squad-Review, Merge-Train, main und das Kanban Simplicio Live" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="Animierter Ablauf in 8 Schritten: Issues, Intake, Generalkoordinator, Squads, Worker in der Sandbox, Squad-Review, Merge-Train, main und das Kanban Simplicio Live" width="100%" />
</p>

## Was es tut

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

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

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

Details: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## So funktioniert es

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="Worker-Schleife: Planen in der Sandbox, Anwenden und Prüfen, ein Fehlschlag, Eskalation zur nächsten Modellrolle, Secret-Scan, PR, Squad-Review" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="Merge-Train: 4 PRs einmal getestet, rot, die Bisektion isoliert C, dann werden A, B und D gemergt" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="Organigramm der Squads: ein Generalkoordinator, ein Koordinator pro Squad und bis zu 4 Worker je Squad" width="100%" />
</p>

```mermaid
flowchart TD
  G["General coordinator<br/>Opus / Fable: plans, never executes"] --> S1["Squad 1<br/>Sonnet coordinator"] & S2["Squad 2<br/>Sonnet coordinator"] & S3["Squad 3<br/>Sonnet coordinator"]
  S1 --> W1["up to 4 Haiku workers"]
  S2 --> W2["up to 4 Haiku workers"]
  S3 --> W3["up to 4 Haiku workers"]
  S1 & S2 & S3 -.->|"APPROVED BY SQUAD"| MC["Merge coordinator<br/>Sonnet: merges in series"] --> MAIN["main"]
```

<p align="center">
  <img src="../docs/assets/readme/agents-before-after-cartoon.webp" alt="1 coordinator and 29 workers versus squads: before and after" width="100%" />
</p>

## Die 50 Erweiterungspunkte

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## Mehr erfahren

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Alles andere: [docs/GUIDE.md](../docs/GUIDE.md)** (Skills, Runtimes, die Schleife, Token-Ersparnis, Sicherheit, Tests; auf Englisch)
